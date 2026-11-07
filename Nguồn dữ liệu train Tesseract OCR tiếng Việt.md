### A. Tài nguyên chính thức của Tesseract

| P | ID | Nguồn | Nội dung cần lấy | Cách tải | Giấy phép |
| --- | --- | --- | --- | --- | --- |
| 1 | `tessdata_best` | https://github.com/tesseract-ocr/tessdata\_best | Chỉ file `vie.traineddata` (model gốc để fine-tune) | HTTP GET raw file, không clone cả repo (rất nặng) | Apache 2.0 |
| 1 | `langdata_lstm` | https://github.com/tesseract-ocr/langdata\_lstm | Thư mục `vie/` (training\_text, wordlist, unicharset…) và các file dùng chung ở gốc (`radical-stroke.txt`, `common.punc`…) | Sparse checkout hoặc GitHub API liệt kê file rồi tải raw | Apache 2.0 |
| 1 | `tesstrain` | https://github.com/tesseract-ocr/tesstrain | Makefile train, không phải dữ liệu | `git clone --depth 1` | Apache 2.0 |
| 2 | `langdata` | https://github.com/tesseract-ocr/langdata | Thư mục `vie/` bản cũ, dùng đối chiếu | Giống `langdata_lstm` | Apache 2.0 |

### B. Kho văn bản thuần (để sinh ảnh tổng hợp)

| P | ID | Nguồn | Nội dung | Cách tải | Dung lượng | Giấy phép |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `viwiki` | https://dumps.wikimedia.org/viwiki/latest/ | Dump bài viết Wikipedia tiếng Việt (`viwiki-latest-pages-articles.xml.bz2`) | HTTP tải file `.bz2`, kiểm tra checksum từ `*-sha1sums.txt`, giải nén bằng `wikiextractor` | \~1–2 GB nén | CC BY-SA 4.0 |
| 1 | `vntc` | https://github.com/duyvuleo/VNTC | Tin tức tiếng Việt chia theo chủ đề | `git clone`, file dữ liệu nằm trong repo (có thể là file nén `.rar`) | \~100–200 MB | Theo README repo, dùng cho nghiên cứu |
| 2 | `binhvq_news` | https://github.com/binhvq/news-corpus | Kho tin tức rất lớn đã crawl sẵn | README trỏ tới link Google Drive / host ngoài; dùng `gdown` hoặc tải thủ công | Vài chục GB | Theo README repo |
| 2 | `cc100_vi` | https://data.statmt.org/cc-100/ | File `vi.txt.xz` (dữ liệu web CommonCrawl) | HTTP tải trực tiếp, hỗ trợ resume | \~30–50 GB nén, nên chỉ đọc một phần theo stream | Theo điều khoản CommonCrawl |
| 2 | `leipzig_vi` | https://wortschatz.uni-leipzig.de/en/download/Vietnamese | Bộ câu tiếng Việt đã tách sẵn (news, web, wiki; các cỡ 10K–1M câu) | Trang download liệt kê file `.tar.gz`, parse HTML lấy link | Vài MB – vài trăm MB | CC BY 4.0 |
| 3 | `oscar_vi` | https://huggingface.co/datasets/oscar-corpus | Phần tiếng Việt của OSCAR | `huggingface_hub`/`datasets`, cần đăng nhập HF và chấp nhận điều khoản | Rất lớn | Theo điều khoản OSCAR |
| 3 | `opus_vi` | https://opus.nlpl.eu | Corpus song ngữ, lấy phía tiếng Việt (vd. OpenSubtitles, TED) | API OPUS hoặc tải file moses `.zip` | Tùy bộ | Tùy bộ |

### C. Bộ ảnh OCR tiếng Việt có nhãn sẵn

| P | ID | Nguồn | Loại ảnh | Cách tải | Ghi chú |
| --- | --- | --- | --- | --- | --- |
| 2 | `vintext` | https://github.com/VinAIResearch/dict-guided | Chữ trong ảnh cảnh thực (biển hiệu) | README trỏ link Google Drive → `gdown` | Nhãn ở mức từ + bounding box, cần cắt ảnh theo box. Giấy phép nghiên cứu |
| 3 | `mcocr` | Cuộc thi MC-OCR, RIVF 2021 | Hóa đơn, biên lai | Tìm link chính thức của cuộc thi, có thể cần đăng ký | Chỉ một số trường có nhãn text |
| 3 | `uit_hwdb` | UIT, ĐHQG TP.HCM | Chữ viết tay | Thường phải gửi yêu cầu/đăng ký → không tự động hóa, chỉ ghi chú hướng dẫn | Chỉ dùng nếu cần OCR viết tay |
| 3 | `cinnamon_hw` | Cinnamon AI Marathon | Chữ viết tay (địa chỉ) | Xác minh link còn sống; có thể đã gỡ | Chỉ dùng nếu cần OCR viết tay |
