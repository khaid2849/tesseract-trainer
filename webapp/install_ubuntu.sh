#!/usr/bin/env bash
# Cài môi trường cho web app train Tesseract trên Ubuntu 22.04 / 24.04 (cần quyền sudo cho apt).
#   ./install_ubuntu.sh               cài gói hệ thống + tạo .venv
#   ./install_ubuntu.sh --tesseract5  thêm PPA alex-p/tesseract-ocr5 khi Ubuntu chỉ có Tesseract 4.x (22.04)
#   ./install_ubuntu.sh --msfonts     cài thêm font Microsoft (Times New Roman, Arial…) cho dòng giả lập giống tài liệu hơn
set -euo pipefail
cd "$(dirname "$0")"

WANT_T5=0
WANT_MSFONTS=0
for arg in "$@"; do
  case "$arg" in
    --tesseract5) WANT_T5=1 ;;
    --msfonts) WANT_MSFONTS=1 ;;
    *) echo "Tham số không hợp lệ: $arg" >&2; exit 2 ;;
  esac
done

. /etc/os-release
echo "== Hệ điều hành: $PRETTY_NAME"
case "${ID:-} ${ID_LIKE:-}" in
  *ubuntu*|*debian*) ;;
  *) echo "!! Script viết cho Ubuntu/Debian, có thể không chạy đúng trên ${ID:-?}" >&2 ;;
esac

if [ "$WANT_T5" = 1 ]; then
  echo "== Thêm PPA Tesseract 5"
  sudo apt-get update
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository -y ppa:alex-p/tesseract-ocr5
fi

echo "== Cài gói hệ thống"
sudo apt-get update
# tesseract-ocr đã gồm lstmtraining, combine_lang_model… (công cụ train); osd để xoay thẳng trang scan
# libarchive-tools (bsdtar): giải nén .rar của nguồn VNTC trong vie-ocr-data
sudo apt-get install -y tesseract-ocr tesseract-ocr-osd make git curl python3 python3-venv python3-pip \
  fonts-liberation fonts-dejavu-core fonts-noto-core libarchive-tools

if [ "$WANT_MSFONTS" = 1 ]; then
  echo "== Cài font Microsoft: màn hình giấy phép EULA sẽ hiện ra, bạn tự đọc và chọn đồng ý"
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository -y multiverse
  sudo apt-get update
  sudo apt-get install -y ttf-mscorefonts-installer
fi

TV=$(tesseract --version 2>&1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)
echo "== Tesseract $TV"
if [ "${TV%%.*}" -lt 5 ]; then
  echo "!! Tesseract $TV vẫn train được, nhưng nên dùng 5.x cho khớp server (Debian bookworm 5.3)."
  echo "   Chạy lại: ./install_ubuntu.sh --tesseract5"
fi
for tool in lstmtraining combine_tessdata combine_lang_model unicharset_extractor merge_unicharsets; do
  command -v "$tool" >/dev/null || { echo "!! Thiếu $tool sau khi cài tesseract-ocr" >&2; exit 1; }
done

echo "== Tạo môi trường Python (.venv)"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import pymupdf, cv2, numpy, pytesseract, docx, werkzeug, yaml, requests, tqdm; print('Thư viện Python: OK')"

cat <<'EOF'

Xong. Bước tiếp theo:
  ./install_service.sh 8770   # chạy app nền (systemd), mất SSH không dừng, tự chạy khi khởi động máy
Mở giao diện từ máy khác: xem README-UBUNTU.md, mục SSH tunnel. Lần đầu vào tab "1. Môi trường" bấm "Cài đặt tự động".
EOF
