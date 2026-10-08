# -*- coding: utf-8 -*-
"""
LIVE VK MONITOR
VK -> Analysis -> Predictor -> GitHub

GitHub token берётся только из локального файла github_token.txt.
VK service key берётся из vk_service_key.txt.
Ни один из ключей не отправляется в GitHub.
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Force UTF-8 for Windows/PyCharm console output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
SECRETS_DIR = PROJECT_ROOT / ".secrets"

TOKEN_FILE = SECRETS_DIR / "vk_service_key.txt"
GITHUB_TOKEN_FILE = SECRETS_DIR / "github_token.txt"

INPUT_FILE = RUNTIME_DIR / "vk_today.json"
SEEN_FILE = RUNTIME_DIR / "live_seen.json"
LOG_FILE = RUNTIME_DIR / "live_monitor.log"

ANALYZER = SRC_DIR / "analysis.py"
PREDICTOR = SRC_DIR / "predictor.py"

POLL_SECONDS = 30
POSTS_PER_GROUP = 100
MAX_VK_WORKERS = 8

GITHUB_REPO = "fisenkobusiness-sketch/omsk-news-live"
GITHUB_BRANCH = "main"
GITHUB_PATH = "editorial_pool.json"

GROUPS = [
    "inci55",
    "omsk_live",
    "1oomestomska",
    "omsk24online",
    "chp55",
    "aomsk",
    "omsk_vk",
    "region_omsk55",
    "spletniki55",
    "tipical_omsk",
    "ghest_omsk",
    "news_gorod55",
    "dushalady",
    "omsk_group",
    "omsk_glavniy",
    "12kanalomsk",
    "omsk_reg",
    "club233315760",
    "omsk_online",
    "ouromsk",
    "live_omck",
    "auto_omsk",
    "fcava"
]


def _console_safe(text):
    """Return text that can always be displayed by a Windows/PyCharm console.

    The full Unicode message is still written to the UTF-8 log file.
    If the active console cannot encode a character, fall back to a readable
    ASCII representation instead of terminating the monitor.
    """
    text = str(text)
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode("ascii", "backslashreplace").decode("ascii")


def log(message):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(_console_safe(line), flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_secret(path, name):
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise RuntimeError(f"Не найден {name}: {path.name}")


def get_vk_token():
    env = os.getenv("VK_SERVICE_KEY", "").strip()
    return env or read_secret(TOKEN_FILE, "VK service key")


def get_github_token():
    env = os.getenv("GITHUB_TOKEN", "").strip()
    return env or read_secret(GITHUB_TOKEN_FILE, "GitHub token")


def vk_call(method, token, **params):
    params["access_token"] = token
    params["v"] = "5.199"
    url = f"https://api.vk.com/method/{method}"
    r = requests.get(url, params=params, timeout=5)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(
            f"VK API {method}: {data['error'].get('error_msg', data['error'])}"
        )
    return data["response"]


def resolve_groups(token):
    response = vk_call(
        "groups.getById",
        token,
        group_ids=",".join(GROUPS),
        fields="name,screen_name",
    )
    result = {}
    for item in response.get("groups", []):
        screen = item.get("screen_name")
        gid = item.get("id")
        if screen and gid:
            result[screen] = {"id": int(gid), "name": item.get("name", screen)}
    missing = [g for g in GROUPS if g not in result]
    if missing:
        log("Не удалось определить группы: " + ", ".join(missing))
    return result


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def today_start():
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def normalize_post(group_key, item):
    post_id = int(item["id"])
    owner_id = int(item["owner_id"])
    date_ts = int(item.get("date", 0) or 0)
    likes = int((item.get("likes") or {}).get("count", 0) or 0)
    comments = int((item.get("comments") or {}).get("count", 0) or 0)
    reposts = int((item.get("reposts") or {}).get("count", 0) or 0)
    views = int((item.get("views") or {}).get("count", 0) or 0)

    return {
        "source": group_key,
        "id": post_id,
        "date": datetime.fromtimestamp(date_ts).strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": date_ts,
        "text": item.get("text", "") or "",
        "likes": likes,
        "comments": comments,
        "reposts": reposts,
        "views": views,
        "url": f"https://vk.ru/wall{owner_id}_{post_id}",
        "source_type": "social",
        "confirmed": False,
        "flags": [],
        "editor_status": "🔵 НАБЛЮДАТЬ",
        "publication_mode": "verification_required",
        "verification_required": True,
        "publish_disclaimer_required": True,
    }


def fetch_group_today(token, group_key, group_id):
    start = int(today_start().timestamp())
    response = vk_call(
        "wall.get",
        token,
        owner_id=-abs(group_id),
        count=POSTS_PER_GROUP,
        filter="owner",
    )
    return [
        normalize_post(group_key, item)
        for item in response.get("items", [])
        if int(item.get("date", 0) or 0) >= start
    ]


def run_pipeline():
    if not ANALYZER.exists():
        raise RuntimeError(f"Не найден {ANALYZER.name}")
    if not PREDICTOR.exists():
        raise RuntimeError(f"Не найден {PREDICTOR.name}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    for script in (ANALYZER, PREDICTOR):
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=PROJECT_ROOT,
            check=False,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.stdout:
            for line in result.stdout.splitlines():
                log(f"{script.name}: {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                log(f"{script.name} ERROR: {line}")
        if result.returncode != 0:
            raise RuntimeError(f"{script.name} завершился с кодом {result.returncode}")


def github_request(method, path, token, payload=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "omsk-news-live",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {e.code}: {body[:500]}")


def publish_to_github():
    token = get_github_token()

    if not INPUT_FILE.exists():
        raise RuntimeError("vk_today.json ещё не создан")

    POOL_FILE = RUNTIME_DIR / "predictor_queue.json"
    if not POOL_FILE.exists():
        raise RuntimeError("predictor_queue.json не создан Predictor")

    payload = load_json(POOL_FILE, {})
    if not isinstance(payload, dict):
        raise RuntimeError("predictor_queue.json имеет неверный формат")

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Публикуем только основной редакционный пул.
    # final_queue.json больше не участвует в текущем pipeline:
    # поиск по репозиторию не нашёл его потребителей. Старый файл можно
    # оставить в GitHub для обратной совместимости, но не тратить ~5 сек
    # на его обновление на каждом цикле.
    for github_path in ("editorial_pool.json",):
        sha = None
        try:
            _, existing = github_request(
                "GET",
                f"/contents/{github_path}?ref={GITHUB_BRANCH}",
                token,
            )
            sha = existing.get("sha")
        except RuntimeError as e:
            if "GitHub API 404" not in str(e):
                raise

        body = {
            "message": "Update live editorial pool",
            "content": encoded,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            body["sha"] = sha

        status, _ = github_request(
            "PUT",
            f"/contents/{github_path}",
            token,
            body,
        )
        log(f"GitHub: {github_path} обновлён (HTTP {status}).")


def main():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    token = get_vk_token()
    groups = resolve_groups(token)

    seen_raw = load_json(SEEN_FILE, [])
    seen = set(seen_raw if isinstance(seen_raw, list) else [])
    today_start_ts = int(today_start().timestamp())

    # Новый календарный день = новая рабочая лента.
    # Старые посты не должны переходить в сегодняшний массив.
    loaded_posts = load_json(INPUT_FILE, [])
    if not isinstance(loaded_posts, list):
        loaded_posts = []
    today_posts = [
        p for p in loaded_posts
        if isinstance(p, dict) and int(p.get("timestamp", 0) or 0) >= today_start_ts
    ]

    unique = {}
    for p in today_posts:
        unique[f"{p.get('source')}:{p.get('id')}"] = p
    today_posts = list(unique.values())

    # Оставляем seen только для постов текущего дня.
    seen = {
        key for key in seen
        if ":" in key and any(key == f"{p.get('source')}:{p.get('id')}" for p in today_posts)
    }

    log(
        f"LIVE VK монитор запущен. Групп: {len(groups)}. "
        f"Опрос каждые {POLL_SECONDS} сек."
    )

    first_cycle = True
    cycle_no = 0

    while True:
        try:
            cycle_no += 1
            log(f"Цикл #{cycle_no}: опрашиваю VK...")
            new_posts = []
            seen_before = seen.copy()

            # VK network calls are independent, so fetch groups concurrently.
            # Result order is restored by group index to keep the output stable.
            group_items = list(groups.items())
            fetched = [None] * len(group_items)
            with ThreadPoolExecutor(max_workers=min(MAX_VK_WORKERS, max(1, len(group_items)))) as pool:
                futures = {
                    pool.submit(fetch_group_today, token, group_key, info["id"]): idx
                    for idx, (group_key, info) in enumerate(group_items)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    group_key, _ = group_items[idx]
                    try:
                        fetched[idx] = future.result()
                    except Exception as exc:
                        log(f"VK {group_key}: ошибка получения: {exc}")
                        fetched[idx] = []

            for posts in fetched:
                for post in posts or []:
                    key = f"{post['source']}:{post['id']}"
                    if key not in seen:
                        new_posts.append(post)
                        seen.add(key)

            if new_posts:
                today_posts.extend(new_posts)

                unique = {}
                for p in today_posts:
                    unique[f"{p.get('source')}:{p.get('id')}"] = p

                today_posts = sorted(
                    unique.values(),
                    key=lambda x: x.get("timestamp", 0),
                    reverse=True,
                )

                save_json(INPUT_FILE, today_posts)
                save_json(SEEN_FILE, sorted(seen))

                log(f"Новых постов: {len(new_posts)}")
                run_pipeline()
                publish_to_github()
                log("Analysis + Predictor + GitHub завершены.")

            elif first_cycle:
                save_json(INPUT_FILE, today_posts)
                save_json(SEEN_FILE, sorted(seen))
                log("Новых постов при первом цикле нет.")

            first_cycle = False
            log(f"Цикл #{cycle_no}: завершён. Следующий опрос через {POLL_SECONDS} сек.")
            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log("Монитор остановлен пользователем.")
            break
        except Exception as exc:
            log(f"ОШИБКА: {exc}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
