#!/bin/bash
set -e

read -p "Bot token: " TELEGRAM_TOKEN
read -p "Superadmin ID(s) (comma separated): " SUPERADMIN_IDS
read -p "Panel address: " MARZBAN_ADDRESS
read -p "Sudo username: " MARZBAN_USERNAME
read -s -p "Sudo password: " MARZBAN_PASSWORD
echo
read -p "Bot status (on/off) [on]: " BOT_STATUS
BOT_STATUS=${BOT_STATUS:-on}

cat > .env <<EOT
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
SUPERADMIN_IDS=$SUPERADMIN_IDS
MARZBAN_ADDRESS=$MARZBAN_ADDRESS
MARZBAN_USERNAME=$MARZBAN_USERNAME
MARZBAN_PASSWORD=$MARZBAN_PASSWORD
BOT_STATUS=$BOT_STATUS
EOT

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "\nInstallation complete. Activate with 'source venv/bin/activate' and run 'python bot.py'."
