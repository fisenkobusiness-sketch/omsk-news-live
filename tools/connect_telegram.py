"""Authorize the local Telegram MTProto session used by live_monitor."""
from __future__ import annotations

import asyncio
import sys
import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from external_sources import _new_telegram_client  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402
import qrcode  # noqa: E402


def main() -> None:
    client = _new_telegram_client()
    try:
        client.connect()
        if not client.is_user_authorized():
            # QR login avoids reliance on SMS or app-delivered login codes.
            # Refresh the short-lived QR automatically until it is scanned.
            qr_login = client.qr_login()
            try:
                while True:
                    code = qrcode.QRCode(border=2, box_size=1)
                    code.add_data(qr_login.url)
                    code.make(fit=True)
                    print("\nОткрой на телефоне Telegram → Настройки → Устройства → Подключить устройство.\n"
                          "Отсканируй САМЫЙ НИЖНИЙ QR-код с экрана. Он обновляется автоматически:\n")
                    for row in code.get_matrix():
                        print("".join("██" if cell else "  " for cell in row))
                    try:
                        client.loop.run_until_complete(qr_login.wait(timeout=20))
                        break
                    except asyncio.TimeoutError:
                        client.loop.run_until_complete(qr_login.recreate())
                        print("QR обновлён — используй новый код ниже.")
            except SessionPasswordNeededError:
                password = getpass.getpass("Пароль двухэтапной защиты Telegram: ")
                client.sign_in(password=password)
        account = client.get_me()
        label = f"@{account.username}" if account.username else str(account.id)
        print(f"Telegram подключён: {label}")
        print("Файл сессии сохранён в .secrets/telegram_user.session")
    finally:
        if client.is_connected():
            client.disconnect()


if __name__ == "__main__":
    main()
