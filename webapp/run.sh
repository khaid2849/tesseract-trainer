#!/usr/bin/env bash
# Chạy web app train Tesseract. Dùng: ./run.sh [port]  → mở http://127.0.0.1:8765
# Biến môi trường: TT_WORK (thư mục dữ liệu, mặc định ~/Works/tesseract-train), TT_PYTHON, TT_HOST.
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ODOO_VENV=/Users/khaid/Works/odoo-18.0/venv/bin/python
if [ -n "$TT_PYTHON" ]; then
  PY="$TT_PYTHON"
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python          # tạo bởi install_ubuntu.sh
elif [ -x "$ODOO_VENV" ]; then
  PY="$ODOO_VENV"              # máy Mac dev: venv Odoo đã đủ thư viện
else
  echo "Chưa có môi trường Python. Ubuntu: chạy ./install_ubuntu.sh trước." >&2
  exit 1
fi
exec "$PY" app.py "${1:-8765}"
