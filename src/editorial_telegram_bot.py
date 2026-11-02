# -*- coding: utf-8 -*-
"""Forward high-priority editorial topics to Telegram and record '+' replies."""
from __future__ import annotations

import base64
import json
import os
import re
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
GITHUB_BRANCH = "main"
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
    try:
        response = requests.get(url, params=params, timeout=POLL_TIMEOUT + 10) if params is not None else requests.post(
            url, data=data, timeout=25
        )
    except requests.exceptions.RequestException as exc:
        safe_error = str(exc).replace(token, "[token скрыт]")
        raise RuntimeError(f"Telegram API {method}: {safe_error}") from exc

    try:
        result = response.json()
    except ValueError:
        result = {}
    if not response.ok or not result.get("ok"):
        description = result.get("description") or response.reason
        raise RuntimeError(
            f"Telegram API {method}: HTTP {response.status_code}: {description}"
        )
    return result


def telegram_text_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def truncate_telegram_text(value: str, max_units: int) -> str:
    chunks = []
    used = 0
    for char in value:
        units = 2 if ord(char) > 0xFFFF else 1
        if used + units > max_units:
            break
        chunks.append(char)
        used += units
    return "".join(chunks)


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


def clean_editorial_text(value: str) -> str:
    # Remove common Unicode emoji ranges while keeping ordinary punctuation and letters.
    value = re.sub(
        "["
        "\\U0001F000-\\U0001FAFF"
        "\\U00002600-\\U000027BF"
        "\\U00002300-\\U000023FF"
        "\\U0001F1E6-\\U0001F1FF"
        "\\U0001F3FB-\\U0001F3FF"
        "\\uFE0E\\uFE0F\\u200D\\u20E3"
        "]+",
        "",
        value,
    )
    return " ".join(value.split())


def display_source_name(value: str) -> str:
    name = " ".join(str(value or "Источник").split())
    if name and name.isupper():
        # Turn all-caps source labels into readable names, retaining short acronyms.
        name = " ".join(
            word if len(word) <= 3 else word.capitalize()
            for word in name.split()
        )
    return name or "Источник"


STORY_STOPWORDS = {
    "омск", "област", "регион", "город", "район", "новост", "публикац",
    "информац", "источник", "сообщ", "заяв", "канал", "виде", "ролик",
    "сайт", "редакц", "сегодня", "вчера", "сейчас", "полици", "следств",
    "данн", "автор", "человек", "мужчин", "женщин", "котор", "сам",
}
STORY_SUFFIXES = tuple(sorted(
    (
        "иями", "ями", "ами", "ирует", "ировать", "оваться",
        "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя", "ое", "ее",
        "ые", "ие", "ую", "юю", "ов", "ев", "ей", "ам", "ям", "ах", "ях",
        "ом", "ем", "ой", "ий", "ый", "а", "я", "ы", "и", "е", "у", "ю",
        "ь", "й", "ся", "сь", "ет", "ит", "ют", "ут", "ят", "ать", "ить",
        "ять", "ешь", "ишь", "лся", "лась", "лись", "ясь",
    ),
    key=len,
    reverse=True,
))


def story_terms(value: str) -> set[str]:
    value = clean_editorial_text(value).casefold().replace("ё", "е")
    terms = set()
    for word in re.findall(r"[a-zа-я0-9]+", value):
        if word.isdigit():
            continue
        term = word
        for suffix in STORY_SUFFIXES:
            if term.endswith(suffix) and len(term) - len(suffix) >= 4:
                term = term[:-len(suffix)]
                break
        if len(term) >= 4 and term not in STORY_STOPWORDS:
            terms.add(term)
    return terms


def story_record_for_topic(topic: dict[str, Any]) -> dict[str, str]:
    source_text, _, _ = source_for(topic)
    return {
        "title": clean_editorial_text(topic_title(topic)),
        "story_text": clean_editorial_text(source_text)[:900],
    }


def same_story(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = story_terms(str(left.get("title") or ""))
    right_title = story_terms(str(right.get("title") or ""))
    left_text = story_terms(
        str(left.get("title") or "") + " " + str(left.get("story_text") or "")
    )
    right_text = story_terms(
        str(right.get("title") or "") + " " + str(right.get("story_text") or "")
    )

    def title_matches_story(title_terms: set[str], story_terms_set: set[str]) -> bool:
        shared = title_terms & story_terms_set
        return len(shared) >= 3 and len(shared) / max(1, len(title_terms)) >= 0.4

    return (
        title_matches_story(left_title, right_text)
        or title_matches_story(right_title, left_text)
    )


def build_message(topic: dict[str, Any], rank: int) -> tuple[str, dict[str, Any]]:
    source_text, source_name, source_url = source_for(topic)
    title = clean_editorial_text(topic_title(topic))
    category_label = audience_label(topic)

    lines = [clean_editorial_text(line) for line in source_text.splitlines()]
    lines = [line for line in lines if line]
    if title and lines and lines[0].casefold() == title.casefold():
        lines = lines[1:]
    body = " ".join(" ".join(lines).split())
    source_line = f"«{display_source_name(source_name)}»"
    head = f"📰 Кандидат #{rank} · {category_label}"
    title_block = f"\n\n{title}" if title else ""
    tail = f"\n\n{source_line}\n\nСсылка: {source_url}"
    body_prefix = f"{head}{title_block}\n\n"
    body_limit = max(
        0,
        3900 - telegram_text_units(body_prefix) - telegram_text_units(tail) - 10,
    )
    if telegram_text_units(body) > body_limit:
        marker = "…"
        body = truncate_telegram_text(
            body, max(0, body_limit - telegram_text_units(marker))
        ).rstrip() + marker
    message = body_prefix + body + tail

    keys, members = topic_keys(topic)
    metadata = {
        "topic_key": keys,
        "member_keys": sorted(members),
        "title": title,
        "category": "ГОЛОС" if category_label == "Голос Омска" else "ЖЕСТЬ" if category_label == "Жесть Омска" else "",
        "source_url": source_url,
        "story_text": clean_editorial_text(source_text)[:900],
    }
    return message, metadata


def initial_state() -> dict[str, Any]:
    return {
        "date": current_date(),
        "initialized": False,
        "offset": None,
        "sent_topic_keys": [],
        "sent_member_keys": [],
        "sent_story_texts": [],
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
    if not isinstance(state.get("message_topics"), dict):
        state["message_topics"] = {}
    if not isinstance(state.get("sent_story_texts"), list):
        state["sent_story_texts"] = [
            {"title": str(item.get("title") or ""), "story_text": str(item.get("story_text") or "")}
            for item in state["message_topics"].values()
            if isinstance(item, dict) and item.get("title")
        ]
    else:
        state["sent_story_texts"] = [
            item for item in state["sent_story_texts"] if isinstance(item, dict)
        ]
    if state["date"] != current_date():
        state["date"] = current_date()
        state["initialized"] = False
        state["sent_topic_keys"] = []
        state["sent_member_keys"] = []
        state["sent_story_texts"] = []
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
    state["message_topics"][f"{chat_id}:{sent['message_id']}"] = metadata
    state["sent_topic_keys"].append(metadata["topic_key"])
    state["sent_member_keys"].extend(metadata["member_keys"])
    state["sent_story_texts"].append(
        {"title": metadata["title"], "story_text": metadata["story_text"]}
    )
    save_state(state)
    return True


def deliver_candidates(token: str, chat_id: str, state: dict[str, Any]) -> None:
    queue = load_json(QUEUE_FILE, {})
    if not isinstance(queue, dict) or str(queue.get("generated_at") or "")[:10] != current_date():
        return

    topics = get_ranked_topics(queue)
    seen_topics = set(state["sent_topic_keys"])
    seen_members = set(state["sent_member_keys"])
    seen_stories = list(state["sent_story_texts"])
    fresh = []
    for topic in topics:
        key, members = topic_keys(topic)
        if not key or key in seen_topics or members.intersection(seen_members):
            continue
        if not source_for(topic)[2]:
            continue
        story = story_record_for_topic(topic)
        if any(same_story(story, previous) for previous in seen_stories):
            continue
        fresh.append(topic)
        seen_stories.append(story)
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
            state["sent_story_texts"].append(story_record_for_topic(topic))
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


def rejection_reply_title(metadata: dict[str, Any]) -> str:
    title = clean_editorial_text(str(metadata.get("title") or ""))
    if not title:
        return "Без заголовка"
    match = re.search(r"[.!?…](?=\s|$)", title)
    if match and match.end() < len(title):
        return title[:match.end()].strip()
    return title[:240].rstrip()


def append_topic_status(
    metadata: dict[str, Any], status: str, symbol: str
) -> bool:
    title = str(metadata.get("title") or "").strip()
    if not title:
        raise RuntimeError("У темы отсутствует заголовок.")
    token = get_github_token()
    date = datetime.now(OMSK_TZ).strftime("%Y-%m-%d")
    note = f"Пользователь ответил «{symbol}» на сообщение бота; {date}."
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
            if status == "rejected" and existing.get("status") == "published":
                raise RuntimeError("Эта тема уже отмечена опубликованной.")
            existing["status"] = status
            if metadata.get("category"):
                existing["category"] = metadata["category"]
            existing["source_url"] = url or existing.get("source_url", "")
            existing["note"] = note
        else:
            topics.append(
                {
                    "title": title,
                    "status": status,
                    "category": str(metadata.get("category") or ""),
                    "source_url": url,
                    "note": note,
                }
            )
        payload = {
            "message": f"Record {status} topic: {title[:60]}",
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
    raise RuntimeError("Не удалось обновить реестр тем.")


def append_published_topic(metadata: dict[str, Any]) -> bool:
    return append_topic_status(metadata, "published", "+")


def append_rejected_topic(metadata: dict[str, Any]) -> bool:
    return append_topic_status(metadata, "rejected", "-")


def handle_update(update: dict[str, Any], token: str, chat_id: str, state: dict[str, Any]) -> bool:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    incoming_chat_id = str(chat.get("id") or "")
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
    if command == "/start":
        if incoming_chat_id == chat_id:
            reply = "✅ Бот подключён к этому чату. Новые подходящие темы будут приходить сюда."
        else:
            reply = (
                "✅ Бот получил команду. Числовой ID этого чата:\n"
                f"{incoming_chat_id}\n\n"
                "Скопируй это число в файл .secrets/telegram_chat_id.txt "
                "в папке проекта и перезапусти комбайн."
            )
        send_message(token, incoming_chat_id, reply)
        return True
    if incoming_chat_id != chat_id:
        return True
    if text not in {"+", "-"}:
        return True
    reply = message.get("reply_to_message") or {}
    message_key = f"{incoming_chat_id}:{reply.get('message_id') or ''}"
    metadata = state["message_topics"].get(message_key)
    if not metadata:
        send_message(
            token,
            chat_id,
            "Чтобы отметить тему, ответь «+» (опубликовано) или «-» (rejected) "
            "реплаем на сообщение бота с этой темой.",
        )
        return True

    if text == "+":
        if metadata.get("published"):
            send_message(token, chat_id, "✅ Эта тема уже отмечена опубликованной.")
            return True
        try:
            created = append_published_topic(metadata)
        except Exception as exc:
            send_message(token, chat_id, f"Не удалось обновить реестр: {str(exc)[:300]}")
            return False
        metadata["published"] = True
        metadata.pop("rejected", None)
        save_state(state)
        status = "добавил" if created else "обновил"
        send_message(
            token,
            chat_id,
            f"✅ Отметил опубликованной и {status} в реестр:\n{metadata['title']}",
        )
        return True

    if metadata.get("published"):
        send_message(token, chat_id, "Эта тема уже отмечена опубликованной.")
        return True
    if metadata.get("rejected"):
        send_message(token, chat_id, "✅ Эта тема уже отмечена как rejected.")
        return True
    try:
        created = append_rejected_topic(metadata)
    except Exception as exc:
        send_message(token, chat_id, f"Не удалось обновить реестр: {str(exc)[:300]}")
        return False
    metadata["rejected"] = True
    save_state(state)
    status = "добавил" if created else "обновил"
    send_message(
        token,
        chat_id,
        f"🚫 Отметил как rejected и {status} в реестр:\n{rejection_reply_title(metadata)}",
    )
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
