# -*- coding: utf-8 -*-
"""Forward high-priority editorial topics to Telegram and record '+' replies."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
SECRETS = ROOT / ".secrets"
TOKEN_FILE = SECRETS / "telegram_bot_token.txt"
CHAT_ID_FILE = SECRETS / "telegram_chat_id.txt"
STATE_FILE = RUNTIME / "editorial_telegram_state.json"
QUEUE_FILE = RUNTIME / "predictor_queue.json"
POLL_TIMEOUT = 15
MAX_INITIAL_TOPICS = 3
OMSK_TZ = timezone(timedelta(hours=6), name="Asia/Omsk")
GITHUB_REPO = "fisenkobusiness-sketch/omsk-news-live"
GITHUB_BRANCH = "smm-newmodel-codex"
PUBLISHED_PATH = "PUBLISHED_TOPICS.json"
TELEGRAM_API = "https://api.telegram.org"

sys.path.insert(0, str(ROOT / "src"))
from live_monitor import get_github_token, github_request  # noqa: E402


def read_secret(filename: str, env_name: str) -> str:
    value = os.getenv(env_name, "").strip()
    path = SECRETS / filename
    if not value and path.exists():
        value = path.read_text(encoding="utf-8").strip()
    return value


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_state(state: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def telegram_call(method: str, token: str, *, params=None, data=None) -> dict[str, Any]:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    response = requests.get(url, params=params, timeout=POLL_TIMEOUT + 10) if params is not None else requests.post(
        url, data=data, timeout=25
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API {method}: {result}")
    return result


def send_message(token: str, chat_id: str, message: str) -> dict[str, Any]:
    return telegram_call(
        "sendMessage",
        token,
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
    )["result"]


def current_date() -> str:
    return datetime.now(OMSK_TZ).date().isoformat()


def topic_title(topic: dict[str, Any]) -> str:
    text = str(topic.get("text") or "").strip()
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def source_for(topic: dict[str, Any]) -> tuple[str, str, str]:
    primary_url = str(topic.get("primary_url") or "").strip()
    primary_source = str(topic.get("primary_source") or "")
    members = [m for m in topic.get("members", []) if isinstance(m, dict)]
    selected = next(
        (m for m in members if (primary_url and m.get("url") == primary_url)
         or (primary_source and m.get("source") == primary_source)),
        members[0] if members else {},
    )
    url = primary_url or str(selected.get("url") or "").strip()
    if not url:
        urls = topic.get("source_urls") or []
        url = str(urls[0]).strip() if urls else ""
    text = str(selected.get("text") or topic.get("text") or "").strip()
    source_name = str(selected.get("source_name") or primary_source or "Источник").strip()
    return text, source_name, url


def audience_label(topic: dict[str, Any]) -> str:
    models = (topic.get("prediction") or {}).get("audience_model_predictions") or {}
    scores = {}
    for key, label in (("golos", "Голос Омска"), ("zhest", "Жесть Омска")):
        value = (models.get(key) or {}).get("priority_score")
        if isinstance(value, (int, float)):
            scores[label] = float(value)
    if len(scores) < 2:
        return "Аудиторию выбери по ситуации"
    names = list(scores)
    if abs(scores[names[0]] - scores[names[1]]) < 0.05:
        return "Подходит обоим пабликам"
    return max(scores, key=scores.get)


def topic_keys(topic: dict[str, Any]) -> tuple[str, set[str]]:
    title = topic_title(topic)
    source_text, _, source_url = source_for(topic)
    primary_url = str(topic.get("primary_url") or source_url).strip()
    member_keys = set()
    for member in topic.get("members", []) or []:
        if not isinstance(member, dict):
            continue
        source = str(member.get("source") or "").strip()
        post_id = str(member.get("id") or "").strip()
        url = str(member.get("url") or "").strip()
        if source and post_id:
            member_keys.add(f"{source}:{post_id}")
        elif url:
            member_keys.add(url)
    if primary_url:
        member_keys.add(primary_url)
    return primary_url or title.casefold()[:240], member_keys


def is_actionable(topic: Any) -> bool:
    if not isinstance(topic, dict):
        return False
    prediction = topic.get("prediction") or {}
    newest = topic.get("newest_source_timestamp")
    try:
        age_seconds = time.time() - float(newest or 0)
    except (TypeError, ValueError):
        return False
    return (
        0 <= age_seconds <= 180 * 60
        and topic.get("status") == "take_now"
        and topic.get("publication_mode") == "editorial_work"
        and prediction.get("eligible") is True
        and float(prediction.get("priority_score") or 0) >= 45
    )


def audience_model_score(topic: dict[str, Any]) -> float | None:
    models = (topic.get("prediction") or {}).get("audience_model_predictions") or {}
    scores = [
        value.get("priority_score")
        for value in models.values()
        if isinstance(value, dict) and isinstance(value.get("priority_score"), (int, float))
    ]
    return max(scores) if scores else None


def get_ranked_topics(queue: dict[str, Any]) -> list[dict[str, Any]]:
    topics = [topic for topic in queue.get("topics", []) if is_actionable(topic)]
    topics.sort(
        key=lambda item: (
            audience_model_score(item) is not None,
            audience_model_score(item) or 0.0,
            float((item.get("prediction") or {}).get("priority_score") or 0),
        ),
        reverse=True,
    )
    return topics


def build_message(topic: dict[str, Any], rank: int) -> tuple[str, dict[str, Any]]:
    source_text, source_name, source_url = source_for(topic)
    title = topic_title(topic)
    category_label = audience_label(topic)
    head = f"📰 Кандидат #{rank} · {category_label}\nИсточник: {source_name}\n\n"
    tail = (
        f"\n\nСсылка на исходную публикацию:\n{source_url}"
        "\n\nСкопируй это сообщение в чат с Codex для готового поста. "
        "После публикации ответь «+» реплаем на это сообщение."
    )
    body_limit = max(0, 4096 - len(head) - len(tail) - 40)
    shortened = len(source_text) > body_limit
    if shortened:
        source_text = source_text[:max(0, body_limit - 35)].rstrip() + "\n… Текст сокращён."
    message = head + source_text + tail
    if len(message) > 4096:
        message = message[:4050].rstrip() + "\n… Текст сокращён.\n" + source_url
    keys, members = topic_keys(topic)
    metadata = {
        "topic_key": keys,
        "member_keys": sorted(members),
        "title": title,
        "category": "ГОЛОС" if category_label == "Голос Омска" else "ЖЕСТЬ" if category_label == "Жесть Омска" else "",
        "source_url": source_url,
    }
    return message, metadata


def initial_state() -> dict[str, Any]:
    return {
        "date": current_date(),
        "initialized": False,
        "offset": None,
        "sent_topic_keys": [],
        "sent_member_keys": [],
        "message_topics": {},
    }


def migrate_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        state = initial_state()
    state.setdefault("date", current_date())
    state.setdefault("initialized", False)
    state.setdefault("offset", None)
    state.setdefault("sent_topic_keys", [])
    state.setdefault("sent_member_keys", [])
    state.setdefault("message_topics", {})
    if state["date"] != current_date():
        state["date"] = current_date()
        state["initialized"] = False
        state["sent_topic_keys"] = []
        state["sent_member_keys"] = []
    return state


def send_candidate(token: str, chat_id: str, topic: dict[str, Any], rank: int, state: dict[str, Any]) -> bool:
    source_text, _, source_url = source_for(topic)
    if not source_text or not source_url:
        return False
    message, metadata = build_message(topic, rank)
    try:
        sent = send_message(token, chat_id, message)
    except Exception as exc:
        print(f"[Telegram bot] Не удалось отправить кандидата: {exc}", flush=True)
        return False
    state["message_topics"][str(sent["message_id"])] = metadata
    state["sent_topic_keys"].append(metadata["topic_key"])
    state["sent_member_keys"].extend(metadata["member_keys"])
    save_state(state)
    return True


def deliver_candidates(token: str, chat_id: str, state: dict[str, Any]) -> None:
    queue = load_json(QUEUE_FILE, {})
    if not isinstance(queue, dict) or str(queue.get("generated_at") or "")[:10] != current_date():
        return

    topics = get_ranked_topics(queue)
    seen_topics = set(state["sent_topic_keys"])
    seen_members = set(state["sent_member_keys"])
    fresh = []
    for topic in topics:
        key, members = topic_keys(topic)
        if not key or key in seen_topics or members.intersection(seen_members):
            continue
        if not source_for(topic)[2]:
            continue
        fresh.append(topic)
        seen_topics.add(key)
        seen_members.update(members)

    if not state["initialized"]:
        # Send only the top three already collected candidates on first start.
        selected = fresh[:MAX_INITIAL_TOPICS]
        for rank, topic in enumerate(selected, 1):
            if not send_candidate(token, chat_id, topic, rank, state):
                return
            sent_topics = set(state["sent_topic_keys"])
            sent_members = set(state["sent_member_keys"])
        # Keep the rest of the pre-existing queue from arriving as a backlog.
        for topic in fresh[MAX_INITIAL_TOPICS:]:
            key, members = topic_keys(topic)
            if key:
                state["sent_topic_keys"].append(key)
            state["sent_member_keys"].extend(members)
        state["initialized"] = True
        save_state(state)
        return

    for topic in fresh:
        key, _ = topic_keys(topic)
        rank = next((i for i, item in enumerate(topics, 1) if topic_keys(item)[0] == key), 0)
        if not send_candidate(token, chat_id, topic, rank or 1, state):
            return
        sent_topics = set(state["sent_topic_keys"])
        sent_members = set(state["sent_member_keys"])


def normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def append_published_topic(metadata: dict[str, Any]) -> bool:
    title = str(metadata.get("title") or "").strip()
    if not title:
        raise RuntimeError("У темы отсутствует заголовок.")
    token = get_github_token()
    for attempt in range(2):
        _, remote = github_request(
            "GET", f"/contents/{PUBLISHED_PATH}?ref={GITHUB_BRANCH}", token
        )
        raw = base64.b64decode(remote.get("content", "")).decode("utf-8")
        registry = json.loads(raw)
        topics = registry.setdefault("topics", [])
        url = str(metadata.get("source_url") or "").strip()
        existing = next(
            (
                item for item in topics
                if (url and item.get("source_url") == url)
                or normalize_title(str(item.get("title") or "")) == normalize_title(title)
            ),
            None,
        )
        if existing:
            existing["status"] = "published"
            if metadata.get("category"):
                existing["category"] = metadata["category"]
            existing["source_url"] = url or existing.get("source_url", "")
            existing["note"] = (
                f"Пользователь ответил «+» на сообщение бота; "
                f"{datetime.now(OMSK_TZ).strftime('%Y-%m-%d')}."
            )
        else:
            topics.append(
                {
                    "title": title,
                    "status": "published",
                    "category": str(metadata.get("category") or ""),
                    "source_url": url,
                    "note": (
                        f"Пользователь ответил «+» на сообщение бота; "
                        f"{datetime.now(OMSK_TZ).strftime('%Y-%m-%d')}."
                    ),
                }
            )
        payload = {
            "message": f"Record Telegram-published topic: {title[:60]}",
            "content": base64.b64encode(
                (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            ).decode("ascii"),
            "sha": remote["sha"],
            "branch": GITHUB_BRANCH,
        }
        try:
            github_request("PUT", f"/contents/{PUBLISHED_PATH}", token, payload)
            return not bool(existing)
        except RuntimeError as exc:
            if attempt == 0 and "GitHub API 409" in str(exc):
                continue
            raise
    raise RuntimeError("Не удалось обновить реестр опубликованных тем.")


def handle_update(update: dict[str, Any], token: str, chat_id: str, state: dict[str, Any]) -> bool:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if str(chat.get("id") or "") != chat_id or chat.get("type") != "private":
        return True
    if str(message.get("text") or "").strip() != "+":
        return True
    reply = message.get("reply_to_message") or {}
    metadata = state["message_topics"].get(str(reply.get("message_id") or ""))
    if not metadata:
        return True
    if metadata.get("published"):
        send_message(token, chat_id, "✅ Эта тема уже отмечена опубликованной.")
        return True
    try:
        created = append_published_topic(metadata)
    except Exception as exc:
        send_message(token, chat_id, f"Не удалось обновить реестр: {str(exc)[:300]}")
        return False
    metadata["published"] = True
    save_state(state)
    status = "добавил" if created else "обновил"
    send_message(token, chat_id, f"✅ Отметил опубликованной и {status} в реестр:\n{metadata['title']}")
    return True


def poll_updates(token: str, chat_id: str, state: dict[str, Any]) -> None:
    params = {"timeout": POLL_TIMEOUT, "allowed_updates": json.dumps(["message"])}
    if state.get("offset") is not None:
        params["offset"] = int(state["offset"])
    result = telegram_call("getUpdates", token, params=params)
    updates = result.get("result", [])
    for update in updates:
        if not handle_update(update, token, chat_id, state):
            break
        state["offset"] = int(update["update_id"]) + 1
        save_state(state)


def main() -> int:
    token = read_secret("telegram_bot_token.txt", "TELEGRAM_BOT_TOKEN")
    chat_id = read_secret("telegram_chat_id.txt", "TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(
            "Telegram-бот не запущен: настройте telegram_bot_token.txt и telegram_chat_id.txt.",
            flush=True,
        )
        return 1
    RUNTIME.mkdir(parents=True, exist_ok=True)
    state = migrate_state(load_json(STATE_FILE, initial_state()))
    save_state(state)
    print("Telegram-бот редакционных тем запущен.", flush=True)
    while True:
        try:
            state = migrate_state(load_json(STATE_FILE, state))
            deliver_candidates(token, chat_id, state)
            poll_updates(token, chat_id, state)
        except KeyboardInterrupt:
            print("Telegram-бот остановлен.", flush=True)
            return 0
        except Exception as exc:
            print(f"[Telegram bot] Ошибка цикла: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
