#!/usr/bin/env bash
# Gọi vod.py bằng cùng môi trường Python với web app.  Dùng: ./vod.sh <lệnh> [tham số]  (vd. ./vod.sh status)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ODOO_VENV=/Users/khaid/Works/odoo-18.0/venv/bin/python
if [ -n "$TT_PYTHON" ]; then
  PY="$TT_PYTHON"
elif [ -x "$DIR/../webapp/.venv/bin/python" ]; then
  PY="$DIR/../webapp/.venv/bin/python"     # Ubuntu: tạo bởi webapp/install_ubuntu.sh
elif [ -x "$ODOO_VENV" ]; then
  PY="$ODOO_VENV"                            # máy Mac dev
else
  echo "Chưa có môi trường Python. Ubuntu: chạy webapp/install_ubuntu.sh trước." >&2
  exit 1
fi
exec "$PY" "$DIR/vod.py" "$@"
