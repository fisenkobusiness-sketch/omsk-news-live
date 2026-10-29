# -*- coding: utf-8 -*-
"""Read-only connection check for the engagement tracker; never starts live_monitor."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets"
VK_VERSION = "5.199"
TIMEOUT = 20
AUDIENCES = {
    "Голос Омска": 133335843,
    "Новости Омска | Жесть": 76091195,
}


def secret(filename: str, env_name: str) -> str:
    value = os.getenv(env_name, "").strip()
    path = SECRETS / filename
    if not value and path.exists():
        value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Не найден секрет {env_name} (файл .secrets/{filename})")
    return value


def vk_call(token: str, method: str, **params):
    params.update(access_token=token, v=VK_VERSION)
    response = requests.get(
        f"https://api.vk.com/method/{method}",
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"VK {method}: ожидался JSON-объект, получен {type(payload).__name__}"
        )

    if "error" in payload:
        error = payload["error"]
        if isinstance(error, dict):
            message = error.get("error_msg", str(error))
            code = error.get("error_code", "не указан")
        else:
            message = str(error)
            code = "не указан"
        raise RuntimeError(f"VK {method}: ошибка API {code}: {message}")

    if "response" not in payload:
        raise RuntimeError(
            f"VK {method}: в ответе отсутствует поле response; "
            f"поля ответа: {', '.join(payload.keys())}"
        )
    return payload["response"]


def main() -> int:
    print("Проверка подключений в режиме чтения. Основной монитор НЕ запускается.\n")
    try:
        vk_token = secret("vk_service_key.txt", "VK_SERVICE_KEY")
        tg_token = secret("telegram_bot_token.txt", "TELEGRAM_BOT_TOKEN")
        secret("telegram_chat_id.txt", "TELEGRAM_CHAT_ID")
    except Exception as exc:
        print(f"[ОШИБКА] Секреты: {exc}")
        return 1

    failures = 0
    for name, group_id in AUDIENCES.items():
        try:
            wall_data = vk_call(vk_token, "wall.get", owner_id=-group_id, count=1, filter="owner")
            if not isinstance(wall_data, dict):
                raise RuntimeError(f"wall.get вернул {type(wall_data).__name__} вместо объекта; проверьте ответ VK API и права токена")
            posts = wall_data.get("items", [])
            if not isinstance(posts, list):
                raise RuntimeError(f"wall.get: поле items имеет тип {type(posts).__name__}, ожидался список")
            if not posts:
                raise RuntimeError("VK вернул пустой список постов")
            post_id = int(posts[0]["id"])
            counters = vk_call(vk_token, "wall.getById", posts=f"-{group_id}_{post_id}")
            if isinstance(counters, dict):
                counters = counters.get("items")
            if not isinstance(counters, list):
                raise RuntimeError(f"wall.getById: ожидался список постов или объект с items, получен {type(counters).__name__}")
            matching = [item for item in counters if isinstance(item, dict) and int(item.get("id", 0) or 0) == post_id]
            if not matching:
                raise RuntimeError("wall.getById не вернул ожидаемый пост")
            item = matching[0]
            views = int((item.get("views") or {}).get("count", 0) or 0)
            print(f"[OK] VK {name}: wall.get и wall.getById работают; просмотры={views}.")
        except Exception as exc:
            failures += 1
            print(f"[ОШИБКА] VK {name}: {exc}")

    try:
        response = requests.get(f"https://api.telegram.org/bot{tg_token}/getMe", timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(str(data.get("description", "неизвестная ошибка Telegram API")))
        bot = data.get("result", {})
        print(f"[OK] Telegram: токен принят; бот @{bot.get('username', '(без username)')}.")
        print("[INFO] Тестовое сообщение не отправлялось; chat_id только проверен на наличие.")
    except Exception as exc:
        failures += 1
        print(f"[ОШИБКА] Telegram: {exc}")

    if failures:
        print(f"\nИТОГ: ошибок — {failures}. Пока не запускайте сбор выборки.")
        return 1
    print("\nИТОГ: подключения прошли проверку. Это не запускает трекер и не меняет данные.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
