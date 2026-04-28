#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "This creates kis_config.local.env for KIS paper trading."
echo "The file stays on this machine and is ignored by git."
echo

while true; do
  read -r -p "KIS app key: " KIS_APP_KEY
  if [ -n "$KIS_APP_KEY" ]; then
    break
  fi
  echo "KIS app key is required."
done

while true; do
  read -r -s -p "KIS app secret: " KIS_APP_SECRET
  echo
  if [ -n "$KIS_APP_SECRET" ]; then
    break
  fi
  echo "KIS app secret is required."
done

while true; do
  read -r -p "KIS account number, 8 digits: " KIS_ACCOUNT_NO
  if [ -n "$KIS_ACCOUNT_NO" ]; then
    break
  fi
  echo "KIS account number is required."
done
read -r -p "KIS account product code [01]: " KIS_ACCOUNT_PRODUCT_CODE
KIS_ACCOUNT_PRODUCT_CODE="${KIS_ACCOUNT_PRODUCT_CODE:-01}"
read -r -p "Telegram bot token [skip]: " TELEGRAM_BOT_TOKEN
read -r -p "Telegram chat id [skip]: " TELEGRAM_CHAT_ID

cat > kis_config.local.env <<EOF
KIS_APP_KEY=$KIS_APP_KEY
KIS_APP_SECRET=$KIS_APP_SECRET
KIS_ACCOUNT_NO=$KIS_ACCOUNT_NO
KIS_ACCOUNT_PRODUCT_CODE=$KIS_ACCOUNT_PRODUCT_CODE
KIS_ENV=paper
KIS_ENABLE_ORDERS=true
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
EOF

chmod 600 kis_config.local.env

echo
echo "Saved kis_config.local.env"
echo "Paper orders are enabled for KIS_ENV=paper."
echo "Press Enter to close."
read -r _
