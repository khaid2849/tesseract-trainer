"""Đo hiệu quả SO SÁNH (đúng cách module tô màu) với 1 model Tesseract trên các cặp file có đáp án.

  cd /Users/khaid/Works/odoo-18.0
  PYTHONPATH=$PWD ./venv/bin/python <đường dẫn>/eval_compare.py pairs.tsv -l vie vie_syntra \
      [--tessdata-dir DIR] [--addons <repo checkout branch tesseract>]

pairs.tsv: mỗi dòng  <bản gốc.pdf> TAB <bản sửa đổi.pdf> TAB <từ bị sửa ở bản gốc, cách nhau dấu cách>
           TAB <từ mới ở bản sửa đổi>   (đường dẫn tương đối theo thư mục chứa pairs.tsv; dòng # là ghi chú)
Chỉ số: bắt được (từ đáp án nằm trong vùng tô) và tô thừa (từ bị tô nhưng không có trong đáp án). Không đụng DB.
"""
import argparse
import os
import sys
import time
from difflib import SequenceMatcher

import odoo
from odoo.tools import config

config.parse_config(['-c', 'vina-dev-conf.conf'])
odoo.modules.module.initialize_sys_path()
# --addons <thư mục repo>: dùng code module từ worktree khác (vd branch Tesseract) thay vì thư mục đang checkout.
if '--addons' in sys.argv:
    odoo.addons.__path__.insert(0, os.path.abspath(sys.argv[sys.argv.index('--addons') + 1]))

from odoo.addons.syntra_document_compare.utils import ocr_tesseract, pdf_reader, redline  # noqa: E402


def changed_tokens(old_doc, new_doc):
    ocr = ocr_tesseract.read_pages
    old_words, _ = redline._positioned_words(pdf_reader.read_pdf(old_doc, ocr=ocr, max_scan_pages=100).blocks)
    new_words, _ = redline._positioned_words(pdf_reader.read_pdf(new_doc, ocr=ocr, max_scan_pages=100).blocks)
    old_tokens, new_tokens = [t for t, _b in old_words], [t for t, _b in new_words]
    old_changed, new_changed = [], []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes():
        if op != 'equal':
            old_changed += old_tokens[i1:i2]
            new_changed += new_tokens[j1:j2]
    return old_changed, new_changed


def score(changed, expected):
    pool = list(changed)
    hit = 0
    for token in expected:
        if token in pool:
            pool.remove(token)
            hit += 1
    return hit, len(pool)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pairs')
    parser.add_argument('-l', '--lang', nargs='+', default=['vie'])
    parser.add_argument('--tessdata-dir')
    parser.add_argument('--addons', help='thư mục repo chứa module (mặc định theo addons_path)')
    parser.add_argument('--show', action='store_true', help='in các từ bị tô (để viết đáp án)')
    args = parser.parse_args()
    base = os.path.dirname(os.path.abspath(args.pairs))
    pairs = []
    for line in open(args.pairs, encoding='utf-8'):
        if line.strip() and not line.startswith('#'):
            old, new, old_exp, new_exp = (line.rstrip('\n').split('\t') + ['', ''])[:4]
            pairs.append((os.path.join(base, old), os.path.join(base, new),
                          old_exp.split(), new_exp.split()))
    default_config = ocr_tesseract.CONFIG
    for lang in args.lang:
        ocr_tesseract.LANG = lang
        ocr_tesseract.CONFIG = default_config + (f' --tessdata-dir {args.tessdata_dir}' if args.tessdata_dir else '')
        total = [0, 0, 0]  # bắt được, đáp án, tô thừa
        print(f'\n== {lang}')
        for old, new, old_exp, new_exp in pairs:
            start = time.time()
            with open(old, 'rb') as f_old, open(new, 'rb') as f_new:
                old_changed, new_changed = changed_tokens(f_old.read(), f_new.read())
            old_hit, old_noise = score(old_changed, old_exp)
            new_hit, new_noise = score(new_changed, new_exp)
            total[0] += old_hit + new_hit
            total[1] += len(old_exp) + len(new_exp)
            total[2] += old_noise + new_noise
            print(f'  {os.path.basename(new)[:45]:45} bắt được {old_hit + new_hit}/{len(old_exp) + len(new_exp)} '
                  f'| tô thừa: gốc {old_noise}, sửa đổi {new_noise} từ | {time.time() - start:.1f}s')
            if args.show:
                print('    tô ở bản gốc   :', ' '.join(old_changed))
                print('    tô ở bản sửa đổi:', ' '.join(new_changed))
        print(f'  TỔNG: bắt được {total[0]}/{total[1]}, tô thừa {total[2]} từ')


if __name__ == '__main__':
    main()
