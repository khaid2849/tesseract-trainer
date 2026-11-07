#!/usr/bin/env python3
"""vie-ocr-data: tải, trích và sinh dữ liệu train Tesseract tiếng Việt từ các nguồn trong sources.yaml.

  vod.py verify                               kiểm tra URL từng nguồn (không tải)
  vod.py download --priority 1                tải nguồn ưu tiên 1 (chỉ nguồn giấy phép mở, trừ khi --allow)
  vod.py extract                              trích text sạch từ mọi nguồn đã tải
  vod.py build-gt --lines 50000               sinh ảnh dòng + .gt.txt (định dạng tesstrain)
  vod.py status                               bảng tóm tắt

Thư mục dữ liệu: $VOD_HOME hoặc ~/Works/tesseract-train/vie-ocr-data (web app train đọc ground-truth ở đây).
"""
import argparse
import datetime
import glob
import json
import logging
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from downloader import chinhphu, common, git, http  # noqa: E402

log = logging.getLogger('vod')


def human(n):
    if n is None:
        return '-'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024:
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


def table(rows, headers):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = '  '.join('{:<%d}' % w for w in widths)
    print(line.format(*headers))
    print('  '.join('-' * w for w in widths))
    for row in rows:
        print(line.format(*[str(x) for x in row]))


# ---------------------------------------------------------------- verify
def cmd_verify(args, paths):
    results = []
    for source in common.load_sources():
        kind = source['kind']
        try:
            if kind == 'http':
                for spec in source['files']:
                    status, ctype, size = http.head(spec['url'])
                    results.append([source['id'], source.get('license_status'), status, ctype.split(';')[0],
                                    human(size), spec['url']])
                    if spec.get('sha1_from'):
                        status, ctype, size = http.head(spec['sha1_from'])
                        results.append([source['id'], '', status, ctype.split(';')[0], human(size), spec['sha1_from']])
            elif kind == 'portal':
                url = chinhphu.VANBAN_LIST if source['portal'] == 'vanban' else chinhphu.CONGBAO_LIST  # pairs: Công báo
                status, ctype, size = http.head(url)
                results.append([source['id'], source.get('license_status'), status, ctype.split(';')[0], '-', url])
            elif kind == 'git':
                ok = git.ls_remote(source['repo'])
                results.append([source['id'], source.get('license_status'), 'ok' if ok else 'LỖI', 'git', '-',
                                source['repo']])
            else:
                results.append([source['id'], source.get('license_status'), 'manual', '-', '-',
                                (source.get('instructions') or '')[:60]])
        except Exception as error:  # noqa: BLE001
            results.append([source['id'], source.get('license_status'), 'LỖI', '-', '-', str(error)[:80]])
    table(results, ['nguồn', 'giấy phép', 'trạng thái', 'loại', 'dung lượng', 'url / ghi chú'])
    os.makedirs(paths.logs, exist_ok=True)
    report = os.path.join(paths.logs, f'verify-{datetime.datetime.now():%Y%m%d-%H%M}.json')
    with open(report, 'w', encoding='utf-8') as f:
        json.dump([dict(zip(['id', 'license_status', 'status', 'type', 'size', 'url'], r)) for r in results], f,
                  ensure_ascii=False, indent=1)
    print(f'\nĐã ghi {report}')


# ---------------------------------------------------------------- download
def cmd_download(args, paths):
    sources, skipped = common.select_sources(common.load_sources(), args.source, args.priority, args.all, args.allow)
    for source, reason in skipped:
        log.warning('Bỏ qua %s: %s', source['id'], reason)
    if not sources:
        raise SystemExit('Không có nguồn nào để tải (chọn --source, --priority hoặc --all).')
    failed = []
    for source in sources:
        try:
            if source['kind'] == 'manual':
                log.info('%s: tải tay — %s', source['id'], source.get('instructions', ''))
                continue
            if source['kind'] == 'git':
                git.checkout(paths, source)
                continue
            if source['kind'] == 'portal':
                limit = args.max_docs or source.get('default_max_docs', 20)
                if source['portal'] == 'vanban':
                    chinhphu.crawl_vanban(paths, source, limit, args.delay, args.max_file_mb,
                                          source.get('want', 'scan'), args.start_id)
                elif source['portal'] == 'pairs':
                    chinhphu.pair_congbao(paths, source, limit, args.delay, args.max_file_mb,
                                          args.max_scan_ids or source.get('default_max_scan_ids', 800))
                else:
                    chinhphu.crawl_congbao(paths, source, limit, args.delay, args.max_file_mb)
                continue
            max_bytes = args.max_bytes if args.max_bytes is not None else source.get('default_max_bytes')
            for spec in source['files']:
                target, partial = http.download_file(paths, source, spec, max_bytes=max_bytes or None,
                                                     rate_limit=args.rate_limit)
                if partial:
                    log.info('%s: tải một phần (%s), dùng --max-bytes 0 để tải đủ', spec['path'], human(max_bytes))
                if source.get('install_to') == 'tessdata':
                    os.makedirs(paths.tessdata, exist_ok=True)
                    shutil.copy2(target, os.path.join(paths.tessdata, os.path.basename(target)))
        except Exception as error:  # noqa: BLE001
            log.error('%s: %s', source['id'], error)
            failed.append(source['id'])
    if failed:
        raise SystemExit(f'Lỗi: {", ".join(failed)} (chạy lại lệnh để tải tiếp)')


# ---------------------------------------------------------------- extract
def cmd_extract(args, paths):
    import extract
    all_sources = common.load_sources()
    if args.source:
        sources, skipped = common.select_sources(all_sources, args.source, allow=args.allow)
    else:  # mặc định: mọi nguồn đã tải và được phép
        downloaded = [s for s in all_sources if os.path.isdir(paths.raw_dir(s['id']))]
        sources, skipped = common.select_sources(downloaded, [s['id'] for s in downloaded], allow=args.allow)
    for source, reason in skipped:
        log.warning('Bỏ qua %s: %s', source['id'], reason)
    for source in sources:
        extract.run(paths, source, args.max_lines)


# ---------------------------------------------------------------- build-gt
def cmd_build_gt(args, paths):
    import build_gt
    allowed = {'open', *args.allow}
    by_id = {s['id']: s for s in common.load_sources()}
    present = args.sources or [os.path.basename(d) for d in glob.glob(os.path.join(paths.text, '*'))]
    blocked = [s for s in present if by_id.get(s, {}).get('license_status', 'unverified') not in allowed]
    if blocked:
        if args.sources:
            raise SystemExit(f'Nguồn {", ".join(blocked)} không có giấy phép mở: thêm --allow nếu chắc chắn.')
        log.warning('Không dùng %s (giấy phép chưa mở; thêm --allow để dùng)', ', '.join(blocked))
    args.sources = [s for s in present if s not in blocked]
    args.source_defs = list(by_id.values())
    build_gt.run(paths, args)


# ---------------------------------------------------------------- status
def dir_size(path):
    return sum(os.path.getsize(p) for p in glob.glob(os.path.join(path, '**', '*'), recursive=True)
               if os.path.isfile(p) and '/.git/' not in p)


def cmd_status(args, paths):
    manifest = common.read_manifest(paths)
    gt_stats = {}
    gt_file = os.path.join(paths.ground_truth, 'stats.json')
    if os.path.exists(gt_file):
        with open(gt_file, encoding='utf-8') as f:
            gt_stats = json.load(f)
    rows = []
    for source in common.load_sources():
        raw = paths.raw_dir(source['id'])
        records = [r for (sid, _p), r in manifest.items() if sid == source['id']]
        downloaded = human(dir_size(raw)) if os.path.isdir(raw) else '-'
        if any(r.get('partial') for r in records):
            downloaded += ' (một phần)'
        stats_file = os.path.join(paths.text_dir(source['id']), 'stats.json')
        lines = '-'
        if os.path.exists(stats_file):
            with open(stats_file, encoding='utf-8') as f:
                lines = f'{json.load(f)["lines"]:,}'
        gt = gt_stats.get('per_source', {}).get(source['id'], '-')
        rows.append([source['id'], source.get('priority'), source.get('license_status'), source['kind'], downloaded,
                     lines, gt])
    table(rows, ['nguồn', 'P', 'giấy phép', 'loại', 'đã tải', 'dòng text', 'dòng GT'])
    fonts = glob.glob(os.path.join(paths.fonts, '*.tt[fc]'))
    print(f'\nThư mục: {paths.home}')
    print(f'Font đã cài: {len(fonts)} (data/fonts)')
    if gt_stats:
        print(f'Ground-truth: {gt_stats["lines"]:,} dòng ({gt_stats["train"]:,} train / {gt_stats["eval"]:,} eval) '
              f'→ {paths.ground_truth}')
        if gt_stats.get('diacritics_below_target'):
            print(f'  Ký tự chưa đủ {gt_stats["min_char_count"]} lần: {gt_stats["diacritics_below_target"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--home', help='thư mục dữ liệu (mặc định $VOD_HOME hoặc ~/Works/tesseract-train/vie-ocr-data)')
    parser.add_argument('-v', '--verbose', action='store_true')
    sub = parser.add_subparsers(dest='cmd', required=True)

    def allow_arg(p):
        p.add_argument('--allow', nargs='+', default=[], choices=['unverified', 'research'],
                       help='cho phép nguồn chưa xác minh giấy phép / chỉ dùng nghiên cứu '
                            '(KHÔNG dùng cho model thương mại)')

    sub.add_parser('verify', help='kiểm tra URL các nguồn, không tải')

    p = sub.add_parser('download', help='tải nguồn')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--source', nargs='+')
    group.add_argument('--priority', type=int)
    group.add_argument('--all', action='store_true')
    allow_arg(p)
    p.add_argument('--max-bytes', type=int, help='chỉ tải N byte đầu mỗi file (0 = đủ); mặc định theo sources.yaml')
    p.add_argument('--rate-limit', type=int, help='giới hạn tốc độ, byte/giây')
    p.add_argument('--max-docs', type=int, help='nguồn cổng Chính phủ: số văn bản / số Công báo cần lấy')
    p.add_argument('--delay', type=float, default=1.5, help='nguồn cổng Chính phủ: giây nghỉ giữa 2 request')
    p.add_argument('--max-file-mb', type=float, default=60, help='bỏ file PDF lớn hơn N MB')
    p.add_argument('--max-scan-ids', type=int,
                   help='congbao_pairs: số trang văn bản trên cổng Chính phủ được đọc tiêu đề')
    p.add_argument('--start-id', type=int, help='chinhphu_scan: bắt đầu từ docid này lùi về (bỏ qua văn bản mới hơn)')

    p = sub.add_parser('extract', help='trích text sạch vào data/text/')
    p.add_argument('--source', nargs='+')
    allow_arg(p)
    p.add_argument('--max-lines', type=int, default=2_000_000, help='tối đa số dòng mỗi nguồn (0 = không giới hạn)')

    p = sub.add_parser('build-gt', help='sinh ảnh dòng + .gt.txt')
    p.add_argument('--lines', type=int, default=50_000)
    p.add_argument('--sources', nargs='+', help='mặc định: mọi nguồn đã extract và được phép')
    p.add_argument('--weights', nargs='+', metavar='NGUON=TRONGSO',
                   help='ghi đè gt_weight trong sources.yaml, vd. viwikisource=3 viwiki=1')
    p.add_argument('--fonts', nargs='+', help='thêm thư mục font (ngoài data/fonts và font hệ thống)')
    p.add_argument('--upper', type=float, default=0.3, help='tỉ lệ dòng IN HOA (điểm yếu của vie gốc)')
    p.add_argument('--min-char-count', type=int, default=300, help='mỗi ký tự có dấu xuất hiện ít nhất N lần')
    p.add_argument('--eval-ratio', type=float, default=0.1)
    p.add_argument('--out', help='mặc định data/ground-truth')
    p.add_argument('--overwrite', action='store_true')
    p.add_argument('--workers', type=int)
    p.add_argument('--seed', type=int, default=1)
    allow_arg(p)

    sub.add_parser('status', help='bảng tóm tắt')
    args = parser.parse_args()
    paths = common.Paths(args.home)
    common.setup_logging(paths, args.verbose)
    {'verify': cmd_verify, 'download': cmd_download, 'extract': cmd_extract, 'build-gt': cmd_build_gt,
     'status': cmd_status}[args.cmd](args, paths)


if __name__ == '__main__':
    main()
