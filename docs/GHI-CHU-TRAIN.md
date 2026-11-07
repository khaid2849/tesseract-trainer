# Hướng dẫn train Tesseract tiếng Việt cho so sánh PDF scan (`syntra_document_compare`)

Mục tiêu: fine-tune model `vie` của Tesseract để **đọc đúng chữ trên scan tài liệu thầu/hợp đồng**, từ đó tab Thay đổi
ít chỗ sửa giả và tab Toàn văn ít tô thừa. Code dùng model nằm ở branch `feature/feature_document_compare_tesseract`
(`utils/ocr_tesseract.py`, `redline.word_redline`).

> **Cách nhanh:** dùng web app `webapp/run.sh` (http://127.0.0.1:8765). App tự làm các bước 1–5 dưới đây: chỉ cần upload
> file gốc và soát chữ dòng scan. Xem `HUONG-DAN-CHUAN-BI-DU-LIEU.md`. Các lệnh dưới đây vẫn dùng được khi cần chạy tay.

Thư mục này (ngoài git):

| File | Dùng để |
|---|---|
| `webapp/` | Web app train (Werkzeug; Mac dùng venv Odoo, Ubuntu dùng `.venv` do `install_ubuntu.sh` tạo); dữ liệu ở `~/Works/tesseract-train/{data,models}` |
| `vie-ocr-data/` | Tải + làm sạch Wikipedia/Wikisource… và sinh hàng chục nghìn dòng giả scan (`vod.sh`); web app tự đọc. Xem `vie-ocr-data/README.md` |
| `webapp/README-UBUNTU.md`, `webapp/make_bundle.sh` | Train trên máy Ubuntu; đóng gói code ra `dist/tesseract-trainer-<ngày>.tar.gz` để copy sang |
| `HUONG-DAN-CHUAN-BI-DU-LIEU.md` | Chuẩn bị file gốc, chia Train/Đánh giá, quy tắc duyệt dòng scan |
| `make_gt.py` | Tạo dữ liệu train: `corpus` (gom chữ), `pdf` (cắt dòng từ PDF có lớp chữ), `text` (vẽ dòng từ corpus) |
| `crop_for_labeling.py` | Cắt dòng từ **scan thật** để gán nhãn tay (bộ đánh giá + dữ liệu train quý nhất) |
| `eval_lines.py` | Đo CER/WER theo dòng, liệt kê ký tự hay nhầm, so nhiều model |
| `eval_compare.py` + `pairs.tsv` | Đo đúng thứ module cần: bắt được bao nhiêu chỗ sửa, tô thừa bao nhiêu từ |

Mọi script chạy bằng venv Odoo (`/Users/khaid/Works/odoo-18.0/venv/bin/python`), không cần cài thêm gói.

---

## 0. Train sửa được gì, không sửa được gì

Tesseract làm 2 việc: **tách trang thành dòng** (layout) rồi **đọc từng dòng** (model LSTM). Fine-tune chỉ cải thiện
việc thứ hai.

| Lỗi đang gặp (Mục 47, 14/15) | Train có sửa không |
|---|---|
| Dấu chữ hoa: `CẦU→CÀU`, `Ấ→Á`, `Ế→É/Ề`, `Ồ→Ô/Ò`; chữ thường `ổ→ồ`, `ể→ề`; `;→:`, `,→.` | **Có**, đúng mục tiêu |
| Cùng 1 chữ ở 2 bản scan đọc khác nhau → tô thừa | Giảm nhiều (model chắc tay hơn) |
| Sót cả dòng (dòng "giao hàng ≤ 90 ngày"), mất số cột STT, gom nhầm khối trong bảng | **Không**: là lỗi tách dòng, phải sửa trong `ocr_tesseract.py` (xoá kẻ bảng, OCR theo ô…) — việc riêng |

Vì vậy luôn đo cả 2 chỉ số: CER theo dòng (đo model) và `eval_compare` (đo kết quả so sánh thật).

### Baseline đã đo (model `vie` tessdata_best, 2026-11-06)

| Bộ đo | Kết quả |
|---|---|
| 150 dòng cắt từ PDF HĐ Pendant (làm giả scan) | CER 3,02%, WER 8,21%, dòng đúng 56,7%, **CER IN HOA 5,12%** |
| 150 dòng vẽ từ corpus | CER 2,58%, CER IN HOA 3,14% |
| `eval_compare` Mục 47 (scan thật) | bắt 9/10 chỗ sửa, **tô thừa 191 từ** |
| `eval_compare` 14/15-scan | bắt 35/38, tô thừa 6 từ |

Ký tự hay nhầm nhất: `;→:`, `ổ→ồ`, `,→.`, `ổ→ô`, `ả→a`, `Ấ→Á`, `ồ→ò`, `Ê→Ề`, `Ế→É`, `Ầ→À`, `Đ→D`.

---

## 1. Chuẩn bị máy (làm 1 lần)

```bash
brew install tesseract make          # đã cài trên máy này; make = GNU Make 4.4 (lệnh `gmake`)
tesseract --version                  # 5.5.x; có sẵn lstmtraining, lstmeval, combine_tessdata, text2image
tesseract --list-langs               # phải có vie (đã tải bản tessdata_best vào /opt/homebrew/share/tessdata)
```

`vie.traineddata` làm điểm xuất phát **phải là bản `tessdata_best`** (số thực). Bản `tessdata_fast` hoặc
`tessdata` mặc định không fine-tune được. Nếu thiếu:
```bash
curl -L -o /opt/homebrew/share/tessdata/vie.traineddata \
  https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata
```

Thư mục làm việc (ngoài repo, vì chứa tài liệu khách hàng):
```bash
mkdir -p ~/Works/tesseract-train/{sources/digital,sources/scan-real,gt,eval,models}
cd ~/Works/tesseract-train
git clone --depth 1 https://github.com/tesseract-ocr/tesstrain.git
```

Chỉ tải **phần ngôn ngữ tiếng Việt** (không chạy `make tesseract-langdata`, lệnh đó tải unicharset của hơn 30 hệ chữ):
```bash
cd ~/Works/tesseract-train/tesstrain
L=data/langdata; B=https://github.com/tesseract-ocr/langdata_lstm/raw/main
mkdir -p $L data/vie_syntra
for f in radical-stroke.txt Latin.unicharset vie/vie.wordlist vie/vie.punc vie/vie.numbers; do
  curl -fsSL -o $L/$(basename $f) $B/$f
done
# Từ điển / dấu câu / mẫu số tiếng Việt → đúng tên tesstrain đọc khi dựng model
for e in wordlist punc numbers; do cp $L/vie.$e data/vie_syntra/vie_syntra.$e; done
```
- `radical-stroke.txt`: `combine_lang_model` bắt buộc phải có (kể cả với chữ Latin).
- `Latin.unicharset`: thuộc tính ký tự của hệ chữ Latin (tiếng Việt thuộc hệ này).
- `vie.wordlist` (7.334 từ), `vie.punc`, `vie.numbers`: từ điển và mẫu dấu câu/số mà Tesseract dùng khi đoán chữ.
  Có thể bổ sung từ chuyên ngành (thuật ngữ thầu, y tế, đơn vị) vào `data/vie_syntra/vie_syntra.wordlist`.

Biến dùng xuyên suốt:
```bash
export TT=~/Works/tesseract-train
export KIT=/Users/khaid/Works/odoo-18.0/tickets/document/feature-document-compare/tesseract-train
export PY=/Users/khaid/Works/odoo-18.0/venv/bin/python
```

Code module: checkout branch `feature/feature_document_compare_tesseract`, hoặc để nguyên thư mục đang làm và tạo
worktree riêng rồi truyền `--addons <worktree>` cho `eval_compare.py`:
```bash
cd /Users/khaid/Works/odoo-18.0/onprem-odoo-erp
git worktree add $TT/code feature/feature_document_compare_tesseract
```

---

## 2. Bước 1 — Dựng bộ đánh giá TRƯỚC (không bao giờ train trên nó)

### 2.1 Dòng scan thật, gán nhãn tay (`$TT/eval/real`) — quan trọng nhất
Chọn 5–10 file **scan thật** (in ra rồi quét, không phải file render), đa dạng: hợp đồng, bảng thông số, trang có tiêu
đề IN HOA, scan mờ/nghiêng. Mục tiêu **300–500 dòng**.
```bash
$PY $KIT/crop_for_labeling.py "$TT/sources/scan-real/"*.pdf -o $TT/eval/real
open $TT/eval/real/review.html          # xem ảnh ↔ chữ Tesseract đọc
```
Sau đó **sửa từng file `.gt.txt`** cho đúng tuyệt đối với ảnh. Quy tắc gán nhãn:
- Gõ đúng từng ký tự nhìn thấy: dấu, hoa/thường, `≥ ≤ ± ° %`, dấu câu. Không sửa lỗi chính tả của tài liệu gốc.
- Unicode dựng sẵn (NFC) — gõ bằng Unikey/bộ gõ macOS bình thường là đúng.
- Dòng rác (kẻ bảng, chữ ký, con dấu, số trang mờ) → xoá cả `.png` và `.gt.txt`.
- Dòng bị cắt sai (2 dòng dính nhau, mất nửa chữ) → xoá.
- Mỗi file 1 dòng, không xuống dòng thừa.

Mẹo: chia việc cho 2 người, người thứ 2 soát lại 10% ngẫu nhiên. Nhãn sai trong bộ đánh giá làm số đo vô nghĩa.

### 2.2 Dòng từ tài liệu digital không dùng để train (`$TT/eval/synth`)
2–3 PDF có lớp chữ **khác** với tài liệu dùng train:
```bash
$PY $KIT/make_gt.py pdf eval_doc1.pdf eval_doc2.pdf -o $TT/eval/synth --seed 99
```
Bộ này để phát hiện model "quên" (CER tăng trên tài liệu bình thường).

### 2.3 Cặp so sánh có đáp án (`pairs.tsv`)
Mỗi dòng: `bản gốc <TAB> bản sửa đổi <TAB> từ bị sửa ở bản gốc <TAB> từ mới ở bản sửa đổi` (từ cách nhau dấu cách,
bỏ dấu câu đầu/cuối từ như module, ví dụ `30%` → `30`). Đã có Mục 47 và 14/15. Nên thêm 3–5 cặp scan thật có chỗ sửa
đã biết. Viết đáp án dễ hơn khi chạy với `--show` để xem các từ đang bị tô.

### 2.4 Chạy baseline, ghi lại số
```bash
cd /Users/khaid/Works/odoo-18.0
$PY $KIT/eval_lines.py $TT/eval/real  -l vie
$PY $KIT/eval_lines.py $TT/eval/synth -l vie
PYTHONPATH=$PWD $PY $KIT/eval_compare.py $KIT/pairs.tsv -l vie --addons $TT/code
```
(`eval_compare.py` phải chạy từ `/Users/khaid/Works/odoo-18.0` vì đọc `vina-dev-conf.conf`; không đụng DB.)

---

## 3. Bước 2 — Tạo dữ liệu train (`$TT/gt/...`)

tesstrain cần 1 thư mục phẳng gồm các cặp `<tên>.png` + `<tên>.gt.txt` (1 dòng chữ mỗi cặp). Ảnh do `make_gt.py` tạo
đã giống đầu vào thật của module: 300 DPI, nghiêng nhẹ, mờ, mực đậm/nhạt, nhiễu, nén JPEG, 80% nhị phân Otsu
(`ocr_tesseract.py` luôn nhị phân trước khi đọc).

### Nguồn A — PDF/DOCX digital đúng lĩnh vực (chính, nhãn đúng 100%)
Hồ sơ mời thầu, hợp đồng, bảng thông số kỹ thuật, biên bản… **càng giống tài liệu khách so sánh càng tốt**. File Word
phải chuyển sang PDF trước (Word → Save as PDF, hoặc `soffice --headless --convert-to pdf *.docx` nếu cài LibreOffice).
```bash
$PY $KIT/make_gt.py pdf "$TT/sources/digital/"*.pdf -o $TT/gt/digital --seed 1
$PY $KIT/make_gt.py pdf "$TT/sources/digital/"*.pdf -o $TT/gt/digital2 --seed 2   # lần 2: mức nhiễu/DPI khác
```
Chỉ lấy được dòng nằm ngang trong PDF có lớp chữ (PDF scan thì không có gì). Mục tiêu 10.000–30.000 dòng (~50–200 tài
liệu).

### Nguồn B — Vẽ dòng từ corpus (bù chữ IN HOA và font đa dạng)
```bash
$PY $KIT/make_gt.py corpus "$TT/sources/digital/"*.pdf "$TT/sources/digital/"*.docx -o $TT/corpus.txt
$PY $KIT/make_gt.py text $TT/corpus.txt -o $TT/gt/text -n 8000
```
30% dòng được chuyển IN HOA (`P_UPPER` trong script) vì đây là điểm yếu nhất của `vie`. Font lấy từ máy: Times New
Roman, Arial, Tahoma, Verdana, Georgia (thường, đậm, nghiêng). Nếu có Calibri/Cambria (cài Office) script tự dùng.

### Nguồn C — Scan thật đã gán nhãn (ít nhưng giá trị nhất)
Làm giống mục 2.1 nhưng với **file khác** bộ đánh giá → `$TT/gt/real`. 500–2.000 dòng. Có thể chép 2 lần (đổi tên)
để tăng trọng số so với dữ liệu giả lập.

### Gom lại
Tỉ lệ đề xuất: A ~60%, B ~25%, C ~15%.
```bash
mkdir -p $TT/tesstrain/data/vie_syntra-ground-truth
cp $TT/gt/*/*.png $TT/gt/*/*.gt.txt $TT/tesstrain/data/vie_syntra-ground-truth/
ls $TT/tesstrain/data/vie_syntra-ground-truth/*.gt.txt | wc -l
```
Tên file phải khác nhau giữa các nguồn (script đã đặt tiền tố theo tên tài liệu / `syn_`). Không chép bộ đánh giá vào
đây.

---

## 4. Bước 3 — Fine-tune

```bash
cd $TT/tesstrain
gmake training \
  MODEL_NAME=vie_syntra \
  START_MODEL=vie \
  TESSDATA=/opt/homebrew/share/tessdata \
  PY_CMD=/Users/khaid/Works/odoo-18.0/venv/bin/python \
  TESSERACT_LANGDATA="data/langdata/radical-stroke.txt data/langdata/Latin.unicharset" \
  MAX_ITERATIONS=10000 \
  RATIO_TRAIN=0.95
```
- **`gmake`, không phải `make`**: `make` của macOS là 3.81, tesstrain báo "GNU Make is too low" và dừng.
- `TESSERACT_LANGDATA=...`: chỉ dùng 2 file langdata đã tải, nếu không tesstrain đòi tải đủ hơn 30 hệ chữ.
- `PY_CMD`: venv Odoo đã có Pillow, đủ cho `generate_line_box.py`; không cần venv riêng.
- `START_MODEL=vie`: fine-tune từ model sẵn có (learning rate mặc định 0.0001 khi có START_MODEL). Không train từ đầu:
  cần hàng trăm nghìn dòng và nhiều ngày.
- `PSM` mặc định 13 (dòng thô) là đúng cho ảnh 1 dòng.
- tesstrain tự tách 5% dữ liệu làm eval nội bộ (`list.eval`), tự tạo box file (`generate_line_box.py`), unicharset,
  file `.lstmf`.
- **Chạy thử trước** với `MAX_ITERATIONS=300` và ~500 dòng. Đã chạy trên máy này (2026-11-06): 625 dòng, 300 vòng
  → **59 giây** tổng cộng (gồm dựng file `.lstmf`), BCER train 6,9% → 5,4%. Cảnh báo
  `Failed to read data from: data/langdata/vie_syntra/vie_syntra.config` là vô hại.
- **Không cần GPU**: `lstmtraining` chỉ chạy CPU, và bản brew chạy **1 nhân** (đo: 1.000 vòng = 80 s, user ≈ real,
  RAM ~430 MB). Ước lượng ~12 vòng/giây → 10.000 vòng ≈ 14 phút, 100.000 vòng ≈ 2,3 giờ (dòng dài thì chậm hơn).
  Máy 10 nhân chạy song song được nhiều thử nghiệm (đổi `MODEL_NAME`). `gmake -j8 training …` chỉ tăng tốc bước
  dựng `.lstmf`.
- Theo dõi: `tail -f data/vie_syntra/training.log` — dòng `At iteration ... BCER train=x%` (lỗi ký tự trên tập train)
  và các lần `Eval Char error rate` (trên `list.eval`). Train giảm mà eval tăng → học vẹt, dừng sớm.
- Ngắt giữa chừng không sao: chạy lại đúng lệnh trên sẽ train tiếp từ checkpoint `data/vie_syntra/checkpoints/`.
- Muốn tăng số vòng: đổi `MAX_ITERATIONS` (vd 20000) rồi chạy lại.

Xuất model:
```bash
ls data/vie_syntra.traineddata          # model cuối (số thực, "best")
gmake traineddata MODEL_NAME=vie_syntra START_MODEL=vie TESSDATA=/opt/homebrew/share/tessdata \
  TESSERACT_LANGDATA="data/langdata/radical-stroke.txt data/langdata/Latin.unicharset"
# mỗi checkpoint → data/vie_syntra/tessdata_best/ (~12 MB) và tessdata_fast/ (~1,7 MB)
```
`tessdata_fast` (số nguyên) nhỏ và nhanh hơn, chính xác kém hơn một chút. Đo cả 2 rồi chọn.

Nếu kết quả chưa tốt, thử lần lượt: thêm dữ liệu nguồn C, tăng số vòng, chỉnh mức nhiễu trong `degrade()` cho giống
scan thật hơn (so ảnh `$TT/eval/real/*.png` với ảnh trong `gt/`).

---

## 5. Bước 4 — Đánh giá model mới

Gom các model cần so vào 1 thư mục riêng (không đụng `/opt/homebrew/share/tessdata`):
```bash
M=$TT/models; mkdir -p $M
cp /opt/homebrew/share/tessdata/{vie,osd}.traineddata $M/
cp $TT/tesstrain/data/vie_syntra.traineddata $M/
cp $TT/tesstrain/data/vie_syntra/tessdata_fast/<checkpoint tốt nhất>.traineddata $M/vie_syntra_fast.traineddata
cd /Users/khaid/Works/odoo-18.0
$PY $KIT/eval_lines.py $TT/eval/real  -l vie vie_syntra vie_syntra_fast --tessdata-dir $M
$PY $KIT/eval_lines.py $TT/eval/synth -l vie vie_syntra vie_syntra_fast --tessdata-dir $M
PYTHONPATH=$PWD $PY $KIT/eval_compare.py $KIT/pairs.tsv -l vie vie_syntra --tessdata-dir $M --addons $TT/code
```

### Kết quả lần chạy thử (2026-11-06) — đọc kỹ trước khi train thật
Train 625 dòng **giả lập** (325 dòng cắt từ PDF HĐ Pendant 23/10 + 300 dòng vẽ từ corpus của chính HĐ đó), 300 vòng:

| | `vie` | `vie_syntra` (best) | `vie_syntra_fast` |
|---|---|---|---|
| 331 dòng cắt từ HĐ Pendant bản 29/10 (không train) | CER 2,60%, IN HOA 3,88%, dòng đúng 49,8% | **CER 1,78%**, IN HOA 2,26%, dòng đúng 71,0% | CER 1,95%, IN HOA 2,53% |
| `eval_compare` Mục 47 + 14/15 (scan) | bắt 44/48, tô thừa 197 từ | bắt 44/48, tô thừa **209** từ | tô thừa 207 từ |
| Tốc độ | 0,09 s/dòng | 0,09 s/dòng | 0,07 s/dòng |

- Cải thiện 32% CER chỉ trên tài liệu **gần như trùng** dữ liệu train (bản sửa của cùng hợp đồng) → con số lạc quan.
- Trên scan thật (Mục 47) **không tốt lên, tô thừa còn tăng nhẹ**: ảnh giả lập chưa giống scan thật và chỉ có 1 hợp
  đồng. Vì vậy bộ đánh giá scan thật (mục 2.1) và dữ liệu scan thật (nguồn C) là bắt buộc, và chỉ chấp nhận model
  khi `eval/real` + `eval_compare` tốt lên.
- `fast` kém `best` chút ít (CER 1,95% vs 1,78%), nhanh hơn ~20%, nhỏ hơn 7 lần.

Tiêu chí đề xuất để coi là đạt (chốt lại với tech lead):
- `eval/real`: CER giảm ít nhất 30% tương đối so với `vie`; CER IN HOA giảm rõ.
- `eval/synth`: không tăng (không "quên").
- `eval_compare`: số chỗ bắt được **không giảm**, số từ tô thừa giảm rõ.
- Tốc độ (`s/dòng`) không chậm hơn đáng kể.

Ghi kết quả từng lần train (dữ liệu, số vòng, số đo) vào `tesseract-trial.md` của ticket.

---

## 6. Bước 5 — Đưa model vào module (cần sửa code, chưa làm)

Hiện `ocr_tesseract.LANG = 'vie'` cố định. Đề xuất (làm trên branch Tesseract khi model đạt):
1. Đóng gói model trong module, giống `salely_ocr/utils/models_vi/vi_rec.onnx`:
   `syntra_document_compare/utils/tessdata/vie_syntra.traineddata` (bản fast vài MB, bản best khoảng 10–15 MB).
2. `ocr_tesseract.py`: dùng `-l vie_syntra --tessdata-dir <thư mục trên>` khi file có mặt, không có thì về `vie`
   hệ thống.
3. Server: Docker image cài `tesseract-ocr` (Debian bookworm là bản 5.3; model LSTM thường dùng chéo được giữa các bản
   4.1+/5.x nhưng **phải thử** model train bằng 5.5 trên đúng image) và `pytesseract`;
   **không cần** `tesseract-ocr-vie` nếu model đã đóng gói. Thêm `pytesseract` vào requirements.
4. Test local trên giao diện (tham số `syntra_document_compare.ocr_engine=tesseract`) rồi mới đề xuất lên staging.

---

## 7. Lưu ý dữ liệu

- Tài liệu khách hàng (kể cả file trong các bản so sánh trên DB) chỉ để trong `~/Works/tesseract-train`, **không commit,
  không đưa lên Colab/dịch vụ ngoài** khi chưa được duyệt.
- Model `.traineddata` không chứa nguyên văn tài liệu nhưng có học từ đó; đóng gói vào module là quyết định cần duyệt.

## 8. Thứ tự việc và công sức (ước lượng công người)

| Việc | Công |
|---|---|
| Chuẩn bị máy + chạy thử train 300 vòng | 0,5 ngày |
| Gom 50–200 tài liệu digital + 10–20 scan thật | 1–2 ngày (tuỳ có sẵn) |
| Gán nhãn 300–500 dòng đánh giá + 500–2.000 dòng train | 1–3 ngày (chưa đo; đo tốc độ gán nhãn ở 50 dòng đầu rồi tính lại) |
| Train + đánh giá 2–3 vòng | 1–2 ngày (máy chạy là chính) |
| Sửa module dùng model + test giao diện | 0,5–1 ngày |
