#!/usr/bin/env bash
# Đóng gói web app để copy sang máy khác (Ubuntu): tạo ../dist/tesseract-trainer-<ngày>.tar.gz
# Không gồm dữ liệu/tài liệu khách hàng, .venv hay model.
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
OUT="$KIT/dist/tesseract-trainer-$(date +%Y%m%d).tar.gz"
DEST="$STAGE/tesseract-trainer"

mkdir -p "$DEST/webapp/static" "$KIT/dist"
cp "$KIT"/{make_gt.py,crop_for_labeling.py,eval_lines.py,HUONG-DAN-CHUAN-BI-DU-LIEU.md} "$DEST/"
cp "$KIT/webapp/README-UBUNTU.md" "$DEST/README.md"
cp "$KIT"/webapp/{app.py,pipeline.py,refmatch.py,run.sh,install_ubuntu.sh,install_service.sh,requirements.txt,README-UBUNTU.md} "$DEST/webapp/"
mkdir -p "$DEST/webapp/tests" && cp "$KIT"/webapp/tests/*.py "$DEST/webapp/tests/"
cp "$KIT"/webapp/static/{index.html,app.js,style.css} "$DEST/webapp/static/"
mkdir -p "$DEST/vie-ocr-data/downloader" "$DEST/vie-ocr-data/tests"
cp "$KIT"/vie-ocr-data/{vod.py,vod.sh,vod-bg.sh,extract.py,build_gt.py,textproc.py,sources.yaml,README.md} "$DEST/vie-ocr-data/"
cp "$KIT"/vie-ocr-data/downloader/*.py "$DEST/vie-ocr-data/downloader/"
cp "$KIT"/vie-ocr-data/tests/*.py "$DEST/vie-ocr-data/tests/"
cp "$KIT/Nguồn dữ liệu train Tesseract OCR tiếng Việt.md" "$DEST/vie-ocr-data/SPEC.md"
chmod +x "$DEST/webapp/run.sh" "$DEST/webapp/install_ubuntu.sh" "$DEST/webapp/install_service.sh" "$DEST/vie-ocr-data/vod.sh" "$DEST/vie-ocr-data/vod-bg.sh"

COPYFILE_DISABLE=1 tar -czf "$OUT" -C "$STAGE" tesseract-trainer   # COPYFILE_DISABLE: không kèm file ._ của macOS
echo "$OUT"
tar -tzf "$OUT"
