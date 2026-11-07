# Train Tesseract trên máy Ubuntu

Web app giống bản trên Mac: upload file gốc, duyệt dòng scan, train, tải model. Cách chuẩn bị dữ liệu xem
`HUONG-DAN-CHUAN-BI-DU-LIEU.md`.

## 1. Yêu cầu

- **Ubuntu 24.04** (khuyên dùng: `apt` có sẵn Tesseract 5.3.4, cùng đời với server Debian bookworm 5.3).
  Ubuntu 22.04 cũng được, nhưng mặc định chỉ có Tesseract 4.1.1, nên cài thêm bản 5 bằng `--tesseract5` (mục 3).
- Quyền `sudo` (để `apt install`), mạng ra Internet (tải gói, tesstrain, model `vie` bản best).
- RAM từ 4 GB, ổ trống vài GB (dữ liệu dòng + checkpoint). Train chỉ dùng CPU, **không cần GPU**.

## 2. Lấy code về máy Ubuntu

```bash
git clone <url-repo> ~/Works/tesseract-trainer
cd ~/Works/tesseract-trainer/webapp
```
Repo là private, nên máy Ubuntu cần quyền đọc: thêm SSH key của máy này vào GitHub, ưu tiên dạng **deploy key chỉ
đọc** của riêng repo này (`ssh-keygen -t ed25519`, rồi dán `~/.ssh/id_ed25519.pub` vào Settings → Deploy keys).
Repo chỉ có code, không có tài liệu khách hàng hay model.

Máy không lên được GitHub thì dùng gói nén: trên Mac chạy `webapp/make_bundle.sh`, chép file
`dist/tesseract-trainer-<ngày>.tar.gz` sang rồi `tar xzf`. Cách này không dùng được `update.sh`.

## 3. Cài đặt (1 lần)

```bash
./install_ubuntu.sh                 # Ubuntu 24.04
./install_ubuntu.sh --tesseract5    # Ubuntu 22.04: thêm PPA alex-p/tesseract-ocr5 để có Tesseract 5
./install_ubuntu.sh --msfonts       # (tuỳ chọn) font Times New Roman/Arial… của Microsoft, bạn tự đồng ý EULA
```
Script sẽ:
- `apt install tesseract-ocr tesseract-ocr-osd make git curl python3-venv fonts-liberation fonts-dejavu-core fonts-noto-core`.
  Gói `tesseract-ocr` của Ubuntu đã có sẵn công cụ train (`lstmtraining`, `combine_lang_model`…).
- Tạo `webapp/.venv` và cài thư viện Python trong `requirements.txt`. Không đụng Python hệ thống.

Về font: không có font Microsoft thì app dùng Liberation Serif/Sans (cùng kích thước chữ với Times New Roman/Arial),
DejaVu và Noto để vẽ dòng giả lập. `--msfonts` giúp dòng giả lập giống tài liệu thật hơn, nhưng không bắt buộc.

## 4. Chạy app thành service (1 lần)

```bash
./install_service.sh 8770     # cổng tuỳ chọn, mặc định 8765
```
App chạy nền dưới systemd (service của user, không chạy bằng root):
- Mất SSH, tắt máy Mac: app **vẫn chạy**, việc đang xử lý hay đang train không bị ngắt.
- Khởi động lại máy Ubuntu: app tự chạy lại. Việc đang dở thì bấm chạy lại trên web (phần đã xong vẫn còn).
- App lỗi bất ngờ: systemd tự bật lại sau 5 giây.

Lần đầu script hỏi mật khẩu `sudo` để bật `loginctl enable-linger` (cho service của user chạy khi không ai đăng nhập).

| Việc | Lệnh |
|---|---|
| Xem trạng thái | `systemctl --user status tesseract-trainer` |
| Xem log | `journalctl --user -u tesseract-trainer -f` (log từng việc cũng hiện trên web) |
| Dừng / chạy | `systemctl --user stop tesseract-trainer` · `start` |
| Đổi cổng | `./install_service.sh <cổng mới>` |
| Gỡ service | `./install_service.sh --remove` |

Không muốn dùng service thì chạy tay trong `tmux`: `tmux new -s tess` rồi `./run.sh 8770`.

### Cập nhật code

```bash
~/Works/tesseract-trainer/update.sh           # git pull + cài lại thư viện nếu requirements đổi + khởi động lại app
~/Works/tesseract-trainer/update.sh --force   # dừng luôn việc đang chạy để khởi động lại
```
Nếu app đang xử lý file hoặc đang train, `update.sh` chỉ kéo code về và báo lại, **không** khởi động lại. Đợi việc
xong rồi chạy lại `update.sh`.

### Lần đầu vào app
Vào tab **1. Môi trường** bấm **Cài đặt tự động**. App tải tesstrain, dữ liệu ngôn ngữ tiếng Việt và
`vie.traineddata` bản best về `~/Works/tesseract-train/`. Muốn để dữ liệu ở chỗ khác:
`TT_WORK=/data/tesseract-train ./install_service.sh 8770` (biến được ghi vào service).

### Mở giao diện từ máy khác (server không có màn hình)

App mặc định **chỉ** nhận kết nối từ chính máy Ubuntu (`127.0.0.1`), vì app không có đăng nhập mà lại chứa tài liệu
khách hàng. Từ máy Mac của bạn, mở SSH tunnel:
```bash
ssh -N -L 8765:127.0.0.1:8765 user@may-ubuntu
```
Giữ lệnh đó chạy rồi mở **http://127.0.0.1:8765** trên trình duyệt Mac. Mọi thao tác (upload, duyệt, tải model)
đi qua tunnel đã mã hoá.

Không nên đặt `TT_HOST=0.0.0.0` (mở cho cả mạng). Chỉ dùng trong mạng nội bộ tin cậy, có tường lửa chặn
từ ngoài, và tắt app khi xong.

### Thêm thật nhiều dòng train từ kho mở (tuỳ chọn)

Trên máy Ubuntu, sau khi đã chạy `install_ubuntu.sh`:
```bash
cd ../vie-ocr-data
./vod-bg.sh download --priority 1     # chạy nền dưới systemd, mất SSH không dừng
journalctl --user -u 'vod-download-*' -f
./vod-bg.sh extract                   # khi download xong
./vod-bg.sh build-gt --lines 50000
```
`vod-bg.sh` nhận đúng tham số của `vod.sh`. Bị dừng giữa chừng thì chạy lại cùng lệnh: phần đã xong được bỏ qua
(`build-gt` thì thêm `--overwrite`).
Tab 4 của web app sẽ hiện số dòng của "kho vie-ocr-data". Chi tiết ở `vie-ocr-data/README.md`.

## 5. Lấy model về

- Tab **5. Model & đánh giá** → nút **Tải** (qua tunnel thì file tải thẳng về Mac), hoặc
- `scp user@may-ubuntu:~/Works/tesseract-train/models/vie_syntra*.traineddata .`

`.traineddata` không phụ thuộc hệ điều hành: train trên Ubuntu dùng được trên Mac và trên server. Trước khi đưa lên
server vẫn phải chạy thử model trên đúng Docker image của server (`docs/GHI-CHU-TRAIN.md` mục 6).

## 6. Chuyển phần đã duyệt từ Mac sang Ubuntu (nếu có)

Dữ liệu app (file gốc, dòng đã cắt, nhãn đã duyệt) nằm gọn trong `data/` và không chứa đường dẫn tuyệt đối:
```bash
# Trên Mac, tắt app trước
rsync -a ~/Works/tesseract-train/data/ user@may-ubuntu:~/Works/tesseract-train/data/
```
Trên Ubuntu vẫn phải bấm "Cài đặt tự động" một lần. Model đã train trên Mac (`models/`) cũng copy được như vậy.

## 7. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `./run.sh` / `install_service.sh` báo chưa có môi trường Python | Chạy `./install_ubuntu.sh` |
| `install_service.sh` báo cổng đang bị giữ | App cũ chạy bằng `run.sh`/tmux: `pkill -f 'app.py 8770'` rồi chạy lại |
| Web không mở được | `systemctl --user status tesseract-trainer`; lỗi xem `journalctl --user -u tesseract-trainer -n 50` |
| `update.sh` báo `Not possible to fast-forward` | Có file bị sửa tay trên máy Ubuntu: `git status`, rồi `git checkout -- <file>` |
| Tab 1 có dấu `!` ở mục "Tesseract 5.x" | Đang dùng bản 4.x: vẫn train được; nên chạy `./install_ubuntu.sh --tesseract5` |
| Tab 1 báo thiếu font có dấu tiếng Việt | `sudo apt install fonts-liberation fonts-dejavu-core` rồi khởi động lại app |
| `Address already in use` | Đã có app chạy (service hoặc tmux) hoặc cổng bị chiếm: dùng cổng khác (tunnel đổi theo) |
| Tải về lỗi ở bước "Cài đặt tự động" | Máy không ra được GitHub: kiểm tra proxy/tường lửa (`curl -I https://github.com`) |
| Việc bị dừng khi đóng SSH | Đang chạy bằng `run.sh`/`vod.sh` thẳng trong SSH: dùng `install_service.sh` và `vod-bg.sh`. Dữ liệu và nhãn vẫn còn |
