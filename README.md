# bot_1 — Telegram Support + Broadcast Bot

Production-ready standalone Telegram bot for support (forward private messages to admin group, reply from group) and broadcast with rate limiting.

**Production deployment:** see [DEPLOYMENT.md](DEPLOYMENT.md) for Ubuntu VPS setup with systemd.

## Tech stack

- Python 3.11+
- python-telegram-bot 21.0.1
- asyncpg, python-dotenv
- PostgreSQL

## Setup

### 1. Create virtual environment and install dependencies

```bash
cd bot_1
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
```

### 2. PostgreSQL

Create database and user:

```sql
CREATE USER botuser WITH PASSWORD 'strongpassword123';
CREATE DATABASE bot1_db OWNER botuser;
```

Tables (`users`, `settings`, `broadcasts`, `forward_mapping`) are created automatically on first run.

### 3. Environment

Copy `.env.example` to `.env` and fill in values:

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS
```

Edit `.env`:

- `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
- `ADMIN_GROUP_ID` — Telegram group ID where admins receive forwarded messages and use `/panel` (e.g. `-1001234567890`). Add the bot to the group and make it admin so it can read and send messages.
- `ADMIN_USER_IDS` — (optional) Comma-separated Telegram user IDs allowed to use `/panel`, broadcast, set welcome, stats, and cleanup (e.g. `123456789,987654321`). If empty, any user in the admin group can use the panel.
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_PORT` — PostgreSQL connection (defaults in `.env.example`).

To get `ADMIN_GROUP_ID`: add [@userinfobot](https://t.me/userinfobot) to the group and note the group id, or use the value from the group invite link (e.g. `-100xxxxxxxxxx`).

### 4. Run

```bash
python main.py
```

The bot runs with polling. After filling `.env`, it should start without code changes.

## Features

- **/start** — Registers user, updates `last_active`, sends welcome (from DB or default).
- **Private messages** — Forwarded to admin group (no captions); mapping stored for replies.
- **Admin group** — Reply to a forwarded message to send that reply back to the user (text/media); blocked users are marked.
- **/panel** (admin group only) — Inline keyboard: Broadcast, Stats, Set Welcome, Cleanup.
- **Set Welcome** — Store one message (text or media) as welcome; new /start users receive it.
- **Stats** — Total users, active (7 days), blocked count.
- **Cleanup** — Deletes DB rows where `is_blocked = TRUE`.
- **Broadcast** — Send one message to all non-blocked users. Uses a queue-based worker pool and `asyncio.Semaphore` for rate limiting (25/sec). Prefers `copy_message` when the admin sends from the group (media preserved); falls back to payload send. Retry logic for `RetryAfter`; single-user failures do not stop the run. Progress and completion sent to admin group. Admin-only when `ADMIN_USER_IDS` is set.

## Project structure

```
bot_1/
  main.py              # Entry, ApplicationBuilder, handlers, error handler, shutdown
  config.py            # Env loading
  database.py          # asyncpg pool, tables, CRUD
  broadcast.py         # Rate-limited broadcast + FloodWait
  handlers/
    start.py           # /start + welcome from DB
    private_messages.py # Forward private → admin group
    admin_group.py     # Reply in group → send to user
    admin_panel.py     # /panel, callbacks, set welcome, broadcast trigger
  requirements.txt
  .env.example
```
