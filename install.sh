#!/usr/bin/env bash
# One-time setup on the Pi, run from the clone as the user the services should run as.
set -euo pipefail
cd "$(dirname "$0")"

sudo apt-get install -y -qq bluetooth bluez python3-venv git
sudo rfkill unblock bluetooth
# Node 22 and pnpm, as in the web app's engines
if ! node -v 2>/dev/null | grep -q '^v2[2-9]'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource.sh && sudo bash /tmp/nodesource.sh
  sudo apt-get install -y -qq nodejs
fi
sudo npm i -g "pnpm@$(node -p "require('./web/package.json').packageManager.split('@')[1]")"
python3 -m venv .venv
.venv/bin/pip install --quiet -r requirements.txt
(cd web && pnpm install --frozen-lockfile --reporter=silent && pnpm build >/dev/null)
# the panel's Bluetooth address, kept out of the repo. The panel shows up as LED_BLE_…
if ! grep -q '^LED_ADDRESS=' .env 2>/dev/null; then
  .venv/bin/pypixelcolor --scan
  read -rp "The panel's Bluetooth address: " address
  echo "LED_ADDRESS=$address" >> .env
fi
# the units are written for user pi with the clone at /home/pi/led, so fill in this user and clone
for unit in systemd/*; do
  sed -e "s#/home/pi/led#$PWD#g; s#/home/pi#$HOME#g; s#^User=pi\$#User=$(id -un)#" "$unit" | sudo tee "/etc/systemd/system/${unit#systemd/}" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now ledserver led-web led-update.timer
