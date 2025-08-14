#!/bin/bash
set -e

ENV_FILE=".env"
DB_DIR="/var/lib/marzban/renew-tg-bot"

if [ "$1" = "uninstall" ]; then
  rm -rf venv "$ENV_FILE" "$DB_DIR"
  echo "Uninstallation complete."
  exit 0
fi

CONFIGURE=false
if [ "$1" = "--configure" ] || [ ! -f "$ENV_FILE" ]; then
  CONFIGURE=true
fi

if [ "$CONFIGURE" = true ]; then
  [ -f "$ENV_FILE" ] && source "$ENV_FILE"

  read -p "Bot token [${TELEGRAM_TOKEN:-}]: " input
  TELEGRAM_TOKEN=${input:-$TELEGRAM_TOKEN}

  read -p "Superadmin ID(s) (comma separated) [${SUPERADMIN_IDS:-}]: " input
  SUPERADMIN_IDS=${input:-$SUPERADMIN_IDS}

  read -p "Panel address [${MARZBAN_ADDRESS:-}]: " input
  MARZBAN_ADDRESS=${input:-$MARZBAN_ADDRESS}

  read -p "Sudo username [${MARZBAN_USERNAME:-}]: " input
  MARZBAN_USERNAME=${input:-$MARZBAN_USERNAME}

  read -s -p "Sudo password [${MARZBAN_PASSWORD:+***}]: " input
  echo
  MARZBAN_PASSWORD=${input:-$MARZBAN_PASSWORD}

  read -p "Bot status (on/off) [${BOT_STATUS:-on}]: " input
  BOT_STATUS=${input:-${BOT_STATUS:-on}}

  cat > "$ENV_FILE" <<EOT
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
SUPERADMIN_IDS=$SUPERADMIN_IDS
MARZBAN_ADDRESS=$MARZBAN_ADDRESS
MARZBAN_USERNAME=$MARZBAN_USERNAME
MARZBAN_PASSWORD=$MARZBAN_PASSWORD
BOT_STATUS=$BOT_STATUS
EOT
else
  echo "Using existing configuration from $ENV_FILE. Run '$0 --configure' to modify."
  source "$ENV_FILE"
fi

if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "\nInstallation complete. Activate with 'source venv/bin/activate' and run 'python bot.py'."
