# Hướng dẫn chuẩn bị dữ liệu train Tesseract (dùng web app)

## 1. Trả lời ngắn

**Bạn chỉ cần đưa file gốc vào web app.** Bạn không phải tự cắt ảnh hay tự tạo các cặp `<tên>.png` + `<tên>.gt.txt`.
App tự làm việc đó.

Việc duy nhất phải làm tay là **soát chữ cho các dòng cắt từ bản scan**. Lý do: file `.gt.txt` là "đáp án" để
Tesseract học theo, nên phải đúng 100%. Với bản scan, app chỉ có chữ do chính Tesseract đọc ra (còn sai dấu, sai
hoa/thường). Nếu dùng nguyên chữ đó làm đáp án, model sẽ học lại đúng các lỗi nó đang mắc. Vì vậy app điền sẵn chữ máy
đọc, bạn chỉ sửa chỗ sai rồi bấm Enter, không phải gõ lại từ đầu.

| Bạn đưa vào | App tự làm | Bạn phải làm |
|---|---|---|
| **PDF xuất từ Word/Excel** (có lớp chữ, bôi đen copy được chữ) | Cắt từng dòng, làm ảnh giả scan (mờ, nghiêng, nhiễu), lấy chữ gốc trong PDF làm đáp án | **Không gì cả**: đáp án đúng sẵn |
| **PDF scan** (ảnh chụp/quét, không bôi đen được chữ) | Xoay thẳng trang, cắt từng dòng, OCR sẵn chữ để bạn sửa | **Soát và sửa chữ** ở tab "3. Duyệt dòng scan" |
| **Ảnh scan** JPG/PNG/TIFF (TIFF nhiều trang cũng được) | Như PDF scan | Như PDF scan |
| **DOCX** | Lấy chữ làm "corpus" để vẽ thêm dòng giả lập (nhiều font, 30% IN HOA) | Không gì cả |
| **TXT** (danh sách thuật ngữ, câu mẫu…) | Như DOCX | Không gì cả |

App xét **từng trang**: file PDF lẫn trang Word và trang scan (ví dụ phụ lục scan đính kèm) vẫn được xử lý đúng.
PDF scan đã có sẵn lớp chữ OCR ẩn (loại "searchable PDF" từ máy scan) được coi là scan, vì lớp chữ đó do máy đọc nên
không đáng tin.

## 2. Nên gom những file gì

Ưu tiên tài liệu **giống thứ khách đưa vào so sánh nhất**: hồ sơ mời thầu, hợp đồng, bảng thông số kỹ thuật, biên bản,
báo giá. Train trên tài liệu khác lĩnh vực ít tác dụng.

| Loại | Vai trò | Mục tiêu số lượng |
|---|---|---|
| PDF có lớp chữ (xuất từ Word) | Nguồn chính: nhiều dòng, nhãn đúng sẵn, không tốn công | 50–200 tài liệu (≈ 10.000–30.000 dòng) |
| Scan thật dùng để **train** | Ít nhưng quý nhất: dạy model đúng kiểu nhoè/mờ của máy scan thật | 10–20 file (500–2.000 dòng đã duyệt) |
| Scan thật dùng để **đánh giá** | Thước đo model mới có tốt hơn `vie` gốc không | 5–10 file (300–500 dòng đã duyệt) |
| DOCX/TXT | Bù chữ cho dòng giả lập | Tuỳ có; đưa vào thêm không hại |

Mẹo:
- **File Word**: nếu được, Save as PDF rồi upload bản PDF. Upload DOCX thì app chỉ lấy được chữ để vẽ dòng giả lập.
  Từ PDF thì app cắt được dòng thật với đúng font, bảng và bố cục của tài liệu (máy này chưa có LibreOffice để tự chuyển).
- **Scan thật**: chọn đa dạng: có tiêu đề IN HOA, có bảng, scan mờ, scan hơi nghiêng, nhiều máy scan khác nhau.
  Bản scan **đúng như khách sẽ đưa** là tốt nhất.
- **Cách lấy nhiều scan thật có nhãn nhanh nhất: in rồi scan lại file có chữ.** Upload cả bản PDF/Word gốc lẫn bản
  scan. App tự tìm câu tương ứng trong bản gốc và **điền sẵn chữ đúng** cho từng dòng scan (xem mục 2.1).
- **Văn bản Chính phủ** (scan thật, không vướng bản quyền) kèm bản chữ trên **Công báo**: tải bằng
  `vie-ocr-data/vod.sh download --source congbao_pairs`, rồi bấm "Nhập vào app" ở tab 2.
- Không cần tách trang, đổi tên hay xoá trang bìa. Dòng rác (chữ ký, con dấu, kẻ bảng) bạn bỏ lúc duyệt.

### 2.1 Tự điền nhãn cho dòng scan từ bản chữ

Mọi trang có lớp chữ đã tải lên app (PDF xuất từ Word, Công báo, DOCX, TXT) gộp thành một **thư viện bản chữ**. Sau
khi OCR, mỗi dòng scan được tìm câu giống nhất trong thư viện. Vì so khớp sau khi đã bỏ dấu, OCR đọc sai dấu vẫn tìm
ra đúng câu. Câu có độ khớp từ 80% được điền sẵn, kèm nhãn "Khớp bản chữ N%" và dòng "Máy đọc: …" để bạn so.

- Có thêm file mới thì bấm **"Khớp lại với bản chữ"** ở tab 3.
- Nút **"Duyệt các dòng khớp bản chữ"** (mặc định ≥ 97%) duyệt hàng loạt. Đo trên cặp "PDF Word + bản scan của
  nó": ở mức ≥ 97%, **104/104 dòng điền sẵn đúng chữ thật**. Nên lướt vài trang theo "Khớp bản chữ cao trước" trước
  khi bấm.
- Dãy số phải trùng khít (số hiệu, ngày, tiền…). Câu cùng khuôn mẫu nhưng khác số thì không điền, để tránh nhãn sai số.
- Dòng không tìm thấy (chữ ký, số trang, câu không có trong bản chữ) giữ chữ máy đọc để bạn sửa tay như cũ.
- **Cặp văn bản Chính phủ ↔ Công báo** (`vod.sh download --source congbao_pairs`): bản scan trên cổng Chính phủ và
  bản chữ trên Công báo của **cùng một văn bản**, ghép theo số hiệu. Đo trên 8 cặp (trang thân văn bản): **72% số
  dòng được điền**; Nghị định/Thông tư/Quyết định quy phạm đạt 95–100%. Văn bản nhiều bảng biểu khớp ít hơn.
- Văn bản scan tải lẻ (`chinhphu_scan`) mà không có cặp thì chỉ khớp phần khuôn mẫu (quốc hiệu, "Căn cứ…"), vì văn
  bản lên Công báo trễ vài tuần, và văn bản cá biệt không đăng Công báo.
- Lưu ý đánh giá: nếu một bản scan để "Đánh giá" mà bản chữ của nó lại là file "Train", model đã thấy nội dung đó
  (dưới dạng ảnh khác). Mức lẫn này nhẹ, nhưng thước đo sạch nhất vẫn là scan có bản chữ **không** nằm trong Train.

## 3. Chia "Train" và "Đánh giá"

Lúc upload chọn **Train** hoặc **Đánh giá** (đổi lại được trong bảng ở tab 2).

- File "Đánh giá" **không bao giờ** được đưa vào train. App dùng nó để đo model mới so với `vie` gốc.
- Chia **theo tài liệu**, không chia theo dòng: 2 bản scan của cùng 1 hợp đồng phải cùng một phía. Nếu không, model
  "thuộc bài" và số đo đẹp giả.
- Nên có cả 2 loại trong bộ đánh giá: **1–2 PDF có lớp chữ** (để biết model không bị "quên" chữ bình thường) và
  **5–10 scan thật đã duyệt** (thước đo chính).
- Đừng chuyển file "Đánh giá" sang "Train" sau khi đã xem kết quả. Khi đó bạn mất thước đo.
- Dòng scan của file "Đánh giá" cũng phải được duyệt thì mới được tính.

## 4. Quy tắc duyệt dòng scan (tab 3)

Phím tắt: <kbd>Enter</kbd> = duyệt và sang dòng sau · <kbd>Shift</kbd>+<kbd>Enter</kbd> = bỏ dòng ·
<kbd>↑</kbd>/<kbd>↓</kbd> = di chuyển. Chỉ dòng **đã duyệt** được dùng, dòng chưa duyệt bị bỏ qua.

Gõ **đúng từng ký tự nhìn thấy trên ảnh**:
- Đúng dấu, đúng hoa/thường, đúng dấu câu (`;` khác `:`, `,` khác `.`). Đây chính là các lỗi `vie` hay mắc.
- **Không sửa lỗi chính tả** của tài liệu gốc. Ảnh ghi sai thì gõ đúng như chỗ sai đó.
- Ký hiệu đặc biệt trên Mac: `≥` = Option+`.` · `≤` = Option+`,` · `±` = Option+Shift+`=` · `°` = Option+Shift+`8`.
- Phần kẻ bảng, vệt đen, mép giấy lẫn trong ảnh thì **bỏ qua**, chỉ gõ chữ.
- Giữa các từ chỉ 1 dấu cách. App tự chuẩn hoá Unicode (NFC) và dấu cách thừa.

**Bỏ dòng** (Shift+Enter) khi:
- Ảnh không có chữ đọc được: chữ ký, con dấu, logo, chỉ có đường kẻ.
- Dòng bị cắt sai: 2 dòng dính nhau, mất nửa trên/dưới của chữ, chữ bị cắt cụt ở mép.
- Chính bạn cũng không chắc chữ đó là gì (mờ quá). Thà bỏ còn hơn đoán.

Mẹo làm nhanh:
- Để sắp xếp "Máy kém tự tin trước": dòng điểm thấp thường là rác (bỏ nhanh) hoặc sai nhiều. Dòng điểm cao thường
  chỉ sai 1–2 dấu, nhưng **vẫn phải nhìn**: `vie` đọc sai dấu chữ hoa ngay cả khi rất tự tin.
- Nút "Duyệt tất cả dòng chưa duyệt trên trang này" chỉ bấm khi bạn **đã soát hết** 30 dòng đang hiển thị.
- Một nhãn sai trong bộ **đánh giá** làm số đo vô nghĩa. Nếu có 2 người, người thứ 2 nên soát lại ngẫu nhiên khoảng
  10% bộ đánh giá (lọc "Đã duyệt").

## 5. Quy trình trên app

Chạy app:
```bash
/Users/khaid/Works/odoo-18.0/tickets/document/feature-document-compare/tesseract-train/webapp/run.sh
# mở http://127.0.0.1:8765  — giữ cửa sổ Terminal này mở suốt lúc train
```

Train trên **máy Ubuntu**: xem `webapp/README-UBUNTU.md` (cài bằng `install_ubuntu.sh`, mở giao diện qua SSH tunnel).
Giao diện và các bước bên dưới giống hệt.

1. **Môi trường**: lần đầu bấm "Cài đặt tự động". App tải tesstrain, dữ liệu ngôn ngữ tiếng Việt và chép model
   `vie` bản best, mất khoảng 1 phút.
2. **Tải file gốc**: kéo thả file, chọn Train/Đánh giá. App tự xử lý; mỗi trang scan mất vài giây (phải OCR).
3. **Duyệt dòng scan**: soát theo mục 4.
4. **Train**: đặt tên model (mặc định `vie_syntra`) rồi bấm "Bắt đầu train". Máy Mac dev train khoảng 12 vòng/giây:
   10.000 vòng ≈ 15 phút, 30.000 vòng ≈ 45 phút; máy khác nhanh/chậm hơn, tab Train hiện thời gian còn lại thật. Có thể theo dõi biểu đồ lỗi và nhật ký.
   Train xong, app tự xuất model và tự đánh giá nếu đã có file "Đánh giá".
5. **Model & đánh giá**: xem bảng so sánh rồi tải `<tên>.traineddata` (bản best, khoảng 12 MB) hoặc
   `<tên>_fast.traineddata` (khoảng 1,7 MB, nhanh hơn, kém chính xác hơn một chút). Model cũng nằm sẵn ở
   `~/Works/tesseract-train/models/`.

Gợi ý số vòng: chạy thử 1.000 vòng trước để chắc mọi thứ ổn, rồi mới chạy thật với 10.000–30.000 vòng khi dữ liệu
đã nhiều.

## 6. Đọc kết quả, khi nào coi là đạt

- **CER** = tỉ lệ ký tự sai, càng thấp càng tốt. Ô xanh là tốt hơn `vie (gốc)`, ô đỏ là kém hơn.
- Tiêu chí đề xuất (chốt lại với tech lead):
  - Bộ **scan thật**: CER giảm ít nhất 30% tương đối so với `vie (gốc)`, CER IN HOA giảm rõ.
  - Bộ **PDF có lớp chữ**: CER không tăng (model không "quên").
  - Tốc độ (s/dòng) không chậm hơn đáng kể.
- Dòng "Model mới còn hay nhầm" cho biết nên bổ sung dữ liệu kiểu gì. Ví dụ còn nhầm `Ấ→Á` nhiều thì thêm tài liệu
  có nhiều tiêu đề IN HOA.
- Số đo trên bộ đánh giá ít dòng (vài chục) dao động mạnh, chưa nên kết luận. Cần ít nhất vài trăm dòng scan đã duyệt.
- Train chỉ sửa được lỗi **đọc sai chữ**. Lỗi **sót cả dòng, gom nhầm ô bảng** là do bước tách dòng và phải sửa trong
  code module (xem `docs/GHI-CHU-TRAIN.md` mục 0).

Nếu chưa đạt, thử lần lượt: duyệt thêm dòng scan train (nguồn quý nhất), tăng "Hệ số dòng scan thật", tăng số vòng,
thêm PDF đúng lĩnh vực.

## 7. Lưu ý

- Tài liệu khách hàng chỉ nằm trên máy này (`~/Works/tesseract-train/data/`). App chỉ mở ở `127.0.0.1`, máy khác trong
  mạng không truy cập được. Không commit, không đưa lên dịch vụ ngoài khi chưa được duyệt.
- Mỗi lần chỉ chạy 1 việc (xử lý file / train / đánh giá).
- **Dừng train giữa chừng thì lần sau phải train lại từ đầu.** Tắt cửa sổ Terminal cũng làm dừng train.
- Train lại với **cùng tên model** (tick "Ghi đè") sẽ xoá model cũ cùng tên. Muốn giữ để so sánh thì đặt tên mới
  (`vie_syntra_v2`…).
- Xoá một file ở tab 2 sẽ xoá luôn các dòng đã duyệt của file đó.
- Đổi vai trò Train/Đánh giá không phải xử lý lại file; lần train/đánh giá sau sẽ dùng vai trò mới.

## 8. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Tab 1 báo thiếu công cụ | Chạy trong Terminal: `brew install tesseract make git`, rồi bấm "Cài đặt tự động" |
| File báo "Lỗi" ở tab 2 | Đọc dòng lỗi; file hỏng/có mật khẩu thì mở bằng Preview, Export PDF lại rồi upload |
| PDF Word mà app báo toàn trang scan | PDF đó thực chất là ảnh (in ra PDF dạng ảnh). Vẫn dùng được, chỉ là phải duyệt dòng |
| Báo "Chỉ có N dòng train, quá ít" | Thêm file hoặc duyệt thêm dòng scan |
| Train báo lỗi | Mở "Nhật ký" ở tab 4, xem các dòng cuối. Lỗi về `gmake` hay thiếu file thì chạy lại "Cài đặt tự động" |
| Cổng 8765 đã bị dùng | `run.sh 8770` (đổi cổng). Chỉ chạy **1** app một lúc vì các app dùng chung dữ liệu |
