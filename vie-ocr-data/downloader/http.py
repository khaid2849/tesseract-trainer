"""Resumable HTTP download with retries, rate limiting, checksum and partial (--max-bytes) support."""
import hashlib
import logging
import os
import re
import time

import requests
from tqdm import tqdm

from .common import USER_AGENT, write_manifest

log = logging.getLogger('http')
MAX_RETRIES = 5
CHUNK = 1 << 16


def session():
    s = requests.Session()
    s.headers['User-Agent'] = USER_AGENT
    return s


def head(url, timeout=30):
    """(status, content_type, size) without downloading the body."""
    response = session().head(url, allow_redirects=True, timeout=timeout)
    size = response.headers.get('Content-Length')
    return response.status_code, response.headers.get('Content-Type', ''), int(size) if size else None


def expected_sha1(sha1_url, filename):
    """Wikimedia *-sha1sums.txt lists dated names; 'latest' files map to the same entry by suffix."""
    text = session().get(sha1_url, timeout=60).text
    suffix = filename.split('-latest-', 1)[-1]
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and (parts[1] == filename or parts[1].endswith('-' + suffix)):
            return parts[0]
    return None


def _sha1(path):
    digest = hashlib.sha1()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def download_file(paths, source, spec, max_bytes=None, rate_limit=None):
    """Download one file spec {url, path, sha1_from?} into data/raw/<source>/; resumes via HTTP Range."""
    url = spec['url']
    target = os.path.join(paths.raw_dir(source['id']), spec['path'])
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + '.part'
    status, _ctype, total = head(url)
    if status != 200:
        raise RuntimeError(f'{url}: HTTP {status}')
    limit = min(total, max_bytes) if (total and max_bytes) else (max_bytes or total)
    partial = bool(max_bytes and (not total or max_bytes < total))

    if os.path.exists(target):
        size = os.path.getsize(target)
        if size == limit or (not partial and total and size == total):
            log.info('%s: đã có (%s byte), bỏ qua', spec['path'], size)
            return target, partial
        os.replace(target, part)  # file cũ chưa đủ (vd. lần trước tải một phần) → tải tiếp

    for attempt in range(1, MAX_RETRIES + 1):
        done = os.path.getsize(part) if os.path.exists(part) else 0
        if limit and done >= limit:
            break
        headers = {'Range': f'bytes={done}-'} if done else {}
        try:
            with session().get(url, headers=headers, stream=True, timeout=60) as response:
                if done and response.status_code != 206:
                    log.warning('%s: server không hỗ trợ Range, tải lại từ đầu', url)
                    done = 0
                response.raise_for_status()
                mode = 'ab' if done else 'wb'
                with open(part, mode) as f, tqdm(total=limit, initial=done, unit='B', unit_scale=True,
                                                 desc=spec['path'][:40]) as bar:
                    started = time.time()
                    received = 0
                    for block in response.iter_content(CHUNK):
                        if limit and done + len(block) > limit:
                            block = block[:limit - done]
                        f.write(block)
                        done += len(block)
                        received += len(block)
                        bar.update(len(block))
                        if rate_limit:  # bytes/giây
                            ahead = received / rate_limit - (time.time() - started)
                            if ahead > 0:
                                time.sleep(ahead)
                        if limit and done >= limit:
                            break
            break
        except (requests.RequestException, OSError) as error:
            wait = min(2 ** attempt, 60)
            log.warning('%s: lỗi lần %s/%s (%s), thử lại sau %ss', url, attempt, MAX_RETRIES, error, wait)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(wait)

    os.replace(part, target)
    if spec.get('sha1_from') and not partial:
        want = expected_sha1(spec['sha1_from'], os.path.basename(spec['path']))
        if want:
            got = _sha1(target)
            if got != want:
                os.replace(target, part)
                raise RuntimeError(f'{spec["path"]}: sai SHA-1 ({got} ≠ {want}). File giữ ở .part; xoá rồi tải lại.')
            log.info('%s: SHA-1 khớp', spec['path'])
        else:
            log.warning('%s: không tìm thấy SHA-1 trong %s', spec['path'], spec['sha1_from'])
    write_manifest(paths, source, url, target, partial=partial,
                   extra={'max_bytes': max_bytes} if partial else None)
    return target, partial


def safe_name(url):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', url.rsplit('/', 1)[-1])
