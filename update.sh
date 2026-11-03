#!/usr/bin/env bash
# Pull origin/main. If it moved, install deps, build the web app and units, then restart.
set -euo pipefail
# braces: bash reads the whole script before running it, since git reset rewrites this file
{
cd "$(dirname "$0")"

git fetch --quiet origin main
# .deployed is the last commit that got all the way through, so a deploy cut short (the Pi
# restarted mid-build) runs again at the next check instead of leaving a broken build
[ "$(cat .deployed 2>/dev/null)" = "$(git rev-parse origin/main)" ] && exit 0

git reset --hard --quiet origin/main
echo "deploying $(git log -1 --format='%h %s')"
.venv/bin/pip install --quiet -r requirements.txt
# lowest CPU and disk priority, so the panel, the page and SSH stay responsive meanwhile
(cd web && nice -n 19 ionice -c 3 pnpm install --frozen-lockfile --reporter=silent && nice -n 19 ionice -c 3 pnpm build >/dev/null)
# as in install.sh: the units filled in for this user and clone
for unit in systemd/*; do
  sed -e "s#/home/pi/led#$PWD#g; s#/home/pi#$HOME#g; s#^User=pi\$#User=$(id -un)#" "$unit" | sudo tee "/etc/systemd/system/${unit#systemd/}" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --quiet ledserver led-web led-update.timer
sudo systemctl restart ledserver led-web
git rev-parse HEAD > .deployed
exit
}
