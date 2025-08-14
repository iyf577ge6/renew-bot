# Renew Bot

Telegram bot for Marzban renewals.

## Installation

1. Ensure Python 3.10+ is installed.
2. Run the install script and follow the prompts:
   ```bash
   bash install.sh
   ```
   The script will ask for:
   - **Bot token**
   - **Super admin Telegram ID** (comma separated for multiple)
   - **Panel address**
   - **Sudo username**
   - **Sudo password**
   - **Bot status** (`on` or `off`)

   The script creates a `.env` file, sets up a virtual environment and installs dependencies.
3. Start the bot:
   ```bash
   source venv/bin/activate
   python bot.py
   ```

Only Telegram IDs configured as admins can interact with the bot; everyone else is ignored. The super admin is the only role allowed to add balance to other admins.

## Environment variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Telegram bot token |
| `SUPERADMIN_IDS` | Comma-separated super admin Telegram IDs |
| `MARZBAN_ADDRESS` | Marzban panel URL |
| `MARZBAN_USERNAME` | Marzban sudo username |
| `MARZBAN_PASSWORD` | Marzban sudo password |
| `BOT_STATUS` | `on` to run the bot, `off` to exit immediately |
