"""Paths, logging, manifest and source selection shared by all commands."""
import datetime
import hashlib
import json
import logging
import os

import yaml

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_FILE = os.path.join(CODE_DIR, 'sources.yaml')
USER_AGENT = 'vie-ocr-data/0.1 (Tesseract Vietnamese fine-tuning; python-requests)'
LICENSE_LEVELS = ('open', 'unverified', 'research')


class Paths:
    """Data layout under the home dir (default ~/Works/tesseract-train/vie-ocr-data, override with VOD_HOME)."""

    def __init__(self, home=None):
        self.home = os.path.abspath(os.path.expanduser(
            home or os.environ.get('VOD_HOME') or '~/Works/tesseract-train/vie-ocr-data'))
        self.data = os.path.join(self.home, 'data')
        self.raw = os.path.join(self.data, 'raw')
        self.text = os.path.join(self.data, 'text')
        self.fonts = os.path.join(self.data, 'fonts')
        self.tessdata = os.path.join(self.data, 'tessdata')
        self.ground_truth = os.path.join(self.data, 'ground-truth')
        self.manifest = os.path.join(self.home, 'manifest.jsonl')
        self.logs = os.path.join(self.home, 'logs')

    def raw_dir(self, source_id):
        return os.path.join(self.raw, source_id)

    def text_dir(self, source_id):
        return os.path.join(self.text, source_id)


def setup_logging(paths, verbose=False):
    os.makedirs(paths.logs, exist_ok=True)
    handlers = [logging.FileHandler(os.path.join(paths.logs, 'vod.log'), encoding='utf-8'), logging.StreamHandler()]
    handlers[1].setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=handlers,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def load_sources():
    with open(SOURCES_FILE, encoding='utf-8') as f:
        return yaml.safe_load(f)['sources']


def select_sources(sources, ids=None, priority=None, all_=False, allow=(), groups=None):
    """Sources matching the selection; license_status beyond 'open' needs an explicit --allow."""
    allowed = {'open', *allow}
    picked, skipped = [], []
    for source in sources:
        if groups and source.get('group') not in groups:
            continue
        if ids:
            wanted = source['id'] in ids
        elif priority:
            wanted = source.get('priority', 9) <= priority
        else:
            wanted = all_
        if not wanted:
            continue
        if source.get('license_status', 'unverified') not in allowed:
            skipped.append((source, f"giấy phép '{source.get('license_status')}' → thêm --allow "
                                    f"{source.get('license_status')} nếu chắc chắn được phép dùng"))
            continue
        picked.append(source)
    if ids:
        unknown = set(ids) - {s['id'] for s in sources}
        if unknown:
            raise SystemExit(f'Không có nguồn: {", ".join(sorted(unknown))}')
    return picked, skipped


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(paths, source, url, path, partial=False, extra=None):
    record = {
        'source_id': source['id'], 'url': url, 'path': os.path.relpath(path, paths.home),
        'size': os.path.getsize(path) if os.path.isfile(path) else None,
        'sha256': sha256_file(path) if os.path.isfile(path) else None,
        'license': source.get('license'), 'license_status': source.get('license_status'),
        'partial': partial, 'downloaded_at': datetime.datetime.now().isoformat(timespec='seconds'),
    }
    record.update(extra or {})
    os.makedirs(paths.home, exist_ok=True)
    with open(paths.manifest, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    return record


def read_manifest(paths):
    """Latest manifest record per (source_id, path)."""
    latest = {}
    if os.path.exists(paths.manifest):
        with open(paths.manifest, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    latest[(record['source_id'], record['path'])] = record
    return latest
