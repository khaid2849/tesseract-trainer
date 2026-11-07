# vie-ocr-data: lấy thật nhiều dữ liệu train Tesseract tiếng Việt

Công cụ dòng lệnh làm theo spec `SPEC.md` (bản gốc: `Nguồn dữ liệu train Tesseract OCR tiếng Việt.md`):
tải các kho văn bản mở → làm sạch → sinh **ảnh dòng giả scan + `.gt.txt`** (định dạng tesstrain). Web app train
tự đọc kết quả này: tab **4. Train**, ô "Số dòng từ kho vie-ocr-data".

## Đọc trước: dữ liệu này giúp được gì

- Có **hàng trăm nghìn đến hàng triệu dòng** nhãn đúng 100%, không tốn công gán nhãn. Dữ liệu này giúp model chắc tay
  hơn với dấu tiếng Việt, chữ IN HOA, nhiều font khác nhau, và không "quên" chữ bình thường.
- Nhưng đây vẫn là **ảnh giả lập**. Lần train thử trước đây cho thấy dữ liệu giả lập **không đủ** để sửa lỗi trên scan
  thật (Mục 47). Dòng scan thật đã duyệt trong web app vẫn là dữ liệu quý nhất, nên dùng kho này **bổ sung**, không
  thay thế. Luôn so kết quả trên bộ đánh giá scan thật ở tab 5.

## Chạy nhanh

```bash
cd tickets/document/feature-document-compare/tesseract-train/vie-ocr-data
./vod.sh verify                    # kiểm tra URL các nguồn (không tải)
./vod.sh download --priority 1     # Wikisource + Wikipedia tiếng Việt, langdata, font Google (≈1,3 GB)
./vod.sh extract                   # trích text sạch (NFC, lọc ký tự, khử trùng)
./vod.sh build-gt --lines 50000    # sinh 50.000 dòng (45.000 train / 5.000 eval)
./vod.sh status
```
Rồi mở web app, tab 4 sẽ hiện số dòng của kho. Muốn sinh lại với số dòng khác thì thêm `--overwrite`.

Dữ liệu nằm ở `~/Works/tesseract-train/vie-ocr-data/` (đổi bằng `VOD_HOME=...` hoặc `--home`; nếu đổi thì chạy web
app với cùng `VOD_HOME`). Trên Ubuntu: chạy `webapp/install_ubuntu.sh` trước, `vod.sh` tự dùng `webapp/.venv`.

## Nguồn (chi tiết + kết quả xác minh 2026-11-07 trong `sources.yaml`)

| Nguồn | Mặc định | Ghi chú |
|---|---|---|
| `congbao_pairs` | ✅ mở | **Nên dùng.** Cặp bản scan (vanban.chinhphu.vn) ↔ bản chữ (Công báo) của cùng văn bản, ghép theo số hiệu → web app tự điền nhãn cho khoảng 72% dòng scan |
| `chinhphu_scan` | ✅ mở | **Scan thật** văn bản Chính phủ/bộ/tỉnh từ vanban.chinhphu.vn (văn bản pháp luật, hành chính: không thuộc đối tượng bảo hộ quyền tác giả, Điều 15 Luật SHTT). Duyệt lùi theo `docid`, chỉ giữ văn bản ≥ 50% trang scan. Không có nhãn → nhập vào web app |
| `congbao` | ✅ mở | Công báo: PDF có lớp chữ, 100–400 trang/số. Vừa cho dòng tự gán nhãn, vừa làm bản chữ để web app tự điền nhãn cho scan |
| `viwikisource` | ✅ mở | **Thêm ngoài spec.** Bộ luật Dân sự, Hiến pháp, nghị định…: sát văn bản hợp đồng/thầu nhất. 39 MB. Trọng số ×2 |
| `viwiki` | ✅ mở | Wikipedia tiếng Việt, 1,17 GB; lấy mẫu 8% số bài rải đều cả dump |
| `google_fonts` | ✅ mở | Be Vietnam Pro, Roboto, Noto Sans/Serif, Source Sans 3, Lora, Merriweather, Montserrat, **Tinos/Arimo** (thay Times New Roman/Arial) |
| `tessdata_best`, `langdata_lstm` | ✅ mở | `langdata_lstm` là chuỗi từ ngẫu nhiên lẫn rác → trích text nhưng **không** dùng khi sinh dòng |
| `leipzig_vi` | ⚠️ `--allow unverified` | 1 triệu câu. Trang giấy phép bị chặn bot (Anubis) nên chưa xác minh được CC BY. Tự mở trang bằng trình duyệt, nếu đúng CC BY thì sửa `license_status: open` |
| `cc100_vi` | ⚠️ `--allow unverified` | 28 GB, mặc định chỉ tải 300 MB đầu. Văn bản web, không ghi giấy phép |
| `vntc` | ⛔ `--allow research` | Bài báo (bản quyền toà soạn) |
| `binhvq_news` | ⛔ đã chết | Ngừng phân phối từ 08/2026 |
| `oscar_vi`, `opus_vi`, `vintext`, `mcocr`, `uit_hwdb`, `cinnamon_hw` | tải tay | Cần đăng nhập/đăng ký, hoặc là ảnh biển hiệu/viết tay (không hợp bài toán). Lệnh `download` chỉ in hướng dẫn |

**Model này dùng cho sản phẩm thương mại**, nên mặc định chỉ dùng nguồn có giấy phép mở. `--allow unverified`
hoặc `--allow research` mở thêm nguồn khác, chỉ dùng khi đã có xác nhận được phép (hỏi tech lead).

### Văn bản Chính phủ: scan thật có sẵn bản chữ (nên dùng)
```bash
./vod.sh download --source congbao_pairs                   # mặc định: 60 số Công báo, 800 trang văn bản
./vod.sh download --source congbao_pairs --max-docs 120 --max-scan-ids 2000   # lấy nhiều hơn (lâu hơn)
```
Cách ghép: đọc mục lục các số Công báo mới nhất (không tải PDF cả số) để biết văn bản nào **đã đăng**. Sau đó duyệt
lùi các trang văn bản trên vanban.chinhphu.vn, mỗi trang chỉ đọc tiêu đề. Văn bản có số hiệu trùng **và** bản trên cổng
là scan thì tải cả bản scan (`scan/`) lẫn PDF riêng của văn bản đó trên Công báo (`ref/`), rồi ghi `pairs.jsonl`.
Chạy lại thì bỏ qua phần đã đọc, nên chạy lại vài tuần một lần để lấy thêm văn bản mới lên Công báo.

Số đo ngày 2026-11-07 (40 số Công báo, 300 trang văn bản, nghỉ 1,5 s giữa các request):

| | |
|---|---|
| Thời gian | 17 phút |
| Kết quả | **52 cặp**: 984 trang scan thật + 965 trang bản chữ (324 MB) |
| Tự điền nhãn (8 cặp, trang thân văn bản) | **72% số dòng**; Nghị định/Thông tư/QĐ quy phạm 95–100%; 319/506 dòng khớp ≥ 97% (duyệt nhanh được) |

Rồi vào web app, tab 2, bấm **"Nhập vào app"**: nhập cả bản scan và bản Công báo, app tự điền nhãn.

Nguồn lẻ (ít dùng): `chinhphu_scan` (chỉ bản scan, `--max-docs`, `--start-id`) và `congbao` (cả số Công báo, mỗi
số 100–400 trang có chữ). Văn bản scan lẻ thường chỉ khớp phần khuôn mẫu, vì văn bản lên Công báo trễ vài tuần.

## Lệnh

| Lệnh | Tham số chính |
|---|---|
| `verify` | Ghi kết quả vào `logs/verify-<thời gian>.json` |
| `download` | `--source a b` · `--priority 1` · `--all` · `--allow unverified research` · `--max-bytes N` (0 = đủ) · `--rate-limit` (byte/giây) · nguồn Chính phủ: `--max-docs N` `--delay 1.5` `--max-file-mb 60` `--start-id` `--max-scan-ids` |
| `extract` | `--source …` (mặc định: mọi nguồn đã tải) · `--max-lines` (mặc định 2.000.000/nguồn; 0 = không giới hạn) |
| `build-gt` | `--lines 50000` · `--weights viwikisource=3 viwiki=1` · `--fonts <thư mục>` · `--upper 0.3` · `--min-char-count 300` · `--eval-ratio 0.1` · `--out` · `--overwrite` |
| `status` | Bảng: đã tải, số dòng text, số dòng ground-truth mỗi nguồn |

Hành vi:
- **Tải**: tải tiếp được khi đứt mạng (HTTP Range), bỏ qua file đã đủ, kiểm SHA-1 của Wikimedia, ghi
  `sha256`/giấy phép/ngày tải vào `manifest.jsonl`. Thử lại tối đa 5 lần (chờ tăng dần). Tải tuần tự, 1 kết nối,
  đúng yêu cầu của Wikimedia. Repo GitHub lớn tải bằng `git sparse-checkout` (API GitHub giới hạn 60 lần/giờ khi
  không đăng nhập).
- **Làm sạch**: NFC, bỏ markup wiki/HTML/URL/email, cắt dòng 10–80 ký tự theo ranh giới từ. **Chỉ giữ dòng 100% ký
  tự hợp lệ** (chữ Việt, số, dấu câu): một ký tự lạ trong nhãn là dạy model sai. Khử trùng lặp.
- **Sinh dòng**: 75% chọn ngẫu nhiên, 25% dành để bù ký tự có dấu hiếm (`ỵ ẵ ẳ ỹ ẻ…`, cả dạng IN HOA) cho đủ
  `--min-char-count` lần. 30% dòng IN HOA. Font xoay vòng (Google Fonts + Times/Arial/Tahoma có trên máy), 25% đậm.
  Ảnh làm giả scan bằng đúng hàm `degrade()` web app đang dùng: 300 DPI, nghiêng, mờ, nhiễu, JPEG, 80% nhị phân.
  Thay `text2image`/`trdg` trong spec để ảnh khớp với đầu vào thật của module.
- Text: `data/text/<nguồn>/part-*.txt`. Ground-truth: `data/ground-truth/{train,eval}/`, kèm `lines.tsv` (dòng
  ↔ nguồn ↔ font) và `stats.json`.

## Số đo trên máy Mac dev (2026-11-07)

| Bước | Kết quả |
|---|---|
| `download --priority 1` (viwiki chỉ 45 MB) | 38 giây |
| `extract` viwikisource | 458.236 dòng, 10 giây |
| `extract` viwiki 60 MB đầu (≈30.000 bài) | ~4.600 bài/giây; bản đủ 1,17 GB ước tính vài phút đến ~10 phút |
| `build-gt --lines 20000` (10 nhân) | 26 giây; chỉ còn `Ỵ ỵ ẵ Ẵ` dưới 300 lần (chữ thật sự hiếm) |
| Train thử web app: 200 vòng, 2.000 dòng kho + 325 dòng PDF + vài chục dòng scan sẵn có | CER dòng PDF đánh giá 2,83% → 2,27%; dòng kho 1,98% → 1,42% (chỉ để thử luồng, chưa phải số đo chất lượng) |

Gợi ý quy mô: 50.000 dòng kho + toàn bộ dòng PDF/scan thật đã duyệt. Mỗi "epoch" của tesstrain ≈ 1 vòng mỗi
dòng, nên 50.000 dòng cần cỡ 50.000–100.000 vòng. Máy Mac dev chạy ~12 vòng/giây, tức khoảng 1–2,5 giờ; nên chạy trên
máy Ubuntu.

## Test

```bash
../../../../../venv/bin/python -m unittest discover -s tests     # hoặc webapp/.venv/bin/python trên Ubuntu
```
Có test chuẩn hoá NFC (spec yêu cầu), lọc URL/ký tự lạ, cắt dòng, gỡ markup wiki, chia hạn mức nguồn.
