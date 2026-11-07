"""Tạo dữ liệu train Tesseract (định dạng tesstrain: <tên>.png + <tên>.gt.txt, mỗi file 1 dòng chữ).

3 lệnh con:
  corpus  <pdf/docx...> -o corpus.txt        gom chữ từ PDF có lớp chữ / DOCX → corpus (mỗi dòng 1 câu/ô)
  pdf     <pdf...> -o <thư mục gt>           cắt từng dòng từ PDF có lớp chữ: nhãn đúng 100%, ảnh làm giả scan
  text    corpus.txt -o <thư mục gt> -n N    vẽ N dòng từ corpus bằng font hệ thống (tăng chữ IN HOA có dấu)

Ảnh được làm giống đầu vào thật của module (utils/ocr_tesseract.py): trang scan render 300 DPI rồi nhị phân Otsu.
Chạy bằng venv Odoo:  ../../../../venv/bin/python make_gt.py ...
"""
import argparse
import glob
import os
import random
import re
import unicodedata

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

TARGET_DPI = 300           # khớp ocr_tesseract.ZOOM
SCAN_DPI = (150, 300)      # độ phân giải "máy scan" giả lập trước khi phóng lên 300 DPI
P_BINARY = 0.8             # tỉ lệ ảnh nhị phân Otsu (module luôn nhị phân trước khi OCR)
P_UPPER = 0.3              # tỉ lệ dòng IN HOA ở lệnh text (điểm yếu lớn nhất của vie gốc)
MIN_CHARS = 2
FONT_DIRS = ['/System/Library/Fonts/Supplemental', '/Library/Fonts', os.path.expanduser('~/Library/Fonts'),  # macOS
             '/usr/share/fonts', '/usr/local/share/fonts', os.path.expanduser('~/.local/share/fonts'),  # Linux
             os.path.expanduser('~/.fonts')]
# Linux: msttcorefonts đặt tên "Times_New_Roman.ttf"; Liberation/DejaVu/Noto thay thế khi không có font MS
FONT_NAMES = ['Times New Roman', 'Arial', 'Tahoma', 'Verdana', 'Georgia', 'Calibri', 'Cambria',
              'LiberationSerif', 'LiberationSans-', 'DejaVuSerif', 'DejaVuSans', 'NotoSerif-', 'NotoSans-']
FONT_SKIP = ('Black', 'Narrow', 'Mono', 'Condensed', 'ExtraLight', 'Thin')
VI_PROBE = 'ộệớưđăơẦỨẶ'


def norm(text):
    text = unicodedata.normalize('NFC', text).replace(' ', ' ').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()


# ---------------------------------------------------------------- corpus
def corpus_cmd(args):
    seen, out = set(), []
    for path in args.inputs:
        lines = _docx_lines(path) if path.lower().endswith('.docx') else _pdf_lines_text(path)
        for line in lines:
            line = norm(line)
            if len(line) >= MIN_CHARS and line not in seen:
                seen.add(line)
                out.append(line)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    print(f'{len(out)} dòng → {args.output}')


def _docx_lines(path):
    import docx
    document = docx.Document(path)
    for paragraph in document.paragraphs:
        yield paragraph.text
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.text.split('\n')


def _pdf_lines_text(path):
    for page in pymupdf.open(path):
        for text, _bbox in _page_lines(page):
            yield text


# ---------------------------------------------------------------- pdf
def _page_lines(page):
    """[(text, bbox in unrotated page coordinates)] of horizontal text lines."""
    out = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            if abs(line['dir'][1]) > 0.01:
                continue
            text = norm(''.join(span['text'] for span in line['spans']))
            if len(text) >= MIN_CHARS:
                out.append((text, pymupdf.Rect(line['bbox'])))
    return out


def page_samples(page, rng):
    """Yield (index, degraded line image, text) for each horizontal text line of a PDF page with a text layer."""
    lines = _page_lines(page)
    if not lines:
        return
    dpi = rng.randint(*SCAN_DPI)
    zoom = dpi / 72
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width)
    for index, (text, rect) in enumerate(lines):
        rect = rect * page.rotation_matrix * pymupdf.Matrix(zoom, zoom)
        pad = rng.randint(2, 6) * dpi / 150
        x0, y0 = max(int(rect.x0 - pad), 0), max(int(rect.y0 - pad), 0)
        x1, y1 = min(int(rect.x1 + pad), gray.shape[1]), min(int(rect.y1 + pad), gray.shape[0])
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        crop = cv2.resize(gray[y0:y1, x0:x1], None, fx=TARGET_DPI / dpi, fy=TARGET_DPI / dpi,
                          interpolation=cv2.INTER_CUBIC)
        yield index, degrade(crop, rng), text


def pdf_cmd(args):
    os.makedirs(args.output, exist_ok=True)
    rng = random.Random(args.seed)
    count = 0
    for path in args.inputs:
        stem = re.sub(r'\W+', '_', os.path.splitext(os.path.basename(path))[0])[:40]
        document = pymupdf.open(path)
        for page in document:
            for index, image, text in page_samples(page, rng):
                _save(args.output, f'{stem}_p{page.number + 1}_{index:03d}', image, text)
                count += 1
    print(f'{count} dòng → {args.output}')


# ---------------------------------------------------------------- text
def _fonts():
    found = {}
    for directory in FONT_DIRS:
        for path in glob.glob(os.path.join(directory, '**', '*.tt[fc]'), recursive=True):
            name = os.path.basename(path).replace('_', ' ')
            real = os.path.realpath(path)  # Linux có symlink trùng (arial.ttf → Arial.ttf)
            if real in found or not any(name.startswith(p) for p in FONT_NAMES) or any(s in name for s in FONT_SKIP):
                continue
            try:
                font = pymupdf.Font(fontfile=path)
            except Exception:  # noqa: BLE001
                continue
            if all(font.has_glyph(ord(c)) for c in VI_PROBE):
                found[real] = path
    return sorted(found.values())


def text_cmd(args):
    os.makedirs(args.output, exist_ok=True)
    rng = random.Random(args.seed)
    fonts = _fonts()
    assert fonts, 'Không tìm thấy font có dấu tiếng Việt'
    lines = [norm(line) for line in open(args.corpus, encoding='utf-8')]
    lines = [line for line in lines if len(line) >= MIN_CHARS]
    for i in range(args.count):
        text = rng.choice(lines)
        words = text.split()
        if len(words) > 10:  # dòng dài → cắt đoạn 3–10 từ
            k = rng.randint(3, 10)
            start = rng.randint(0, len(words) - k)
            text = ' '.join(words[start:start + k])
        if rng.random() < P_UPPER:
            text = text.upper()
        font_path = rng.choice(fonts)
        points = rng.uniform(9, 14)
        image = _render(text, font_path, points * TARGET_DPI / 72, rng)
        _save(args.output, f'syn_{i:06d}', degrade(image, rng), text)
    print(f'{args.count} dòng ({len(fonts)} font) → {args.output}')


def _render(text, font_path, size, rng):
    font = ImageFont.truetype(font_path, int(size))
    left, top, right, bottom = ImageDraw.Draw(Image.new('L', (8, 8))).textbbox((0, 0), text, font=font)
    pad = int(size * rng.uniform(0.15, 0.4))
    image = Image.new('L', (right - left + 2 * pad, bottom - top + 2 * pad), 255)
    ImageDraw.Draw(image).text((pad - left, pad - top), text, font=font, fill=0)
    return np.asarray(image)


# ---------------------------------------------------------------- giả lập scan
def degrade(gray, rng):
    """Làm ảnh dòng giống scan: nghiêng nhẹ, mờ, nhoè mực, nhiễu, nén JPEG, rồi (đa số) nhị phân Otsu."""
    img = gray.astype(np.float32)
    if rng.random() < 0.6:
        angle = rng.uniform(-0.8, 0.8)
        h, w = img.shape
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        img = cv2.warpAffine(img, matrix, (w, h), borderValue=255)
    if rng.random() < 0.5:
        kernel = np.ones((2, 2), np.uint8)
        img = cv2.erode(img, kernel) if rng.random() < 0.5 else cv2.dilate(img, kernel)  # mực đậm / nhạt
    if rng.random() < 0.6:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.4, 1.3))
    img = img * rng.uniform(0.85, 1.0) + rng.uniform(0, 30)  # nền xám, mực không đen tuyệt đối
    if rng.random() < 0.6:
        img = img + np.random.default_rng(rng.randrange(2**32)).normal(0, rng.uniform(3, 14), img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    if rng.random() < 0.5:
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(35, 85)])
        img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if rng.random() < P_BINARY:
        img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return img


def _save(directory, name, image, text):
    cv2.imwrite(os.path.join(directory, name + '.png'), image)
    with open(os.path.join(directory, name + '.gt.txt'), 'w', encoding='utf-8') as f:
        f.write(text + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('corpus')
    p.add_argument('inputs', nargs='+')
    p.add_argument('-o', '--output', required=True)
    p = sub.add_parser('pdf')
    p.add_argument('inputs', nargs='+')
    p.add_argument('-o', '--output', required=True)
    p.add_argument('--seed', type=int, default=0)
    p = sub.add_parser('text')
    p.add_argument('corpus')
    p.add_argument('-o', '--output', required=True)
    p.add_argument('-n', '--count', type=int, default=5000)
    p.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    {'corpus': corpus_cmd, 'pdf': pdf_cmd, 'text': text_cmd}[args.cmd](args)


if __name__ == '__main__':
    main()
