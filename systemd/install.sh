#!/usr/bin/env bash
# Installs the T-287 token-usage-sampler timer as a user-level systemd unit.
# Run AFTER this repo is checked out at ~/repos/cortex-board (the .service's
# ExecStart is pinned to that path) -- symlinks the units in, does not copy,
# so `git pull` keeps them current.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

ln -sf "$REPO_DIR/systemd/cortex-board-token-sample.timer" "$UNIT_DIR/cortex-board-token-sample.timer"
ln -sf "$REPO_DIR/systemd/cortex-board-token-sample.service" "$UNIT_DIR/cortex-board-token-sample.service"

systemctl --user daemon-reload
systemctl --user enable --now cortex-board-token-sample.timer

echo "installed + enabled: cortex-board-token-sample.timer"
systemctl --user list-timers cortex-board-token-sample.timer --no-pager || true
