# -*- coding: utf-8 -*-
"""Optional Telegram MTProto collector for the discovery layer.

The dependency is imported lazily on purpose. Telegram credentials and a
session must stay local and are never read from GitHub or committed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, Iterable, List

from normalization.source_post import make_source_post


@dataclass(frozen=True)
class TelegramChannel:
    username: str
    label: str = ""


class TelegramMTProtoCollector:
    """History collector using a user-authorized MTProto client.

    Telethon is optional until Telegram integration is explicitly enabled.
    This keeps the current pipeline dependency-free and backwards compatible.
    """

    def __init__(
        self,
        channels: Iterable[TelegramChannel],
        *,
        max_messages: int = 200,
    ) -> None:
        self.channels = list(channels)
        self.max_messages = max_messages

    @staticmethod
    def _required_env(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(
                f"Не задан Telegram credential: {name}. "
                "Секреты должны храниться локально."
            )
        return value

    @staticmethod
    def _post_url(username: str, message_id: int) -> str:
        return f"https://t.me/{username}/{message_id}"

    def collect(self) -> List[dict[str, Any]]:
        try:
            from telethon import TelegramClient
        except ImportError as exc:
            raise RuntimeError(
                "Для Telegram MTProto не установлен Telethon. "
                "Зависимость добавляем только после отдельного подтверждения."
            ) from exc

        api_id = int(self._required_env("TELEGRAM_API_ID"))
        api_hash = self._required_env("TELEGRAM_API_HASH")
        session = os.getenv(
            "TELEGRAM_SESSION",
            str(
                Path("secrets") / "telegram"
            ),
        ).strip()

        result: List[dict[str, Any]] = []

        # Client lifecycle is intentionally local. The first run may require
        # interactive authorization; no phone code or session is ever logged.
        with TelegramClient(session, api_id, api_hash) as client:
            for channel in self.channels:
                entity = client.get_entity(channel.username)

                for message in client.iter_messages(
                    entity,
                    limit=self.max_messages,
                ):
                    if message is None:
                        continue

                    text = (
                        getattr(message, "message", None)
                        or ""
                    )

                    published_at = None
                    if getattr(message, "date", None):
                        published_at = (
                            message.date.astimezone(timezone.utc)
                            .isoformat(timespec="seconds")
                            .replace("+00:00", "Z")
                        )

                    media_types = []
                    if getattr(message, "media", None) is not None:
                        media_types.append(
                            type(message.media).__name__
                        )

                    views = getattr(message, "views", None)
                    views = (
                        int(views)
                        if views is not None
                        else None
                    )

                    result.append(
                        make_source_post(
                            platform="telegram",
                            kind="channel_post",
                            source_id=str(
                                getattr(entity, "id", channel.username)
                            ),
                            source_name=(
                                channel.label
                                or getattr(
                                    entity,
                                    "title",
                                    channel.username,
                                )
                            ),
                            source_url=(
                                f"https://t.me/{channel.username}"
                            ),
                            post_id=str(message.id),
                            post_url=self._post_url(
                                channel.username,
                                int(message.id),
                            ),
                            published_at=published_at,
                            edited_at=(
                                message.edit_date.astimezone(
                                    timezone.utc
                                )
                                .isoformat(timespec="seconds")
                                .replace("+00:00", "Z")
                                if getattr(
                                    message,
                                    "edit_date",
                                    None,
                                )
                                else None
                            ),
                            text=text,
                            media_types=media_types,
                            views=views,
                            collection_extra={
                                "collector_version": (
                                    "telegram-mtproto/0.1"
                                ),
                            },
                            meta={
                                "channel_username": (
                                    channel.username
                                ),
                            },
                        )
                    )

        return result
