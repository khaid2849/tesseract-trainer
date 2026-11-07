"""build-gt: sample cleaned text lines (balanced over Vietnamese diacritics), render them as scan-like line images.

Rendering reuses make_gt.degrade() from the training kit so images match what the web app and module feed Tesseract.
Output (tesstrain format): <out>/train/*.png + *.gt.txt, <out>/eval/…, lines.tsv, stats.json
"""
import collections
import glob
import json
import logging
import multiprocessing
import os
import random
import shutil
import sys

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

import textproc

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)
import make_gt  # noqa: E402

log = logging.getLogger('build-gt')
POOL_FACTOR = 4          # số dòng ứng viên mỗi nguồn = hạn mức × hệ số, để có chỗ chọn dòng chứa ký tự hiếm
BALANCE_SHARE = 0.25     # tối đa 25% số dòng dành cho việc bù ký tự hiếm
BOLD_P = 0.25
POINT_SIZES = (9, 14)


# ---------------------------------------------------------------- fonts
def find_fonts(paths, extra_dirs):
    """Vietnamese-capable fonts: data/fonts (Google Fonts) + --fonts dirs + system fonts known to make_gt."""
    candidates = []
    for directory in [paths.fonts, *extra_dirs]:
        candidates += glob.glob(os.path.join(os.path.expanduser(directory), '**', '*.tt[fc]'), recursive=True)
        candidates += glob.glob(os.path.join(os.path.expanduser(directory), '**', '*.otf'), recursive=True)
    fonts = []
    for path in sorted(set(candidates)):
        try:
            font = pymupdf.Font(fontfile=path)
        except Exception:  # noqa: BLE001
            continue
        if all(font.has_glyph(ord(c)) for c in make_gt.VI_PROBE):
            fonts.append(path)
    return sorted(set(fonts) | set(make_gt._fonts()))


def _load_font(path, size, rng):
    font = ImageFont.truetype(path, int(size))
    try:  # variable font (Google Fonts): đôi khi chọn bản đậm
        axes = font.get_variation_axes()
        values = [a['default'] for a in axes]
        for i, axis in enumerate(axes):
            if axis.get('name') in (b'Weight', 'Weight') and rng.random() < BOLD_P:
                values[i] = min(700, axis['maximum'])
        font.set_variation_by_axes(values)
    except (OSError, AttributeError):
        pass
    return font


def render(task):
    name, text, font_path, seed, out_dir = task
    rng = random.Random(seed)
    size = rng.uniform(*POINT_SIZES) * make_gt.TARGET_DPI / 72
    font = _load_font(font_path, size, rng)
    left, top, right, bottom = ImageDraw.Draw(Image.new('L', (8, 8))).textbbox((0, 0), text, font=font)
    pad = int(size * rng.uniform(0.15, 0.4))
    image = Image.new('L', (right - left + 2 * pad, bottom - top + 2 * pad), 255)
    ImageDraw.Draw(image).text((pad - left, pad - top), text, font=font, fill=0)
    make_gt._save(out_dir, name, make_gt.degrade(np.asarray(image), rng), text)
    return name


# ---------------------------------------------------------------- sampling
def reservoir(folder, size, rng):
    pool, seen = [], 0
    for path in sorted(glob.glob(os.path.join(folder, 'part-*.txt'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                seen += 1
                if len(pool) < size:
                    pool.append(line)
                else:
                    j = rng.randrange(seen)
                    if j < size:
                        pool[j] = line
    return pool, seen


def quotas(available, total, weights):
    """Split `total` over sources by weight, capped by what each source has; leftovers go to the others."""
    share = {s: 0 for s in available}
    remaining = total
    active = {s for s in available if available[s]}
    while remaining > 0 and active:
        weight_sum = sum(weights.get(s, 1.0) for s in active)
        given = 0
        for s in sorted(active):
            want = max(1, int(remaining * weights.get(s, 1.0) / weight_sum))
            take = min(want, available[s] - share[s], remaining - given)
            share[s] += take
            given += take
        remaining -= given
        active = {s for s in active if share[s] < available[s]}
        if given == 0:
            break
    return share


def select(pools, share, upper_ratio, min_char, rng):
    """Uniform picks, then extra lines carrying under-represented diacritics (incl. their UPPERCASE forms)."""
    chosen = []
    for source, pool in pools.items():
        base = int(share[source] * (1 - BALANCE_SHARE))
        rng.shuffle(pool)
        for line in pool[:base]:
            chosen.append((source, line.upper() if rng.random() < upper_ratio else line))
        pools[source] = pool[base:]
    budget = sum(share.values()) - len(chosen)
    counts = collections.Counter(c for _s, line in chosen for c in line)
    leftovers = [(s, line) for s, pool in pools.items() for line in pool]
    rng.shuffle(leftovers)
    by_char = collections.defaultdict(list)
    for index, (_s, line) in enumerate(leftovers):
        for c in set(line.lower()):
            if c in textproc.VI_LOWER:
                by_char[c].append(index)
    used = set()
    cursors = {c: iter(by_char.get(c.lower(), [])) for c in textproc.VI_DIACRITICS}
    while budget > 0:  # xoay vòng: mỗi lượt 1 dòng cho mỗi ký tự còn thiếu, để ngân sách không dồn vào vài ký tự đầu
        progressed = False
        for char in sorted(cursors, key=lambda c: counts[c]):
            if budget <= 0 or counts[char] >= min_char:
                continue
            index = next((i for i in cursors[char] if i not in used), None)
            if index is None:
                continue
            used.add(index)
            source, line = leftovers[index]
            line = line.upper() if char.isupper() else line
            chosen.append((source, line))
            counts.update(line)
            budget -= 1
            progressed = True
        if not progressed:
            break
    for index, (source, line) in enumerate(leftovers):  # còn chỗ thì lấp bằng dòng ngẫu nhiên
        if budget <= 0:
            break
        if index not in used:
            chosen.append((source, line.upper() if rng.random() < upper_ratio else line))
            budget -= 1
    return chosen, counts


def run(paths, args):
    rng = random.Random(args.seed)
    sources = args.sources or sorted(os.path.basename(d) for d in glob.glob(os.path.join(paths.text, '*'))
                                     if glob.glob(os.path.join(d, 'part-*.txt')))
    if not sources:
        raise SystemExit('Chưa có text: chạy `vod.py download` rồi `vod.py extract` trước.')
    weights = {s['id']: s['gt_weight'] for s in args.source_defs if 'gt_weight' in s}
    for item in args.weights or []:
        key, _, value = item.partition('=')
        weights[key] = float(value)
    dropped = [s for s in sources if weights.get(s, 1.0) <= 0]
    if dropped:
        log.info('Không dùng (trọng số 0): %s', ', '.join(dropped))
        sources = [s for s in sources if s not in dropped]
    fonts = find_fonts(paths, args.fonts or [])
    if not fonts:
        raise SystemExit('Không tìm thấy font có dấu tiếng Việt: tải google_fonts hoặc truyền --fonts <thư mục>.')

    log.info('Đọc mẫu từ %s', ', '.join(sources))
    first_pass = {}
    for source in sources:
        stats_file = os.path.join(paths.text_dir(source), 'stats.json')
        with open(stats_file, encoding='utf-8') as f:
            first_pass[source] = json.load(f)['lines']
    share = quotas(first_pass, args.lines, weights)
    pools = {}
    for source in sources:
        pools[source], _seen = reservoir(paths.text_dir(source), share[source] * POOL_FACTOR, rng)
    chosen, counts = select(pools, share, args.upper, args.min_char_count, rng)
    rng.shuffle(chosen)

    out = os.path.abspath(os.path.expanduser(args.out or paths.ground_truth))
    if os.path.isdir(out):
        if not args.overwrite:
            raise SystemExit(f'{out} đã có dữ liệu: thêm --overwrite để tạo lại.')
        shutil.rmtree(out)
    for sub in ('train', 'eval'):
        os.makedirs(os.path.join(out, sub))
    n_eval = int(len(chosen) * args.eval_ratio)
    tasks, rows = [], []
    for i, (source, text) in enumerate(chosen):
        split = 'eval' if i < n_eval else 'train'
        name = f'vod_{source}_{i:07d}'
        font = rng.choice(fonts)
        tasks.append((name, text, font, rng.randrange(2 ** 32), os.path.join(out, split)))
        rows.append((name, split, source, os.path.basename(font), text))

    with multiprocessing.Pool(args.workers or os.cpu_count()) as pool:
        for _ in tqdm(pool.imap_unordered(render, tasks, chunksize=64), total=len(tasks), desc='render', unit=' dòng'):
            pass

    with open(os.path.join(out, 'lines.tsv'), 'w', encoding='utf-8') as f:
        f.write('name\tsplit\tsource\tfont\ttext\n')
        for row in rows:
            f.write('\t'.join(row) + '\n')
    rare = {c: counts[c] for c in textproc.VI_DIACRITICS}
    stats = {
        'lines': len(chosen), 'train': len(chosen) - n_eval, 'eval': n_eval,
        'per_source': dict(collections.Counter(s for s, _t in chosen)),
        'fonts': sorted({os.path.basename(f) for f in fonts}),
        'upper_ratio': args.upper, 'min_char_count': args.min_char_count,
        'diacritics_below_target': {c: n for c, n in sorted(rare.items(), key=lambda x: x[1])
                                    if n < args.min_char_count},
    }
    with open(os.path.join(out, 'stats.json'), 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    log.info('%s dòng (%s train / %s eval), %s font → %s', stats['lines'], stats['train'], stats['eval'],
             len(stats['fonts']), out)
    if stats['diacritics_below_target']:
        log.warning('Ký tự chưa đủ %s lần: %s', args.min_char_count, stats['diacritics_below_target'])
    return stats
