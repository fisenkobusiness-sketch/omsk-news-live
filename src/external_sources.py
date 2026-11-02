"""Read public Telegram channel history over MTProto and optional RSS feeds."""
from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
SECRETS = ROOT / ".secrets"
CONFIG_PATH = RUNTIME / "external_sources.json"
SESSION_PATH = SECRETS / "telegram_user"
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; OmskNewsLive/1.0; +public-news-monitor)"
OMSK_TZ = timezone(timedelta(hours=6), name="Asia/Omsk")

# Public channels used only as sources for topic discovery. Their counters are
# deliberately omitted from the data sent to the ranking and ML systems.
DEFAULT_TELEGRAM_CHANNELS = {
    'omskinform_news': 'Омск-информ',
    'kanal12omsk': '12 Канал | Новости Омска',
    'gorod55ru': 'Город55 | Новости Омска',
    'Om1_Omsk': 'Om1: Новости Омска и России',
    'omsk_smi': 'Новости Омска и Области',
    'incident_55ru': 'Инцидент Омск!',
    '-1001178109741': 'Омск Live',
    '-1001432513803': 'Инцидент Омск!',
    'omsk360': 'Омск 360°',
    'omsktop1': 'Омск с огоньком',
    'chp_55': 'ЧП Омск',
    'zhest_omsk_55': 'Жесть Омск',
    'region_omsk55': 'Омск | Регион-55',
    'omsks': 'Омск сегодня',
    'aomsk': 'Аварийный Омск',
    'ghest_omsk': 'Я в шоке. Омск',
    'moiiomsk': 'Мой Омск',
    'omskkoroche': 'Короче, Омск',
    'ngs55news': 'Новости Омска | NGS55',
    'newsomsk': 'Новости Омска',
    'vestiomsk': 'ВЕСТИ ОМСК',
    'omskpravda': 'Омская правда',
    'TramplinOmsk': 'Трамплин Медиа',
    'kdomsk': 'Камеры ДПС Омск',
    'dps155': 'ДПС Омск',
    'forumomskcom': 'Омский форум',
    'mec_55': 'Экономика | 55',
}


def _source_config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _secret(name: str, filename: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    path = SECRETS / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _telegram_settings():
    api_id = _secret("TELEGRAM_API_ID", "telegram_api_id.txt")
    api_hash = _secret("TELEGRAM_API_HASH", "telegram_api_hash.txt")
    if not api_id or not api_hash:
        raise RuntimeError(
            "Не настроены TELEGRAM_API_ID и TELEGRAM_API_HASH. "
            "Добавьте значения в .secrets/telegram_api_id.txt и "
            ".secrets/telegram_api_hash.txt, затем выполните tools/connect_telegram.py."
        )
    try:
        api_id = int(api_id)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_API_ID должен быть числом.") from exc

    proxy_url = _secret("TELEGRAM_PROXY", "telegram_proxy.txt")
    proxy = None
    if proxy_url:
        parsed = urlparse(proxy_url)
        if parsed.scheme not in ("socks5", "socks5h") or not parsed.hostname or not parsed.port:
            raise RuntimeError(
                "TELEGRAM_PROXY должен быть адресом SOCKS5, например "
                "socks5://логин:пароль@сервер:порт."
            )
        try:
            import socks
        except ImportError as exc:
            raise RuntimeError("Для SOCKS5 установите зависимость PySocks из requirements-telegram.txt.") from exc
        proxy = {
            "proxy_type": socks.SOCKS5,
            "addr": parsed.hostname,
            "port": parsed.port,
            "rdns": True,
            "username": parsed.username,
            "password": parsed.password,
        }
    return api_id, api_hash, proxy


def _new_telegram_client():
    try:
        from telethon.sync import TelegramClient
    except ImportError as exc:
        raise RuntimeError("Не установлена Telethon. Установите зависимости из requirements-telegram.txt.") from exc
    api_id, api_hash, proxy = _telegram_settings()
    SECRETS.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(SESSION_PATH), api_id, api_hash, proxy=proxy,
        timeout=15, request_retries=2, connection_retries=1,
        flood_sleep_threshold=30,
    )


def _media_type(message) -> str | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    if getattr(message, "photo", None):
        return "photo"
    document = getattr(message, "document", None)
    if document:
        mime = str(getattr(document, "mime_type", "") or "")
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "image"
        return "document"
    if getattr(message, "web_preview", None):
        return "link_preview"
    return "media"


def fetch_telegram_posts(
    channels: dict[str, str], limit: int = 100, log_callback=None,
) -> list[dict[str, Any]]:
    """Read recent full text posts from channels available to the logged-in user."""
    report = log_callback or (lambda message: print(message, flush=True))
    client = _new_telegram_client()
    posts = []
    try:
        client.connect()
        if not client.is_user_authorized():
            raise RuntimeError(
                "Telegram-сессия ещё не авторизована. Сначала выполните tools/connect_telegram.py."
            )
        for channel_ref, display_name in channels.items():
            channel_ref = str(channel_ref).strip().lstrip("@")
            is_channel_id = bool(re.fullmatch(r"(?:-100)?\d+", channel_ref))
            if not is_channel_id and not re.fullmatch(r"[A-Za-z0-9_]+", channel_ref):
                report(f"Telegram: invalid channel address {channel_ref!r}.")
                continue
            try:
                if is_channel_id:
                    from telethon.tl.types import PeerChannel
                    channel_id = int(channel_ref.removeprefix("-100"))
                    entity = client.get_entity(PeerChannel(channel_id))
                    source_key = str(channel_id)
                else:
                    channel_id = None
                    entity = client.get_entity(channel_ref)
                    source_key = channel_ref
                for message in client.iter_messages(entity, limit=limit, wait_time=1):
                    text = (getattr(message, "message", None) or "").strip()
                    # Media-only posts have no text for the current classifier.
                    # Keep captioned media and its type; downloading files/OCR is
                    # a separate optional enrichment stage.
                    if not text:
                        continue
                    timestamp = int(message.date.timestamp())
                    local_date = datetime.fromtimestamp(timestamp, OMSK_TZ)
                    posts.append({
                        "source": f"tg_{source_key}",
                        "id": int(message.id),
                        "source_name": str(display_name or getattr(entity, "title", None) or channel_ref),
                        "source_type": "telegram",
                        "timestamp": timestamp,
                        "date": local_date.strftime("%Y-%m-%d %H:%M:%S"),
                        "text": text,
                        "url": (
                            f"https://t.me/c/{channel_id}/{int(message.id)}"
                            if channel_id is not None
                            else f"https://t.me/{channel_ref}/{int(message.id)}"
                        ),
                        "media_type": _media_type(message),
                        # External audience counters are not model inputs.
                        "views": None, "likes": None, "comments": None, "reposts": None,
                    })
            except Exception as exc:
                report(f"Telegram {channel_ref}: {exc}")
    finally:
        if client.is_connected():
            client.disconnect()
    return posts


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def fetch_rss_feed(feed_url: str, source_name: str | None = None) -> list[dict[str, Any]]:
    """Read RSS/Atom headlines without importing third-party feed libraries."""
    response = requests.get(feed_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    entries = [element for element in root.iter() if _local_name(element.tag) in ("item", "entry")]
    result = []
    default_source = source_name or urlparse(feed_url).netloc
    for entry in entries:
        fields = {_local_name(child.tag): (child.text or "").strip() for child in entry}
        title = fields.get("title", "")
        summary = fields.get("description") or fields.get("summary") or fields.get("content", "")
        link = fields.get("link", "")
        for child in entry:
            if _local_name(child.tag) == "link":
                link = child.attrib.get("href", link)
                break
        date_value = fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("date")
        timestamp = _parse_feed_time(date_value)
        if not title or not link or not timestamp:
            continue
        text = re.sub(r"\s+", " ", f"{title}\n{summary}").strip()
        stable_id = int(hashlib.sha256(link.encode("utf-8")).hexdigest()[:15], 16)
        result.append({
            "source": f"rss_{urlparse(feed_url).netloc}", "id": stable_id,
            "source_name": default_source, "source_type": "regional_media",
            "timestamp": timestamp, "date": datetime.fromtimestamp(timestamp, OMSK_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "text": text, "url": link,
            "views": None, "likes": None, "comments": None, "reposts": None,
        })
    return result


def _parse_feed_time(value: str | None) -> int | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return int(parsedate_to_datetime(value).timestamp())
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_external_posts(log_callback=None) -> list[dict[str, Any]]:
    """Fetch Telegram channel history and optional RSS/Atom feeds."""
    report = log_callback or (lambda message: print(message, flush=True))
    config = _source_config()
    channels = dict(DEFAULT_TELEGRAM_CHANNELS)
    channels.update(config.get("telegram_channels", {}) if isinstance(config.get("telegram_channels"), dict) else {})
    feeds = config.get("rss_feeds", [])
    posts = []
    try:
        telegram_posts = fetch_telegram_posts(channels, log_callback=report)
        posts.extend(telegram_posts)
        report(f"Telegram MTProto: загружено публикаций {len(telegram_posts)}.")
    except Exception as exc:
        report(f"Telegram MTProto: {exc}")

    rss_jobs = [(str(feed.get("url")), str(feed.get("name") or ""),
                 lambda f=feed: fetch_rss_feed(str(f["url"]), str(f.get("name") or "") or None))
                for feed in feeds if isinstance(feed, dict) and feed.get("url")] if isinstance(feeds, list) else []
    if rss_jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(rss_jobs))) as pool:
            pending = {pool.submit(fetch): (url, name) for url, name, fetch in rss_jobs}
            for future in as_completed(pending):
                url, _ = pending[future]
                try:
                    posts.extend(future.result())
                except Exception as exc:
                    report(f"RSS {url}: {exc}")
    return posts
