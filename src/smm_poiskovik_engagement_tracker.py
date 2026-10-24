# -*- coding: utf-8 -*-
"""СММ Поисковик: контроль вовлечённости для двух целевых VK-аудиторий."""
from __future__ import annotations
import hashlib, json, os, sqlite3, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any
import requests

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SECRETS = ROOT / ".secrets"
RUNTIME = ROOT / "runtime"
DB_PATH = RUNTIME / "smm_poiskovik_engagement.sqlite3"
LOG_PATH = RUNTIME / "smm_poiskovik_engagement.log"
VK_VERSION = "5.199"
POLL_SECONDS = 60
CHECKPOINTS_HOURS = (1, 3)
TARGET_PER_AUDIENCE = 500
POSTS_PER_GROUP = 100
VK_TIMEOUT = 20
AUDIENCES = {
    "golos": {"name": "Голос Омска", "group_id": 133335843},
    "zhest": {"name": "Новости Омска | Жесть", "group_id": 76091195},
}

def now_ts() -> int:
    return int(time.time())

def log(message: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def read_secret(filename: str, env_name: str) -> str:
    value = os.getenv(env_name, "").strip()
    path = SECRETS / filename
    if not value and path.exists():
        value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(
            f"Не настроен секрет {env_name}. Создайте локальный файл .secrets/{filename}; "
            "не добавляйте его в Git."
        )
    return value

def vk_call(token: str, method: str, **params: Any) -> Any:
    params.update(access_token=token, v=VK_VERSION)
    response = requests.get(f"https://api.vk.com/method/{method}", params=params, timeout=VK_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"VK API {method}: {err.get('error_msg', err)}")
    return data["response"]

def fetch_wall(token: str, group_id: int) -> list[dict[str, Any]]:
    result = vk_call(token, "wall.get", owner_id=-abs(group_id), count=POSTS_PER_GROUP, filter="owner")
    return result.get("items", [])

def normalize_post(audience_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    group_id = int(AUDIENCES[audience_key]["group_id"])
    post_id = int(raw["id"])
    timestamp = int(raw.get("date") or 0)
    return {
        "source": audience_key, "id": post_id,
        "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": timestamp, "text": raw.get("text") or "",
        "likes": int((raw.get("likes") or {}).get("count", 0) or 0),
        "comments": int((raw.get("comments") or {}).get("count", 0) or 0),
        "reposts": int((raw.get("reposts") or {}).get("count", 0) or 0),
        "views": int((raw.get("views") or {}).get("count", 0) or 0),
        "url": f"https://vk.ru/wall-{group_id}_{post_id}",
        "source_type": "social", "confirmed": False, "flags": [],
        "editor_status": "Наблюдение", "publication_mode": "verification_required",
        "verification_required": True, "publish_disclaimer_required": True,
    }

def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS seen_posts (
            audience TEXT NOT NULL, post_id INTEGER NOT NULL, first_seen_at INTEGER NOT NULL,
            PRIMARY KEY (audience, post_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS observations (
            observation_id TEXT PRIMARY KEY, audience TEXT NOT NULL, audience_name TEXT NOT NULL,
            member_posts_json TEXT NOT NULL, member_ids_json TEXT NOT NULL,
            predicted_at INTEGER NOT NULL, score REAL NOT NULL, prediction TEXT NOT NULL,
            initial_views INTEGER NOT NULL DEFAULT 0, initial_likes INTEGER NOT NULL DEFAULT 0,
            initial_comments INTEGER NOT NULL DEFAULT 0, initial_reposts INTEGER NOT NULL DEFAULT 0,
            score_at_1h REAL, score_at_3h REAL,
            views_at_1h INTEGER, likes_at_1h INTEGER, comments_at_1h INTEGER, reposts_at_1h INTEGER,
            views_at_3h INTEGER, likes_at_3h INTEGER, comments_at_3h INTEGER, reposts_at_3h INTEGER,
            measured_at_1h INTEGER, measured_at_3h INTEGER,
            completed_1h INTEGER NOT NULL DEFAULT 0, completed_3h INTEGER NOT NULL DEFAULT 0,
            notified_1h INTEGER NOT NULL DEFAULT 0, notified_3h INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.commit()

def db_connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    return db

def unseen_posts(db_path: Path, audience: str, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First poll bootstraps existing posts; only later posts enter the experiment."""
    with db_connect(db_path) as db:
        bootstrapped = db.execute("SELECT value FROM state WHERE key=?", (f"bootstrapped:{audience}",)).fetchone()
        if not bootstrapped:
            stamp = now_ts()
            db.executemany("INSERT OR IGNORE INTO seen_posts(audience,post_id,first_seen_at) VALUES(?,?,?)",
                           [(audience, int(p["id"]), stamp) for p in posts])
            db.execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (f"bootstrapped:{audience}", str(stamp)))
            db.commit()
            log(f"{AUDIENCES[audience]['name']}: первичная загрузка {len(posts)} постов; старые посты не оцениваются.")
            return []
        fresh = []
        stamp = now_ts()
        for post in posts:
            cursor = db.execute("INSERT OR IGNORE INTO seen_posts(audience,post_id,first_seen_at) VALUES(?,?,?)",
                                (audience, int(post["id"]), stamp))
            if cursor.rowcount == 1:
                fresh.append(post)
        db.commit()
    return fresh

def isolated_prediction(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run existing analysis/predictor in a temporary runtime, isolated from live monitor."""
    import tempfile
    if not posts:
        return []
    with tempfile.TemporaryDirectory(prefix="smm_poiskovik_eval_") as tmp:
        work = Path(tmp)
        runtime = work / "runtime"
        runtime.mkdir()
        (runtime / "vk_today.json").write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        for script in (SRC / "analysis.py", SRC / "predictor.py"):
            result = subprocess.run([sys.executable, str(script)], cwd=work, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=120)
            if result.returncode:
                raise RuntimeError(f"{script.name} завершился с кодом {result.returncode}: {(result.stderr or result.stdout)[-1200:]}")
        data = json.loads((runtime / "predictor_queue.json").read_text(encoding="utf-8"))
        return data.get("topics", [])

def store_observations(db_path: Path, audience: str, topics: list[dict[str, Any]]) -> int:
    stored = 0
    with db_connect(db_path) as db:
        for topic in topics:
            prediction = topic.get("prediction") or {}
            members = topic.get("members") or []
            member_ids = sorted({int(m.get("id")) for m in members
                                 if isinstance(m, dict) and str(m.get("id", "")).isdigit()})
            if not member_ids:
                continue
            ids_json = json.dumps(member_ids, separators=(",", ":"))
            observation_id = hashlib.sha256(f"{audience}|{ids_json}".encode("utf-8")).hexdigest()
            cursor = db.execute("""INSERT OR IGNORE INTO observations (
                observation_id,audience,audience_name,member_posts_json,member_ids_json,predicted_at,score,prediction,
                initial_views,initial_likes,initial_comments,initial_reposts,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (observation_id, audience, AUDIENCES[audience]["name"],
                 json.dumps(members, ensure_ascii=False), ids_json, now_ts(),
                 float(prediction.get("priority_score", 0) or 0),
                 str(prediction.get("prediction", "unknown")),
                 int(topic.get("views", 0) or 0), int(topic.get("likes", 0) or 0),
                 int(topic.get("comments", 0) or 0), int(topic.get("reposts", 0) or 0), now_ts()))
            stored += max(0, cursor.rowcount)
        db.commit()
    return stored

def fetch_post_counters(token: str, audience: str, post_ids: list[int]) -> dict[int, dict[str, int]]:
    group_id = int(AUDIENCES[audience]["group_id"])
    result: dict[int, dict[str, int]] = {}
    for offset in range(0, len(post_ids), 100):
        chunk = post_ids[offset:offset + 100]
        posts_param = ",".join(f"-{group_id}_{pid}" for pid in chunk)
        items = vk_call(token, "wall.getById", posts=posts_param)
        for item in items:
            pid = int(item.get("id", 0) or 0)
            result[pid] = {
                "views": int((item.get("views") or {}).get("count", 0) or 0),
                "likes": int((item.get("likes") or {}).get("count", 0) or 0),
                "comments": int((item.get("comments") or {}).get("count", 0) or 0),
                "reposts": int((item.get("reposts") or {}).get("count", 0) or 0),
            }
    return result

def telegram_send(message: str, token: str, chat_id: str) -> None:
    response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message, "disable_web_page_preview": True}, timeout=VK_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API: {data}")

def completed_counts(db_path: Path = DB_PATH) -> dict[str, int]:
    with db_connect(db_path) as db:
        rows = db.execute("SELECT audience,COUNT(*) AS n FROM observations WHERE completed_1h=1 AND completed_3h=1 GROUP BY audience").fetchall()
    counts = {key: 0 for key in AUDIENCES}
    counts.update({row["audience"]: int(row["n"]) for row in rows})
    return counts

def maybe_notify_threshold(db_path: Path, send_func=telegram_send, token: str | None = None,
                           chat_id: str | None = None, threshold: int = TARGET_PER_AUDIENCE) -> bool:
    counts = completed_counts(db_path)
    if not all(counts.get(key, 0) >= threshold for key in AUDIENCES):
        return False
    with db_connect(db_path) as db:
        if db.execute("SELECT value FROM state WHERE key='threshold_notified'").fetchone():
            return False
        message = ("✅ СММ Поисковик: контрольная выборка готова\n\n" +
                   "\n".join(f"{AUDIENCES[key]['name']}: {counts.get(key, 0)}/{threshold} наблюдений "
                             "(есть замеры через 1 и 3 часа)" for key in AUDIENCES) +
                   "\nМожно переходить к оценке качества прогнозов.")
        if not token or not chat_id:
            raise RuntimeError("Для уведомления не заданы Telegram bot token и chat_id.")
        send_func(message, token, chat_id)
        db.execute("INSERT INTO state(key,value) VALUES('threshold_notified',?)", (str(now_ts()),))
        db.commit()
    return True

def process_due_observations(token: str, db_path: Path = DB_PATH, now: int | None = None) -> None:
    now = now if now is not None else now_ts()
    # A checkpoint is accepted only within a 10-minute window. If the process
    # was stopped for longer, leave it incomplete rather than label a late value as 1h/3h.
    tolerance_seconds = 10 * 60
    with db_connect(db_path) as db:
        rows = db.execute("SELECT * FROM observations WHERE completed_1h=0 OR completed_3h=0 ORDER BY predicted_at").fetchall()
    for row in rows:
        age = now - int(row["predicted_at"])
        due_hours = []
        for hours in CHECKPOINTS_HOURS:
            if row[f"completed_{hours}h"]:
                continue
            delta = age - hours * 3600
            if 0 <= delta <= tolerance_seconds:
                due_hours.append(hours)
            elif delta > tolerance_seconds:
                log(f"Пропущена точная точка {hours}h для {row['audience_name']} {row['member_ids_json']}: "
                    f"возраст {age / 3600:.2f} ч. Поздний замер не засчитывается.")
        if not due_hours:
            continue
        audience = row["audience"]
        counters = fetch_post_counters(token, audience, json.loads(row["member_ids_json"]))
        if not counters:
            log(f"Не удалось получить свежие счётчики: {row['audience_name']} {row['member_ids_json']}")
            continue
        views = sum(v["views"] for v in counters.values())
        likes = sum(v["likes"] for v in counters.values())
        comments = sum(v["comments"] for v in counters.values())
        reposts = sum(v["reposts"] for v in counters.values())
        weighted_engagement_rate = (likes + 2 * comments + 4 * reposts) / max(views, 1)
        with db_connect(db_path) as db:
            for hours in due_hours:
                db.execute(
                    f"""UPDATE observations SET score_at_{hours}h=?,
                        views_at_{hours}h=?, likes_at_{hours}h=?, comments_at_{hours}h=?,
                        reposts_at_{hours}h=?, measured_at_{hours}h=?, completed_{hours}h=1
                        WHERE observation_id=?""",
                    (weighted_engagement_rate, views, likes, comments, reposts, now, row["observation_id"]),
                )
            db.commit()
        log(f"Контроль {row['audience_name']}: +{age / 3600:.2f} ч, "
            f"просмотры={views}, лайки={likes}, комментарии={comments}, репосты={reposts}, "
            f"вовлечённость/просмотры={weighted_engagement_rate:.5f}")

def main() -> None:
    init_db()
    vk_token = read_secret("vk_service_key.txt", "VK_SERVICE_KEY")
    tg_token = read_secret("telegram_bot_token.txt", "TELEGRAM_BOT_TOKEN")
    tg_chat_id = read_secret("telegram_chat_id.txt", "TELEGRAM_CHAT_ID")
    log(f"Трекер запущен. Порог: {TARGET_PER_AUDIENCE} завершённых наблюдений на каждую аудиторию.")
    while True:
        try:
            for key, audience in AUDIENCES.items():
                raw_posts = fetch_wall(vk_token, int(audience["group_id"]))
                posts = [normalize_post(key, p) for p in raw_posts]
                fresh = unseen_posts(DB_PATH, key, posts)
                if fresh:
                    topics = isolated_prediction(fresh)
                    added = store_observations(DB_PATH, key, topics)
                    log(f"{audience['name']}: новых постов {len(fresh)}, сохранено прогнозов {added}.")
            process_due_observations(vk_token)
            if maybe_notify_threshold(DB_PATH, token=tg_token, chat_id=tg_chat_id):
                log("Telegram: отправлено уведомление о готовности контрольной выборки.")
        except Exception as exc:
            log(f"ОШИБКА цикла трекера: {exc}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
