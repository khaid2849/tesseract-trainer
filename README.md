# tesseract-trainer

Bộ công cụ fine-tune Tesseract `vie` cho tài liệu scan tiếng Việt (dùng cho module so sánh tài liệu
`syntra_document_compare`). Gồm web app chạy trên máy Ubuntu: upload file gốc, duyệt dòng scan, train, xuất model.

| Thư mục / file | Là gì |
|---|---|
| `webapp/` | Web app train. Cài và chạy trên Ubuntu: `webapp/README-UBUNTU.md` |
| `vie-ocr-data/` | Tải dữ liệu mở (Wikipedia, Wikisource, văn bản Chính phủ + Công báo…), sinh dòng train: `vie-ocr-data/README.md` |
| `HUONG-DAN-CHUAN-BI-DU-LIEU.md` | Chuẩn bị file gốc, chia Train/Đánh giá, quy tắc duyệt dòng scan |
| `docs/GHI-CHU-TRAIN.md` | Ghi chú train bằng lệnh tay, kết quả các lần thử, cách đưa model lên server |
| `make_gt.py`, `crop_for_labeling.py`, `eval_lines.py`, `eval_compare.py` | Script dùng chung (web app gọi lại) và đo kết quả |

**Không commit dữ liệu**: tài liệu khách hàng, dòng đã cắt, model đều nằm ngoài repo, ở `~/Works/tesseract-train/`.

## Máy Ubuntu: cài lần đầu

```bash
git clone <url-repo> ~/Works/tesseract-trainer
cd ~/Works/tesseract-trainer/webapp
./install_ubuntu.sh            # gói hệ thống + .venv (Ubuntu 22.04: thêm --tesseract5)
./install_service.sh 8770      # chạy app nền ở cổng 8770, tự bật lại khi khởi động máy
```

## Máy Ubuntu: cập nhật code

```bash
~/Works/tesseract-trainer/update.sh
```
Lệnh này kéo code mới về rồi khởi động lại app. Nếu app đang xử lý file hoặc đang train thì chỉ kéo code về, chưa
khởi động lại, để việc đang chạy không bị ngắt.

## Việc chạy lâu của vie-ocr-data

Dùng `vod-bg.sh` thay cho `vod.sh` (cùng tham số). Việc chạy dưới systemd nên mất SSH vẫn không dừng:
```bash
cd ~/Works/tesseract-trainer/vie-ocr-data
./vod-bg.sh download --source congbao_pairs
```
