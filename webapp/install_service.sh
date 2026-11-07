#!/usr/bin/env bash
# Cài web app thành systemd user service: tự chạy khi bật máy, tự chạy lại khi lỗi, không phụ thuộc SSH/tmux.
#   ./install_service.sh [cổng]     mặc định 8765 (biến TT_WORK, VOD_HOME, TT_HOST đang đặt sẽ được ghi vào service)
#   ./install_service.sh --remove   gỡ service
set -euo pipefail
WEBAPP="$(cd "$(dirname "$0")" && pwd)"
NAME=tesseract-trainer
UNIT="$HOME/.config/systemd/user/$NAME.service"

if [ "${1:-}" = "--remove" ]; then
  systemctl --user disable --now "$NAME" 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Đã gỡ service $NAME."
  exit 0
fi

PORT="${1:-8765}"
case "$PORT" in ''|*[!0-9]*) echo "Cổng không hợp lệ: $PORT" >&2; exit 2 ;; esac
[ -x "$WEBAPP/.venv/bin/python" ] || { echo "Chưa có webapp/.venv: chạy ./install_ubuntu.sh trước." >&2; exit 1; }
if ! systemctl --user is-active --quiet "$NAME" && ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "Cổng $PORT đang bị chương trình khác giữ (app cũ chạy bằng run.sh/tmux?). Tắt nó trước:" >&2
  echo "  pkill -f 'app.py $PORT'     rồi chạy lại script này." >&2
  exit 1
fi

# Thiếu linger thì systemd tắt service khi phiên SSH cuối cùng đóng và không tự chạy lúc khởi động máy
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]; then
  echo "== Bật linger cho $USER (cần sudo một lần)"
  sudo loginctl enable-linger "$USER"
fi

mkdir -p "$(dirname "$UNIT")"
{
  echo "[Unit]"
  echo "Description=Tesseract trainer web app (port $PORT)"
  echo
  echo "[Service]"
  echo "WorkingDirectory=$WEBAPP"
  echo "Environment=PYTHONUNBUFFERED=1"
  for var in TT_WORK VOD_HOME TT_HOST; do
    if [ -n "${!var:-}" ]; then echo "Environment=$var=${!var}"; fi
  done
  echo "ExecStart=$WEBAPP/run.sh $PORT"
  echo "Restart=on-failure"
  echo "RestartSec=5"
  echo "TimeoutStopSec=20"
  echo
  echo "[Install]"
  echo "WantedBy=default.target"
} > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable "$NAME" >/dev/null
systemctl --user restart "$NAME"
git -C "$WEBAPP/.." rev-parse HEAD > "$WEBAPP/.deployed-commit" 2>/dev/null || true

for _ in $(seq 20); do
  curl -sf "http://127.0.0.1:$PORT/api/job" >/dev/null && break
  sleep 0.5
done
if curl -sf "http://127.0.0.1:$PORT/api/job" >/dev/null; then
  echo "Xong: app chạy nền ở http://127.0.0.1:$PORT (tự chạy lại khi khởi động máy)."
else
  echo "!! Service chưa trả lời. Xem lỗi: journalctl --user -u $NAME -n 50" >&2
  exit 1
fi
cat <<EOF
  Trạng thái:  systemctl --user status $NAME
  Xem log:     journalctl --user -u $NAME -f
  Dừng/chạy:   systemctl --user stop|start $NAME
  Cập nhật:    ../update.sh
EOF
