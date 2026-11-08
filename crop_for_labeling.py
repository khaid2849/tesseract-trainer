"""Cắt từng dòng từ PDF scan THẬT để gán nhãn tay (bộ đánh giá / bổ sung dữ liệu train).

  ../../../../venv/bin/python crop_for_labeling.py <scan.pdf...> -o <thư mục> [--pages 1,2]

Mỗi dòng: <tên>.png (ảnh y như module đưa cho Tesseract: 300 DPI, đã xoay thẳng, nhị phân Otsu)
và <tên>.gt.txt điền sẵn chữ Tesseract đọc được → người gán nhãn SỬA LẠI cho đúng từng ký tự.
Dòng rác (kẻ bảng, chữ ký, con dấu) thì xoá cả 2 file. Mở review.html để soát nhanh ảnh ↔ chữ.
"""
import argparse
import html
import os
import re

import cv2
import numpy as np
import pymupdf
import pytesseract
from PIL import Image

ZOOM = 300 / 72
PAD = 6


def page_image(page):
    return prepare(render_gray(page))


def render_gray(page):
    """300 DPI grayscale array of a PDF page (copied out of the pixmap, safe to hand to another thread)."""
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width).copy()


def prepare(gray):
    """Straighten a 300 DPI grayscale page (OSD) and binarize it like the module does."""
    try:
        rotate = int(re.search(r'Rotate:\s*(\d+)', pytesseract.image_to_osd(Image.fromarray(gray))).group(1))
    except Exception:  # noqa: BLE001
        rotate = 0
    if rotate:
        gray = np.ascontiguousarray(np.rot90(gray, -rotate // 90))
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def lines(image, lang, with_conf=False, tessdata_dir=None):
    """Yield (text, bbox) per OCR line; with_conf adds the mean word confidence (0–100)."""
    config = '--oem 1 --psm 4' + (f' --tessdata-dir {tessdata_dir}' if tessdata_dir else '')
    data = pytesseract.image_to_data(Image.fromarray(image), lang=lang, config=config,
                                     output_type=pytesseract.Output.DICT)
    grouped = {}
    for i, word in enumerate(data['text']):
        if not word.strip() or float(data['conf'][i]) < 0:
            continue
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
        grouped.setdefault(key, []).append((word, (x, y, x + w, y + h), float(data['conf'][i])))
    for words in grouped.values():
        boxes = [box for _word, box, _conf in words]
        text = ' '.join(word for word, _box, _conf in words)
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        if with_conf:
            yield text, bbox, sum(conf for _word, _box, conf in words) / len(words)
        else:
            yield text, bbox


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inputs', nargs='+')
    parser.add_argument('-o', '--output', required=True)
    parser.add_argument('--pages', help='vd 1,2 (mặc định tất cả)')
    parser.add_argument('-l', '--lang', default='vie')
    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    rows = []
    for path in args.inputs:
        stem = re.sub(r'\W+', '_', os.path.splitext(os.path.basename(path))[0])[:40]
        document = pymupdf.open(path)
        numbers = [int(n) for n in args.pages.split(',')] if args.pages else range(1, len(document) + 1)
        for number in numbers:
            image = page_image(document[number - 1])
            for index, (text, (x0, y0, x1, y1)) in enumerate(lines(image, args.lang)):
                if y1 - y0 < 12 or len(text) < 2:
                    continue
                crop = image[max(y0 - PAD, 0):y1 + PAD, max(x0 - PAD, 0):x1 + PAD]
                name = f'{stem}_p{number}_{index:03d}'
                cv2.imwrite(os.path.join(args.output, name + '.png'), crop)
                with open(os.path.join(args.output, name + '.gt.txt'), 'w', encoding='utf-8') as f:
                    f.write(text + '\n')
                rows.append((name, text))
    with open(os.path.join(args.output, 'review.html'), 'w', encoding='utf-8') as f:
        f.write('<meta charset="utf-8"><style>body{font:16px sans-serif}img{max-height:40px;display:block}'
                'div{margin:8px 0;border-bottom:1px solid #ccc}</style>')
        for name, text in rows:
            f.write(f'<div><img src="{name}.png"><code>{name}.gt.txt</code>: {html.escape(text)}</div>')
    print(f'{len(rows)} dòng → {args.output} (soát: {args.output}/review.html)')


if __name__ == '__main__':
    main()
