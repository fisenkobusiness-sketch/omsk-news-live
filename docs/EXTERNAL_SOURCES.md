# External topic sources

The live monitor reads public Telegram channel history through MTProto and can also read configured RSS/Atom feeds. External views, reactions, comments, and forwards are not used in ranking or ML training. The Telegram source contributes full text/captions, publication time, link, and attachment type for topic discovery.

## Telegram channels

Configured Telegram channels:

- `@omskinform_news` — Омск-информ
- `@kanal12omsk` — 12 Канал | Новости Омска
- `@gorod55ru` — Город55 | Новости Омска
- `@Om1_Omsk` — Om1: Новости Омска и России
- `@omsk_smi` — Новости Омска и Области
- `@incident_55ru` — Инцидент Омск!
- `-1001178109741` - Omsk Live (private channel; requires existing Telegram session access)
- `-1001432513803` - Incident Omsk (private channel; requires existing Telegram session access)
- `-1001587149148` - O chem govoryat v Omske (private channel; requires existing Telegram session access)
- `@omsk360` — Омск 360°
- `@omsktop1` — Омск с огоньком
- `@chp_55` — ЧП Омск
- `@zhest_omsk_55` — Жесть Омск
- `@region_omsk55` — Омск | Регион-55
- `@omsks` — Омск сегодня
- `@aomsk` — Аварийный Омск
- `@ghest_omsk` — Я в шоке. Омск
- `@moiiomsk` — Мой Омск
- `@omskkoroche` — Короче, Омск
- `@ngs55news` — Новости Омска | NGS55
- `@newsomsk` — Новости Омска
- `@vestiomsk` — ВЕСТИ ОМСК
- `@omskpravda` — Омская правда
- `@TramplinOmsk` — Трамплин Медиа
- `@kdomsk` — Камеры ДПС Омск
- `@forumomskcom` — Омский форум
- `@mec_55` — Экономика | 55

The monitor polls every five minutes and reads up to the latest 100 messages from each channel. A numeric `-100...` key works for a private channel available to the authorized Telegram account; message links use Telegram's `t.me/c/...` format. The current Omsk-day filter and deduplication in `live_monitor.py` decide which messages enter the editorial pipeline.

## One-time setup

1. Install the Telegram collector dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-telegram.txt
   ```

2. Create an application at [my.telegram.org](https://my.telegram.org) under **API development tools**.
3. Save the application ID to `.secrets/telegram_api_id.txt` and the API hash to `.secrets/telegram_api_hash.txt`. These are separate from the existing Telegram bot token.
4. If the computer cannot reach Telegram directly, save a SOCKS5 URL to `.secrets/telegram_proxy.txt`, for example `socks5://user:password@host:port`. A proxy can also be configured with the `TELEGRAM_PROXY` environment variable. Alternatively, run the collector on a server that can reach Telegram.
5. Authorize once from the project folder:

   ```powershell
   .\.venv\Scripts\python.exe tools\connect_telegram.py
   ```

   Scan the QR code printed in the local terminal using Telegram on your phone: **Settings → Devices → Link Desktop Device**. If 2FA is enabled, enter its password in the terminal. The script stores the reusable session under `.secrets/telegram_user.session`.

The API hash and session file grant access to the account. Keep both inside `.secrets`; do not send them in chat or commit them. The repository ignores the full `.secrets` directory.

The monitor does not request a login code. If the one-time authorization has not been completed, it logs setup instructions and keeps processing VK and RSS sources.

## Channel configuration

Copy `tools/external_sources.example.json` to `runtime/external_sources.json` to change Telegram channel names or add RSS/Atom feeds:

```json
{
  "telegram_channels": {
    "omskinform_news": "Омск-информ"
  },
  "rss_feeds": [
    {"name": "Example media", "url": "https://example.org/rss.xml"}
  ]
}
```

For each Telegram message, the collector saves the text, timestamp, channel, post ID, public link, and media type when available. It does not download media files or run OCR. Posts with media captions are kept; media-only posts are skipped because the current topic classifier needs text.

RSS posts contribute their headline, summary, date, and link. They do not contribute audience counters.

## Current limitations

- The account must be able to access each channel. The collector reads public channel history available to that account.
- Network restrictions still require a working SOCKS5 proxy or a machine/server with Telegram connectivity.
- This connector is for topic discovery. The ML model learns from the 1-hour and 3-hour results of the two target VK communities only.
- A separate search-engine connector is not configured yet.
