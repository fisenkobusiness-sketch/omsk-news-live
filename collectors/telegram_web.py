# -*- coding: utf-8 -*-
"""Public Telegram channel previews; no MTProto credentials required.

This collector reads public t.me/s/<username> pages only. It intentionally
writes to a separate human-review stream, not the model/scoring input.
Invite-only channels require a separate authenticated integration.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List

import requests

from normalization.source_post import make_source_post


_OMSK_OFFSET = timedelta(hours=6)
_WS_RE = re.compile(r"\s+")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img",
              "input", "link", "meta", "param", "source", "track", "wbr"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _parse_views(value: str) -> int | None:
    value = (value or "").strip().lower()
    if not value:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([kmкм]?)", value)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    suffix = match.group(2)
    if suffix in {"k", "к"}:
        number *= 1_000
    elif suffix in {"m", "м"}:
        number *= 1_000_000
    return int(number)


class _PublicChannelParser(HTMLParser):
    """Extract individual public channel post cards from Telegram's web view."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: List[Dict[str, Any]] = []
        self.current: Dict[str, Any] | None = None
        self.capture_kind: str | None = None
        self.capture_depth = 0
        self.capture_parts: List[str] = []

    @staticmethod
    def _classes(attrs: Dict[str, str | None]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def _finish_capture(self) -> None:
        if self.current is None or self.capture_kind is None:
            return
        value = _WS_RE.sub(" ", "".join(self.capture_parts)).strip()
        if self.capture_kind == "text":
            self.current["text"] = value
        elif self.capture_kind == "views":
            self.current["views"] = _parse_views(value)
        self.capture_kind = None
        self.capture_depth = 0
        self.capture_parts = []

    def _finish_post(self) -> None:
        if self.current is not None:
            self.posts.append(self.current)
        self.current = None

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        classes = self._classes(attrs)

        if self.capture_kind is not None:
            if tag == "br" and self.capture_kind == "text":
                self.capture_parts.append(" ")
            if tag not in _VOID_TAGS:
                self.capture_depth += 1
            return

        if tag == "div" and "tgme_widget_message" in classes and attrs.get("data-post"):
            self._finish_post()
            data_post = str(attrs["data-post"])
            self.current = {
                "data_post": data_post,
                "text": "",
                "published_at": None,
                "post_url": None,
                "views": None,
                "media_types": [],
                "media_urls": [],
            }
            return

        if self.current is None:
            return

        if tag == "time" and attrs.get("datetime"):
            self.current["published_at"] = attrs["datetime"]

        href = attrs.get("href")
        if href and "tgme_widget_message_date" in classes:
            self.current["post_url"] = href

        photo_classes = {
            name for name in classes
            if "tgme_widget_message_photo" in name
        }
        video_classes = {
            name for name in classes
            if "tgme_widget_message_video" in name
        }
        document_classes = {
            name for name in classes
            if "tgme_widget_message_document" in name
        }
        if photo_classes:
            self.current["media_types"].append("photo")
        if video_classes:
            self.current["media_types"].append("video")
        if document_classes:
            self.current["media_types"].append("document")
        if any("tgme_widget_message_sticker" in name for name in classes):
            self.current["media_types"].append("sticker")
        if any("tgme_widget_message_poll" in name for name in classes):
            self.current["media_types"].append("poll")

        # Public Telegram pages often expose media as a CSS background URL
        # rather than a normal <img src>. Capture only URLs attached to media
        # elements to avoid accidentally storing channel avatars.
        is_media_element = bool(photo_classes or video_classes or document_classes)
        media_urls = self.current.setdefault("media_urls", [])
        style = attrs.get("style") or ""
        if is_media_element:
            media_urls.extend(re.findall(
                r"url\(\s*['\"]?(https?://[^)'\"]+)",
                style,
                flags=re.IGNORECASE,
            ))
            for attr_name in ("src", "data-src", "poster"):
                candidate = attrs.get(attr_name)
                if candidate and candidate.startswith(("http://", "https://")):
                    media_urls.append(candidate)
            srcset = attrs.get("srcset") or ""
            if srcset:
                for candidate in srcset.split(","):
                    candidate_url = candidate.strip().split(" ", 1)[0]
                    if candidate_url.startswith(("http://", "https://")):
                        media_urls.append(candidate_url)

        if tag == "div" and "tgme_widget_message_text" in classes:
            self.capture_kind = "text"
            self.capture_depth = 1
            self.capture_parts = []
        elif "tgme_widget_message_views" in classes:
            self.capture_kind = "views"
            self.capture_depth = 1
            self.capture_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self.capture_kind is not None:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self._finish_capture()

    def handle_startendtag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        if self.capture_kind is not None:
            if tag == "br" and self.capture_kind == "text":
                self.capture_parts.append(" ")
            return
        self.handle_starttag(tag, attrs_list)

    def handle_data(self, data: str) -> None:
        if self.capture_kind is not None:
            self.capture_parts.append(data)

    def result(self) -> List[Dict[str, Any]]:
        self.close()
        self._finish_capture()
        self._finish_post()
        return self.posts


class TelegramPublicWebCollector:
    """Read only today's posts (Omsk local date) from public t.me/s pages."""

    def __init__(
        self,
        channels: Iterable[Dict[str, str]],
        *,
        timeout: float = 15.0,
        request_delay: float = 0.25,
        session: requests.Session | None = None,
    ) -> None:
        self.channels = list(channels)
        self.timeout = timeout
        self.request_delay = request_delay
        self.session = session or requests.Session()
        self.errors: List[Dict[str, str]] = []
        self.source_counts: Dict[str, int] = {}

    @staticmethod
    def _today_omsk():
        return (datetime.now(timezone.utc) + _OMSK_OFFSET).date()

    def _fetch_channel(self, channel: Dict[str, str]) -> List[Dict[str, Any]]:
        username = (channel.get("username") or "").strip().lstrip("@")
        label = (channel.get("label") or username).strip()
        if not username:
            return []

        response = self.session.get(
            f"https://t.me/s/{username}",
            timeout=self.timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        parser = _PublicChannelParser()
        parser.feed(response.text)
        raw_posts = parser.result()
        today = self._today_omsk()
        results: List[Dict[str, Any]] = []

        for raw in raw_posts:
            published = _parse_dt(raw.get("published_at"))
            if published is None:
                continue
            local_date = (published + _OMSK_OFFSET).date()
            if local_date != today:
                continue

            data_post = str(raw.get("data_post") or "")
            pieces = data_post.split("/", 1)
            post_username = pieces[0] if len(pieces) == 2 else username
            post_id = pieces[1] if len(pieces) == 2 else ""
            post_url = raw.get("post_url") or (
                f"https://t.me/{post_username}/{post_id}"
                if post_id else f"https://t.me/s/{username}"
            )
            media_types = sorted(set(raw.get("media_types") or []))
            post_text = raw.get("text") or ""
            if not post_text and not media_types:
                continue

            results.append(make_source_post(
                platform="telegram",
                kind="public_channel_post",
                source_id=username,
                source_name=label,
                source_url=f"https://t.me/{username}",
                post_id=post_id or data_post or post_url,
                post_url=post_url,
                published_at=published.isoformat(timespec="seconds").replace("+00:00", "Z"),
                text=post_text,
                media_types=media_types,
                views=raw.get("views"),
                collection_extra={
                    "collector_version": "telegram-public-web/0.2",
                    "review_only": True,
                    "prediction_eligible": False,
                    "publication_timezone": "Asia/Omsk",
                },
                meta={
                    "channel_username": username,
                    "ingest_method": "public_web_preview",
                    "today_filter": "Asia/Omsk",
                    "media_urls": sorted(set(raw.get("media_urls") or [])),
                    "has_text": bool(post_text.strip()),
                    "media_only": not bool(post_text.strip()) and bool(media_types),
                },
            ))

        return results

    def collect(self) -> List[Dict[str, Any]]:
        all_posts: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for channel in self.channels:
            username = (channel.get("username") or "").strip().lstrip("@")
            label = (channel.get("label") or username).strip()
            try:
                posts = self._fetch_channel(channel)
                source_label = f"{label} (@{username})" if label else f"@{username}"
                self.source_counts[source_label] = len(posts)
                for post in posts:
                    url = str((post.get("post") or {}).get("url") or "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    all_posts.append(post)
            except (requests.Timeout, requests.ConnectionError) as exc:
                source_label = f"{label} (@{username})" if label else f"@{username}"
                self.source_counts[source_label] = 0
                self.errors.append({
                    "username": username,
                    "label": label,
                    "error": str(exc),
                })
                # A connection failure usually affects every Telegram web
                # preview on this network; stop instead of timing out 24 times.
                break
            except (requests.RequestException, ValueError) as exc:
                self.source_counts[label or username] = 0
                self.errors.append({
                    "username": username,
                    "label": label,
                    "error": str(exc),
                })
            if self.request_delay > 0:
                time.sleep(self.request_delay)
        return all_posts
