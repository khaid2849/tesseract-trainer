"""Government portals: scanned/signed documents (vanban.chinhphu.vn) and Official Gazette issues (congbao.chinhphu.vn).

Both sites expose sequential numeric ids, so we walk backwards from the newest id instead of driving ASP.NET paging.
Polite by default: one request at a time, `delay` seconds between requests, already-seen ids are skipped.
"""
import json
import logging
import os
import re
import time

import pymupdf

from .common import write_manifest
from .http import session

log = logging.getLogger('chinhphu')
VANBAN_LIST = 'https://vanban.chinhphu.vn/he-thong-van-ban?classid=1&mode=1'
VANBAN_DOC = 'https://vanban.chinhphu.vn/?pageid=27160&docid={id}&classid=1'
VANBAN_PDF_RE = re.compile(r'https://datafiles\.chinhphu\.vn/cpp/files/vbpq/[^"\' <>]+?\.pdf', re.I)
CONGBAO_LIST = 'https://congbao.chinhphu.vn/cong-bao.htm'
CONGBAO_ISSUE = 'https://congbao.chinhphu.vn/cong-bao/x-{id}.htm'
CONGBAO_PDF_RE = re.compile(r'data-file="(https://congbaocdn\.chinhphu\.vn/[^"]+?\.pdf)"', re.I)
TITLE_RE = re.compile(r'<title>\s*([^<]+?)\s*</title>', re.I)
MAX_MISSES = 40  # số id liên tiếp không có tài liệu → coi như hết


class Crawler:
    def __init__(self, paths, source, delay, index_name='index.jsonl'):
        self.folder = paths.raw_dir(source['id'])
        os.makedirs(self.folder, exist_ok=True)
        self.index_file = os.path.join(self.folder, index_name)
        self.paths, self.source, self.delay = paths, source, delay
        self.http = session()
        self.seen = {}
        if os.path.exists(self.index_file):
            with open(self.index_file, encoding='utf-8') as f:
                for line in f:
                    record = json.loads(line)
                    self.seen[record['id']] = record
        self.last = 0.0

    def get(self, url, **kwargs):
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        for attempt in range(1, 4):
            try:
                response = self.http.get(url, timeout=120, **kwargs)
                if response.status_code == 404:  # id khuyết: không phải lỗi
                    return None
                response.raise_for_status()
                return response
            except Exception as error:  # noqa: BLE001
                if attempt == 3:
                    raise
                log.warning('%s: %s, thử lại', url, error)
                time.sleep(5 * attempt)

    def record(self, entry):
        self.seen[entry['id']] = entry
        with open(self.index_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def save_pdf(self, url, name, max_mb):
        target = os.path.join(self.folder, name)
        if not os.path.exists(target):
            response = self.get(url, stream=True)
            if response is None:
                return None
            size = int(response.headers.get('Content-Length') or 0)
            if max_mb and size > max_mb * 1e6:
                log.info('  bỏ %s (%.0f MB > %s MB)', name, size / 1e6, max_mb)
                return None
            tmp = target + '.part'
            with open(tmp, 'wb') as f:
                for block in response.iter_content(1 << 16):
                    f.write(block)
            os.replace(tmp, target)
        info = page_kinds(target)
        write_manifest(self.paths, self.source, url, target, extra=info)
        return {'file': name, 'url': url, **info}


def page_kinds(path):
    """Count scanned pages (full-page image, almost no text) vs pages with a real text layer."""
    try:
        document = pymupdf.open(path)
    except Exception as error:  # noqa: BLE001
        return {'pages': 0, 'scan_pages': 0, 'error': str(error)}
    scan = sum(1 for page in document if page.get_images() and len(page.get_text().strip()) < 400)
    return {'pages': len(document), 'scan_pages': scan}


def _slug(text, limit=60):
    import unicodedata
    text = unicodedata.normalize('NFKD', text.replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_')[:limit] or 'doc'


def crawl_vanban(paths, source, max_docs, delay, max_mb, want='scan', start_id=None):
    """Newest documents first; keeps docs whose PDFs are mostly scans (want='scan'), text ('text') or both ('all')."""
    crawler = Crawler(paths, source, delay)
    html = crawler.get(VANBAN_LIST).text
    ids = [int(x) for x in re.findall(r'docid=(\d+)', html)]
    if not ids:
        raise RuntimeError('Không đọc được danh sách văn bản (trang đổi cấu trúc?)')
    kept = sum(1 for r in crawler.seen.values() if r.get('kept'))
    doc_id, misses = min(start_id, max(ids)) if start_id else max(ids), 0
    while kept < max_docs and misses < MAX_MISSES and doc_id > 0:
        if doc_id in crawler.seen:
            doc_id -= 1
            continue
        response = crawler.get(VANBAN_DOC.format(id=doc_id))
        page = response.text if response is not None else ''
        urls = sorted(set(VANBAN_PDF_RE.findall(page)))
        title = (TITLE_RE.search(page) or [None, ''])[1]
        entry = {'id': doc_id, 'title': title, 'url': VANBAN_DOC.format(id=doc_id), 'files': [], 'kept': False}
        if not urls:
            misses += 1
            crawler.record(entry)
            doc_id -= 1
            continue
        misses = 0
        for url in urls:
            saved = crawler.save_pdf(url, f'{doc_id}_{_slug(os.path.basename(url)[:-4])}.pdf', max_mb)
            if saved:
                entry['files'].append(saved)
        pages = sum(f['pages'] for f in entry['files'])
        scans = sum(f['scan_pages'] for f in entry['files'])
        is_scan = pages and scans / pages >= 0.5
        entry['kept'] = bool(pages) and (want == 'all' or (want == 'scan') == bool(is_scan))
        if not entry['kept']:  # không đúng loại cần lấy → xoá file, vẫn ghi index để lần sau bỏ qua
            for f in entry['files']:
                os.remove(os.path.join(crawler.folder, f['file']))
        else:
            kept += 1
            log.info('[%s/%s] %s: %s trang (%s scan) — %s', kept, max_docs, doc_id, pages, scans, title[:70])
        crawler.record(entry)
        doc_id -= 1
    log.info('%s: %s văn bản trong %s', source['id'], kept, crawler.folder)
    return kept


def crawl_congbao(paths, source, max_issues, delay, max_mb):
    """Newest Official Gazette issues: typeset PDFs with a text layer (auto labels + reference text for scans)."""
    crawler = Crawler(paths, source, delay)
    html = crawler.get(CONGBAO_LIST).text
    ids = [int(x) for x in re.findall(r'/cong-bao/[^"#]*?-(\d+)\.htm', html)]
    if not ids:
        raise RuntimeError('Không đọc được danh sách Công báo (trang đổi cấu trúc?)')
    kept = sum(1 for r in crawler.seen.values() if r.get('kept'))
    issue_id, misses = max(ids), 0
    while kept < max_issues and misses < MAX_MISSES and issue_id > 0:
        if issue_id in crawler.seen:
            issue_id -= 1
            continue
        response = crawler.get(CONGBAO_ISSUE.format(id=issue_id))
        page = response.text if response is not None else ''
        match = CONGBAO_PDF_RE.search(page)
        title = (TITLE_RE.search(page) or [None, ''])[1]
        entry = {'id': issue_id, 'title': title, 'url': CONGBAO_ISSUE.format(id=issue_id), 'files': [], 'kept': False}
        if not match:
            misses += 1
        else:
            misses = 0
            saved = crawler.save_pdf(match.group(1), f'{issue_id}_{_slug(title)}.pdf', max_mb)
            if saved:
                entry['files'].append(saved)
                entry['kept'] = True
                kept += 1
                log.info('[%s/%s] %s: %s trang — %s', kept, max_issues, issue_id, saved['pages'], title)
        crawler.record(entry)
        issue_id -= 1
    log.info('%s: %s số Công báo trong %s', source['id'], kept, crawler.folder)
    return kept


# ---------------------------------------------------------------- ghép scan ↔ Công báo theo số hiệu
SO_HIEU_RE = re.compile(r'\bsố\s+([0-9][\w./-]*[A-Za-zĐđ])', re.I)
CONGBAO_DOC_LINK_RE = re.compile(r'href="(/van-ban/([a-z0-9-]+?)-(\d+)/\d+\.htm)"')
CONGBAO_DOC_PDF_RE = re.compile(r'href="(https://congbaocdn\.chinhphu\.vn/[^"]+?\.pdf)"', re.I)


def so_hieu_key(title):
    """'Nghị định số 401/2026/NĐ-CP của …' → '401-2026-nd-cp' (same form as the Công báo URL slug)."""
    match = SO_HIEU_RE.search(title or '')
    return _slug(match.group(1), 80).lower().replace('_', '-') if match else None


def pair_congbao(paths, source, max_issues, delay, max_mb, max_scan_ids=800):
    """Scanned documents that ALSO have a text PDF on the Official Gazette, matched by document number.

    1. Read the table of contents of the newest `max_issues` gazette issues (no issue PDF download).
    2. Walk vanban.chinhphu.vn document ids backwards (title only) up to `max_scan_ids`.
    3. For a title whose number is in the gazette, keep its PDF if mostly scanned, and fetch the gazette's own PDF of
       that document. Output: scan/*.pdf, ref/*.pdf, pairs.jsonl.
    """
    issues = Crawler(paths, source, delay, index_name='congbao_issues.jsonl')
    docs = Crawler(paths, source, delay, index_name='vanban_titles.jsonl')
    for sub in ('scan', 'ref'):
        os.makedirs(os.path.join(issues.folder, sub), exist_ok=True)
    pairs_file = os.path.join(issues.folder, 'pairs.jsonl')
    done = set()
    if os.path.exists(pairs_file):
        with open(pairs_file, encoding='utf-8') as f:
            done = {json.loads(line)['so_hieu'] for line in f}

    published = {}  # số hiệu → (đường dẫn trang văn bản trên Công báo, tên số Công báo)
    html = issues.get(CONGBAO_LIST).text
    issue_id = max(int(x) for x in re.findall(r'/cong-bao/[^"#]*?-(\d+)\.htm', html))
    checked = 0
    while checked < max_issues and issue_id > 0:
        issue = issues.seen.get(issue_id)
        if issue is None:
            response = issues.get(CONGBAO_ISSUE.format(id=issue_id))
            page = response.text if response is not None else ''
            title = (TITLE_RE.search(page) or [None, ''])[1]
            issue = {'id': issue_id, 'title': title,
                     'docs': sorted({(m[1], m[0]) for m in CONGBAO_DOC_LINK_RE.findall(page)})}
            issues.record(issue)
        checked += bool(issue.get('title'))
        for slug, link in issue.get('docs', []):
            if '-so-' in slug:
                published[slug.split('-so-', 1)[1]] = (link, issue['title'])
        issue_id -= 1
    log.info('Công báo: %s số, %s văn bản có số hiệu', checked, len(published))

    html = docs.get(VANBAN_LIST).text
    doc_id = max(int(x) for x in re.findall(r'docid=(\d+)', html))
    paired = len(done)
    for _ in range(max_scan_ids):
        if doc_id <= 0:
            break
        record = docs.seen.get(doc_id)
        if record is None:
            response = docs.get(VANBAN_DOC.format(id=doc_id))
            page = response.text if response is not None else ''
            record = {'id': doc_id, 'title': (TITLE_RE.search(page) or [None, ''])[1],
                      'pdfs': sorted(set(VANBAN_PDF_RE.findall(page)))}
            docs.record(record)
        key = so_hieu_key(record['title'])
        if key and key in published and key not in done and record['pdfs']:
            paired += _make_pair(docs, record, key, published[key], pairs_file, max_mb)
            done.add(key)
        doc_id -= 1
    log.info('Đã ghép %s văn bản scan ↔ Công báo trong %s', paired, issues.folder)
    return paired


def _make_pair(crawler, record, key, published, pairs_file, max_mb):
    files = [crawler.save_pdf(url, f'scan/{key}_{i}.pdf', max_mb) for i, url in enumerate(record['pdfs'])]
    files = [f for f in files if f]
    pages = sum(f['pages'] for f in files)
    if not pages or sum(f['scan_pages'] for f in files) / pages < 0.5:  # bản trên cổng là PDF có chữ → không cần
        for f in files:
            os.remove(os.path.join(crawler.folder, f['file']))
        return 0
    link, issue_title = published
    response = crawler.get('https://congbao.chinhphu.vn' + link)
    match = CONGBAO_DOC_PDF_RE.search(response.text if response is not None else '')
    reference = crawler.save_pdf(match.group(1), f'ref/{key}.pdf', max_mb) if match else None
    if not reference:
        for f in files:
            os.remove(os.path.join(crawler.folder, f['file']))
        return 0
    pair = {'so_hieu': key, 'title': record['title'], 'scan_files': [f['file'] for f in files],
            'scan_pages': pages, 'reference_file': reference['file'], 'reference_pages': reference['pages'],
            'congbao_issue': issue_title, 'congbao_url': 'https://congbao.chinhphu.vn' + link,
            'vanban_url': VANBAN_DOC.format(id=record['id'])}
    with open(pairs_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(pair, ensure_ascii=False) + '\n')
    log.info('Ghép: %s (%s trang scan) ↔ %s', record['title'][:70], pages, issue_title)
    return 1
