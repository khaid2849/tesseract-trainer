"""Đo độ chính xác Tesseract trên bộ dòng có nhãn (<tên>.png + <tên>.gt.txt).

  ../../../../venv/bin/python eval_lines.py <thư mục gt> -l vie vie_syntra [--tessdata-dir DIR] [--psm 7]

In: CER (tỉ lệ lỗi ký tự), WER (tỉ lệ lỗi từ), % dòng đúng hoàn toàn, CER riêng dòng IN HOA, các cặp hay nhầm.
"""
import argparse
import collections
import difflib
import glob
import os
import time
import unicodedata

import pytesseract
from PIL import Image


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def norm(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def evaluate(files, lang, config):
    chars = char_err = words = word_err = exact = 0
    upper_chars = upper_err = 0
    confusions = collections.Counter()
    start = time.time()
    for png in files:
        truth = norm(open(png[:-4] + '.gt.txt', encoding='utf-8').read())
        guess = norm(pytesseract.image_to_string(Image.open(png), lang=lang, config=config))
        err = distance(truth, guess)
        chars += len(truth)
        char_err += err
        words += len(truth.split())
        word_err += distance(truth.split(), guess.split())
        exact += truth == guess
        if truth.isupper():
            upper_chars += len(truth)
            upper_err += err
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, truth, guess, autojunk=False).get_opcodes():
            if op != 'equal' and i2 - i1 <= 3 and j2 - j1 <= 3:
                confusions[(truth[i1:i2], guess[j1:j2])] += 1
    return {
        'CER': char_err / max(chars, 1), 'WER': word_err / max(words, 1), 'exact': exact / max(len(files), 1),
        'CER_upper': upper_err / upper_chars if upper_chars else None,
        'sec_per_line': (time.time() - start) / max(len(files), 1), 'confusions': confusions.most_common(15),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('gt_dir')
    parser.add_argument('-l', '--lang', nargs='+', default=['vie'])
    parser.add_argument('--tessdata-dir')
    parser.add_argument('--psm', default='7')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    files = sorted(f for f in glob.glob(os.path.join(args.gt_dir, '*.png')) if os.path.exists(f[:-4] + '.gt.txt'))
    files = files[:args.limit] if args.limit else files
    config = f'--oem 1 --psm {args.psm}' + (f' --tessdata-dir {args.tessdata_dir}' if args.tessdata_dir else '')
    print(f'{len(files)} dòng trong {args.gt_dir}')
    for lang in args.lang:
        r = evaluate(files, lang, config)
        upper = f"{r['CER_upper']:.2%}" if r['CER_upper'] is not None else '-'
        print(f"\n== {lang}: CER {r['CER']:.2%} | WER {r['WER']:.2%} | dòng đúng {r['exact']:.1%} | "
              f"CER IN HOA {upper} | {r['sec_per_line']:.2f} s/dòng")
        print('   hay nhầm (đúng → đọc ra: số lần):',
              ', '.join(f"'{a}'→'{b}': {n}" for (a, b), n in r['confusions']))


if __name__ == '__main__':
    main()
