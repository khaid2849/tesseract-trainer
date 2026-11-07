#!/usr/bin/env bash
# Kéo code mới từ GitHub rồi khởi động lại web app (service). Dùng: ./update.sh [--force]
# Đang có việc chạy (xử lý file, train) thì chỉ kéo code, chưa khởi động lại; --force dừng việc đó rồi khởi động lại.
set -euo pipefail
cd "$(dirname "$0")"
NAME=tesseract-trainer
UNIT="$HOME/.config/systemd/user/$NAME.service"
MARK=webapp/.deployed-commit
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

before=$(git rev-parse HEAD)
git pull --ff-only
after=$(git rev-parse HEAD)
if [ "$before" != "$after" ]; then
  git log --oneline "$before..$after"
  if ! git diff --quiet "$before" "$after" -- webapp/requirements.txt; then
    echo "== requirements.txt thay đổi: cài lại thư viện Python"
    webapp/.venv/bin/pip install -r webapp/requirements.txt
  fi
fi

if [ ! -f "$UNIT" ]; then
  echo "Chưa cài service (webapp/install_service.sh). Nếu app đang chạy bằng run.sh thì tự khởi động lại."
  exit 0
fi
if [ "$(cat "$MARK" 2>/dev/null)" = "$after" ] && [ "$FORCE" = 0 ]; then
  echo "App đang chạy bản mới nhất ($(git log -1 --format='%h %s'))."
  exit 0
fi

PORT=$(sed -n 's|^ExecStart=.*run\.sh \([0-9]*\)$|\1|p' "$UNIT")
job_status() {
  curl -s --max-time 5 "http://127.0.0.1:$PORT/api/job" \
    | python3 -c 'import json,sys; j=json.load(sys.stdin); print(j["status"] if j else "")' 2>/dev/null || true
}
if [ "$(job_status)" = running ]; then
  if [ "$FORCE" = 0 ]; then
    echo "!! App đang chạy một việc (xem trên web). Code mới đã kéo về nhưng CHƯA khởi động lại app."
    echo "   Đợi việc xong rồi chạy lại ./update.sh, hoặc ./update.sh --force để dừng việc đó."
    exit 1
  fi
  echo "== Dừng việc đang chạy"
  curl -s -X POST "http://127.0.0.1:$PORT/api/stop" >/dev/null || true
  for _ in $(seq 30); do [ "$(job_status)" = running ] || break; sleep 1; done
fi

systemctl --user restart "$NAME"
echo "$after" > "$MARK"
echo "Đã khởi động lại app với bản $(git log -1 --format='%h %s') (cổng $PORT)."
