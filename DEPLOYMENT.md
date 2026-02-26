# Production Deployment Guide — Ubuntu VPS with systemd

This guide deploys **bot_1** (Telegram support + broadcast bot) on an Ubuntu VPS and runs it as a systemd service with automatic restart and logging.

---

## 1. Prerequisites

- **Ubuntu Server** 22.04 LTS or 24.04 LTS (or 20.04 with Python 3.11 from deadsnakes)
- **SSH** access as a user with `sudo`
- **Domain or IP** for the VPS (optional; bot uses polling, no public URL required)

---

## 2. Initial Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Optional: set timezone
sudo timedatectl set-timezone UTC
```

---

## 3. Install Python 3.11+

**Ubuntu 24.04** ships Python 3.12; **22.04** ships 3.10. For 3.11+ on 22.04:

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

Verify:

```bash
python3.11 --version   # Should be 3.11.x or higher
```

---

## 4. Install PostgreSQL

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

Create database and user (replace password with a strong one):

```bash
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE bot1_db OWNER botuser;"
sudo -u postgres psql -c "GRANT CONNECT ON DATABASE bot1_db TO botuser;"
```

Optional: allow local connections only (default in `pg_hba.conf`):

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = 'localhost';"
sudo systemctl restart postgresql
```

---

## 5. Create System User and Directories

Run the bot as an unprivileged user:

```bash
sudo useradd -r -s /bin/false -d /opt/bot1 -m bot1
sudo mkdir -p /opt/bot1/app
sudo mkdir -p /opt/bot1/venv
sudo chown -R bot1:bot1 /opt/bot1
```

---

## 6. Deploy Application Code

From your dev machine, copy the project to the server (adjust paths and host):

```bash
# From your dev machine (Windows PowerShell or WSL)
scp -r "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\main.py" \
      "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\config.py" \
      "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\database.py" \
      "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\broadcast.py" \
      "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\requirements.txt" \
      "c:\Work\Mahadev Ads Agency\NEW BROADCAST BOT 25 FEB\bot_1\handlers" \
      user@YOUR_VPS_IP:/tmp/bot1_deploy/
```

Or clone from git on the server:

```bash
sudo -u bot1 git clone https://github.com/YOUR_ORG/bot_1.git /opt/bot1/app
# Then remove .git if you don't need it: rm -rf /opt/bot1/app/.git
```

**Manual copy (on the server):** upload only the app files (no `.env`, no `.venv`):

- `main.py`, `config.py`, `database.py`, `broadcast.py`, `requirements.txt`
- `handlers/` directory (all `.py` files)

Ensure ownership:

```bash
sudo chown -R bot1:bot1 /opt/bot1/app
```

---

## 7. Python Virtual Environment and Dependencies

```bash
sudo -u bot1 python3.11 -m venv /opt/bot1/venv
sudo -u bot1 /opt/bot1/venv/bin/pip install --upgrade pip
sudo -u bot1 /opt/bot1/venv/bin/pip install -r /opt/bot1/app/requirements.txt
```

Verify:

```bash
/opt/bot1/venv/bin/python -c "import telegram; import asyncpg; print('OK')"
```

---

## 8. Environment Configuration

Create `.env` on the server (do **not** commit it):

```bash
sudo -u bot1 nano /opt/bot1/app/.env
```

Contents (fill every value):

```env
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_GROUP_ID=-1001234567890
ADMIN_USER_IDS=123456789,987654321
DB_HOST=localhost
DB_NAME=bot1_db
DB_USER=botuser
DB_PASS=YOUR_STRONG_PASSWORD
DB_PORT=5432
```

Restrict permissions:

```bash
sudo chmod 600 /opt/bot1/app/.env
sudo chown bot1:bot1 /opt/bot1/app/.env
```

---

## 9. systemd Service

Install the unit file:

```bash
sudo cp /opt/bot1/app/deploy/bot1.service /etc/systemd/system/
# If you didn't deploy the deploy folder:
# sudo nano /etc/systemd/system/bot1.service
# Paste the contents from deploy/bot1.service
```

Reload systemd and enable the service (start on boot):

```bash
sudo systemctl daemon-reload
sudo systemctl enable bot1
sudo systemctl start bot1
sudo systemctl status bot1
```

You should see `active (running)`. The bot creates DB tables on first run.

---

## 10. Useful Commands

| Action | Command |
|--------|--------|
| Start | `sudo systemctl start bot1` |
| Stop | `sudo systemctl stop bot1` |
| Restart | `sudo systemctl restart bot1` |
| Status | `sudo systemctl status bot1` |
| Enable on boot | `sudo systemctl enable bot1` |
| Disable on boot | `sudo systemctl disable bot1` |
| Live logs | `sudo journalctl -u bot1 -f` |
| Last 100 lines | `sudo journalctl -u bot1 -n 100` |
| Logs since boot | `sudo journalctl -u bot1 -b` |
| Logs with time | `sudo journalctl -u bot1 -f -o short-precise` |

---

## 11. Logging

Logs go to **journald** (stdout/stderr of the service). No extra log file is required.

Persist logs across reboots (optional):

```bash
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald
```

Or in `/etc/systemd/journald.conf` set `Storage=persistent` and restart `systemd-journald`.

---

## 12. Updating the Bot

```bash
# Stop the service
sudo systemctl stop bot1

# Update code (example: copy new files or git pull)
# e.g. sudo -u bot1 git -C /opt/bot1/app pull

# Update dependencies if requirements.txt changed
sudo -u bot1 /opt/bot1/venv/bin/pip install -r /opt/bot1/app/requirements.txt

# Start again
sudo systemctl start bot1
sudo systemctl status bot1
```

---

## 13. Security Checklist

- [ ] `.env` has mode `600` and is owned by `bot1`.
- [ ] Bot runs as user `bot1`, not root.
- [ ] PostgreSQL listens only on `localhost` (default).
- [ ] Firewall: allow SSH (22), block everything else if no other services (e.g. `ufw allow 22 && ufw enable`).
- [ ] Keep OS and Python/PostgreSQL updated: `sudo apt update && sudo apt upgrade -y`.
- [ ] Use a strong `DB_PASS` and keep `BOT_TOKEN` and `.env` out of version control.

---

## 14. Troubleshooting

**Service fails to start**

- Check: `sudo systemctl status bot1` and `sudo journalctl -u bot1 -n 50`.
- Ensure `/opt/bot1/app/.env` exists and is readable by `bot1`.
- Run manually: `sudo -u bot1 /opt/bot1/venv/bin/python -m main` from `/opt/bot1/app` (with `cd /opt/bot1/app` and same `.env`) to see tracebacks.

**Database connection errors**

- Confirm PostgreSQL is running: `sudo systemctl status postgresql`.
- Test: `sudo -u postgres psql -c "\l"` and connect as `botuser`: `psql -h localhost -U botuser -d bot1_db -c "SELECT 1;"` (from a shell where you set `PGPASSWORD` or use `.pgpass`).
- Ensure `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME` in `.env` match the created user and database.

**Permission denied**

- `ls -la /opt/bot1` and `/opt/bot1/app` should be owned by `bot1:bot1`.
- If you use stricter systemd options (e.g. `ProtectSystem=strict`), ensure `ReadWritePaths=/opt/bot1` is set so the process can access app and venv.

**Bot not responding**

- Confirm `BOT_TOKEN` is correct and the bot is not disabled in BotFather.
- Confirm `ADMIN_GROUP_ID` is correct (negative integer for groups) and the bot is in the group with enough permissions.

---

## 15. Optional: Deploy Script

Example script to copy files and restart (run from your dev machine or CI):

```bash
#!/bin/bash
# deploy.sh — run from project root
set -e
RSYNC_TARGET="${1:?Usage: ./deploy.sh user@vps}"
rsync -avz --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude '*.pyc' \
  main.py config.py database.py broadcast.py requirements.txt \
  handlers/ deploy/ \
  "$RSYNC_TARGET:/tmp/bot1_deploy/"
ssh "$RSYNC_TARGET" 'sudo cp -r /tmp/bot1_deploy/* /opt/bot1/app/ && sudo chown -R bot1:bot1 /opt/bot1/app && sudo systemctl restart bot1'
```

Create `.env` once on the server manually; do not overwrite it with deploy.

---

You now have **bot_1** running as a systemd service on Ubuntu, with automatic restart, journald logging, and a clear path for updates and troubleshooting.
