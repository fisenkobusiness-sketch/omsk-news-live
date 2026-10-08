# -*- coding: utf-8 -*-
"""Коллектор поисковой выдачи через Google News RSS."""
from __future__ import annotations

import hashlib
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

from normalization.source_post import make_source_post


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SearchQuery:
    query_id: str
    query: str
    label: str = ""


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = _HTML_TAG_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def _parse_pub_date(value: str | None) -> str | None:
    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _stable_id(link: str, guid: str, title: str) -> str:
    base = guid.strip() or link.strip() or title.strip()
    return hashlib.sha1(
        base.encode("utf-8", errors="ignore")
    ).hexdigest()


def build_google_news_search_url(
    *,
    query: str,
    when: str,
    language: str = "ru",
    country: str = "RU",
) -> str:
    """Строит поисковую RSS-ленту Google News."""
    effective_query = query.strip()

    if when.strip():
        effective_query = f"{effective_query} when:{when.strip()}"

    ceid = f"{country}:{language}"

    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(effective_query)}"
        f"&hl={quote_plus(language)}"
        f"&gl={quote_plus(country)}"
        f"&ceid={quote_plus(ceid)}"
    )


class GoogleNewsRSSCollector:
    """Получает поисковую выдачу и превращает её в SourcePost."""

    def __init__(
        self,
        *,
        language: str = "ru",
        country: str = "RU",
        default_when: str = "6h",
        timeout: float = 20.0,
        max_items: int = 100,
        request_delay: float = 0.25,
        session: requests.Session | None = None,
    ) -> None:
        self.language = language
        self.country = country
        self.default_when = default_when
        self.timeout = timeout
        self.max_items = max_items
        self.request_delay = request_delay
        self.session = session or requests.Session()
        self.errors: List[Dict[str, str]] = []

    def fetch_query(
        self,
        query: SearchQuery,
    ) -> List[Dict[str, Any]]:
        url = build_google_news_search_url(
            query=query.query,
            when=self.default_when,
            language=self.language,
            country=self.country,
        )

        response = self.session.get(
            url,
            timeout=self.timeout,
            headers={
                "User-Agent": (
                    "omsk-news-live/1.0 "
                    "(news discovery collector)"
                )
            },
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        channel = root.find("channel")

        if channel is None:
            return []

        items: List[Dict[str, Any]] = []

        for rank, item in enumerate(
            channel.findall("item")[: self.max_items],
            start=1,
        ):
            title = _clean_text(
                item.findtext("title")
            )
            link = (
                item.findtext("link")
                or ""
            ).strip()
            guid = _clean_text(
                item.findtext("guid")
            )
            description = _clean_text(
                item.findtext("description")
            )
            published_at = _parse_pub_date(
                item.findtext("pubDate")
            )

            source_node = item.find("source")
            source_name = _clean_text(
                source_node.text
                if source_node is not None
                else ""
            )
            source_url = (
                source_node.attrib.get("url")
                if source_node is not None
                else None
            )

            if not link and not title:
                continue

            post_id = _stable_id(
                link=link,
                guid=guid,
                title=title,
            )

            items.append(
                make_source_post(
                    platform="web_search",
                    kind="google_news",
                    source_id=query.query_id,
                    source_name=(
                        source_name
                        or "Google News"
                    ),
                    source_url=source_url,
                    post_id=post_id,
                    post_url=link or None,
                    published_at=published_at,
                    text=title,
                    collection_extra={
                        "collector_version": (
                            "google-news-rss/1.0"
                        ),
                        "query_id": query.query_id,
                    },
                    meta={
                        "query": query.query,
                        "label": query.label,
                        "rank": rank,
                        "guid": guid or None,
                        "description": description,
                        "publisher": source_name or None,
                        "publisher_url": source_url,
                        "query_id": query.query_id,
                    },
                )
            )

        return items

    def collect(
        self,
        queries: Iterable[SearchQuery],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for query in queries:
            try:
                results.extend(
                    self.fetch_query(query)
                )
            except (
                requests.RequestException,
                ET.ParseError,
                ValueError,
            ) as exc:
                self.errors.append({
                    "query_id": query.query_id,
                    "query": query.query,
                    "error": str(exc),
                })
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return self._deduplicate(results)

    @staticmethod
    def _deduplicate(
        items: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Убирает повтор одного материала из нескольких поисковых запросов."""
        seen: Dict[str, Dict[str, Any]] = {}

        for item in items:
            post = item.get("post") or {}
            meta = item.setdefault("meta", {})

            link = str(
                post.get("url") or ""
            ).strip()

            title = _WS_RE.sub(
                " ",
                str(post.get("text") or "")
                .lower(),
            ).strip()

            key = link or title

            if not key:
                continue

            existing = seen.get(key)

            if existing is None:
                meta.setdefault(
                    "matched_query_ids",
                    [meta.get("query_id")],
                )
                seen[key] = item
                continue

            existing_meta = existing.setdefault(
                "meta",
                {},
            )
            matched = existing_meta.setdefault(
                "matched_query_ids",
                [],
            )

            query_id = meta.get("query_id")
            if query_id and query_id not in matched:
                matched.append(query_id)

        return list(seen.values())
