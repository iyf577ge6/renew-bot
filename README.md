# Renew Bot

Telegram bot for Marzban renewals.

## Get the code

Clone with git:

```bash
git clone https://github.com/iyf577ge6/renew-bot.git
cd renew-bot
```

## Prerequisites

- Python 3.10 or newer
- `python3-venv` to create virtual environments (e.g. `sudo apt install python3-venv`)
- `git` (if cloning the repository)

## Installation

1. Run the install script:

```bash
bash install.sh
```

On first run it will ask for:
- **Bot token**
- **Super admin Telegram ID** (comma separated for multiple)
- **Panel address**
- **Sudo username**
- **Sudo password**
- **Bot status** (`on` or `off`)

A `.env` file is created, a virtual environment is set up and dependencies are installed. Subsequent runs reuse the existing `.env`. To change values run:

```bash
bash install.sh --configure
```

To remove the virtual environment, configuration and database, run:

```bash
bash install.sh uninstall
```

2. Start the bot:

```bash
source venv/bin/activate
python3 bot.py
```

Only Telegram IDs configured as admins or those already registered as customers can interact with the bot. Others are ignored and not stored. The super admin is the only role allowed to add balance to other admins.

## Environment variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Telegram bot token |
| `SUPERADMIN_IDS` | Comma-separated super admin Telegram IDs |
| `MARZBAN_ADDRESS` | Marzban panel URL |
| `MARZBAN_USERNAME` | Marzban sudo username |
| `MARZBAN_PASSWORD` | Marzban sudo password |
| `BOT_STATUS` | `on` to run the bot, `off` to exit immediately |

## Run with systemd

A sample unit file `renew-bot.service` is provided to run the bot as a
service. Adjust the `User`, `WorkingDirectory` and `ExecStart` paths as
needed, then install and enable it:

```bash
sudo cp renew-bot.service /etc/systemd/system/renew-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now renew-bot
```

Useful commands to manage the service:

```bash
sudo systemctl status renew-bot   # view status
sudo systemctl stop renew-bot     # stop the bot
sudo systemctl start renew-bot    # start the bot
sudo systemctl restart renew-bot  # restart the bot
```

`Restart=always` in the unit file ensures the bot is restarted if it
exits unexpectedly, and enabling the service makes it start automatically
after reboots.
