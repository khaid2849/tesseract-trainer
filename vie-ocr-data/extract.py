"""extract: raw downloads → data/text/<source>/part-NNNN.txt (NFC, cleaned, deduplicated, one line per OCR line)."""
import bz2
import glob
import hashlib
import json
import logging
import lzma
import os
import shutil
import subprocess
import tarfile
import time
import xml.etree.ElementTree as ET

from tqdm import tqdm

import textproc

log = logging.getLogger('extract')
PART_LINES = 500_000
FONT_SKIP_WEIGHTS = ('Thin', 'ExtraLight', 'Light', 'Black', 'ExtraBold')  # văn bản thầu/hợp đồng không dùng


class Writer:
    """Streams accepted lines into part files with dedup and a line cap."""

    def __init__(self, folder, max_lines):
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        self.folder = folder
        self.max_lines = max_lines or None
        self.dedup = textproc.Dedup()
        self.count = self.dropped_dup = 0
        self.part = None
        self.started = time.time()

    @property
    def full(self):
        return self.max_lines is not None and self.count >= self.max_lines

    def add_paragraph(self, raw):
        for line in textproc.clean_lines(raw):
            if self.full:
                return
            if not self.dedup.add(line):
                self.dropped_dup += 1
                continue
            if self.count % PART_LINES == 0:
                if self.part:
                    self.part.close()
                self.part = open(os.path.join(self.folder, f'part-{self.count // PART_LINES + 1:04d}.txt'), 'w',
                                 encoding='utf-8')
            self.part.write(line + '\n')
            self.count += 1

    def close(self, extra=None):
        if self.part:
            self.part.close()
        stats = {'lines': self.count, 'duplicates_dropped': self.dropped_dup,
                 'seconds': round(time.time() - self.started), **(extra or {})}
        with open(os.path.join(self.folder, 'stats.json'), 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
        return stats


# ---------------------------------------------------------------- extractors
def _keep_page(title, rate):
    if rate >= 1 or not title:
        return True
    digest = hashlib.blake2b(title.encode('utf-8'), digest_size=4).digest()
    return int.from_bytes(digest, 'big') / 2 ** 32 < rate


def extract_wiki(raw_dir, writer, sample_pages=1.0):
    """MediaWiki XML dump (.bz2): main-namespace pages, no redirects; tolerates a truncated (partial) download.

    sample_pages < 1 keeps a deterministic share of articles spread over the whole dump (not just the first ones).
    """
    pages = 0
    truncated = False
    for path in sorted(glob.glob(os.path.join(raw_dir, '*.xml.bz2'))):
        bar = tqdm(desc=os.path.basename(path)[:40], unit=' trang', mininterval=2)
        try:
            with bz2.open(path, 'rb') as stream:
                ns = title = root = None
                redirect = False
                for event, elem in ET.iterparse(stream, events=('start', 'end')):
                    if event == 'start':
                        if root is None:
                            root = elem
                        continue
                    tag = elem.tag.rsplit('}', 1)[-1]
                    if tag == 'ns':
                        ns = elem.text
                    elif tag == 'redirect':
                        redirect = True
                    elif tag == 'title':
                        title = elem.text
                    elif tag == 'text' and ns == '0' and not redirect and elem.text and _keep_page(title, sample_pages):
                        if title:
                            writer.add_paragraph(title)
                        for paragraph in textproc.strip_wikitext(elem.text).split('\n'):
                            writer.add_paragraph(paragraph)
                    elif tag == 'page':
                        pages += 1
                        bar.update()
                        ns, title, redirect = None, None, False
                        root.clear()  # bỏ các <page> đã xử lý, giữ RAM ổn định với dump hàng triệu trang
                        if writer.full:
                            break
        except (EOFError, ET.ParseError) as error:
            truncated = True
            log.warning('%s: dừng ở trang %s (%s) — file tải một phần?', os.path.basename(path), pages, error)
        bar.close()
    return {'pages': pages, 'truncated': truncated}


def extract_leipzig(raw_dir, writer):
    files = 0
    for path in sorted(glob.glob(os.path.join(raw_dir, '*.tar.gz'))):
        try:
            with tarfile.open(path, 'r|gz') as archive:
                for member in archive:
                    if member.name.endswith('-sentences.txt'):
                        stream = archive.extractfile(member)
                        for raw in tqdm(stream, desc=os.path.basename(member.name)[:40], unit=' câu'):
                            writer.add_paragraph(raw.decode('utf-8', 'replace').split('\t', 1)[-1])
                            if writer.full:
                                break
                        files += 1
        except (EOFError, tarfile.ReadError) as error:
            log.warning('%s: file nén bị cụt (%s)', os.path.basename(path), error)
    return {'files': files}


def _decode(data):
    if data[:2] in (b'\xff\xfe', b'\xfe\xff') or data[1:2] == b'\x00':
        return data.decode('utf-16', 'replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1258', 'replace')


def extract_vntc(raw_dir, writer):
    """VNTC .rar archives → bsdtar (libarchive) extracts, then read each news file (UTF-16 or UTF-8)."""
    out = os.path.join(raw_dir, 'extracted')
    if not os.path.isdir(out):
        os.makedirs(out)
        for path in sorted(glob.glob(os.path.join(raw_dir, '*.rar'))):
            log.info('Giải nén %s', os.path.basename(path))
            subprocess.run(['bsdtar', '-xf', path, '-C', out], check=True)
    files = sorted(p for p in glob.glob(os.path.join(out, '**', '*'), recursive=True) if os.path.isfile(p))
    for path in tqdm(files, desc='vntc', unit=' file'):
        with open(path, 'rb') as f:
            for paragraph in _decode(f.read()).splitlines():
                writer.add_paragraph(paragraph)
        if writer.full:
            break
    return {'files': len(files)}


def extract_cc100(raw_dir, writer):
    """vi.txt.xz streamed with an incremental decompressor so a partial download still yields text."""
    stats = {'truncated': False}
    for path in sorted(glob.glob(os.path.join(raw_dir, '*.xz'))):
        decompressor = lzma.LZMADecompressor()
        rest = b''
        with open(path, 'rb') as f, tqdm(total=os.path.getsize(path), unit='B', unit_scale=True,
                                         desc=os.path.basename(path)) as bar:
            for block in iter(lambda: f.read(1 << 20), b''):
                bar.update(len(block))
                try:
                    data = decompressor.decompress(block)
                except (EOFError, lzma.LZMAError) as error:
                    stats['truncated'] = True
                    log.warning('%s: %s', os.path.basename(path), error)
                    break
                lines = (rest + data).split(b'\n')
                rest = lines.pop()
                for raw in lines:
                    writer.add_paragraph(raw.decode('utf-8', 'replace'))
                if writer.full:
                    break
            if not decompressor.eof:
                stats['truncated'] = True
    return stats


def extract_langdata(raw_dir, writer):
    paths = sorted(glob.glob(os.path.join(raw_dir, '*', '*.training_text')))
    for path in paths:
        with open(path, encoding='utf-8', errors='replace') as f:
            for raw in f:
                writer.add_paragraph(raw)
    return {'files': [os.path.relpath(p, raw_dir) for p in paths]}


def extract_pdf_text(raw_dir, writer):
    """Text-layer pages of PDFs (Công báo…); scanned pages are skipped."""
    import pymupdf
    paths = sorted(glob.glob(os.path.join(raw_dir, '*.pdf')))
    pages = 0
    for path in tqdm(paths, desc='pdf', unit=' file'):
        try:
            document = pymupdf.open(path)
        except Exception as error:  # noqa: BLE001
            log.warning('%s: %s', os.path.basename(path), error)
            continue
        for page in document:
            if page.get_images() and len(page.get_text().strip()) < 400:
                continue
            pages += 1
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    if abs(line['dir'][1]) < 0.01:
                        writer.add_paragraph(''.join(span['text'] for span in line['spans']))
        if writer.full:
            break
    return {'files': len(paths), 'text_pages': pages}


def extract_plain(raw_dir, writer):
    paths = sorted(p for p in glob.glob(os.path.join(raw_dir, '**', '*'), recursive=True)
                   if os.path.isfile(p) and (p.endswith('.txt') or p.endswith('.vi')))
    for path in paths:
        with open(path, encoding='utf-8', errors='replace') as f:
            for raw in f:
                writer.add_paragraph(raw)
                if writer.full:
                    break
    return {'files': len(paths)}


def install_fonts(raw_dir, fonts_dir):
    """Copy upright regular-to-bold .ttf files into data/fonts/ (fresh copy each run)."""
    shutil.rmtree(fonts_dir, ignore_errors=True)
    os.makedirs(fonts_dir)
    copied = 0
    for path in glob.glob(os.path.join(raw_dir, '**', '*.ttf'), recursive=True):
        name = os.path.basename(path)
        if 'Italic' in name or any(w in name for w in FONT_SKIP_WEIGHTS):
            continue
        shutil.copy2(path, os.path.join(fonts_dir, os.path.basename(path)))
        copied += 1
    return copied


EXTRACTORS = {'wiki': extract_wiki, 'leipzig': extract_leipzig, 'vntc': extract_vntc, 'cc100': extract_cc100,
              'langdata': extract_langdata, 'plain': extract_plain, 'pdf_text': extract_pdf_text}


def run(paths, source, max_lines):
    raw_dir = paths.raw_dir(source['id'])
    if not os.path.isdir(raw_dir) or not os.listdir(raw_dir):
        log.warning('%s: chưa tải (data/raw/%s trống) → bỏ qua', source['id'], source['id'])
        return None
    kind = source.get('extractor')
    if kind == 'fonts':
        count = install_fonts(raw_dir, paths.fonts)
        log.info('%s: %s font → %s', source['id'], count, paths.fonts)
        return {'fonts': count}
    if kind not in EXTRACTORS:
        log.info('%s: không có bước trích text', source['id'])
        return None
    writer = Writer(paths.text_dir(source['id']), max_lines)
    options = {'sample_pages': source['sample_pages']} if 'sample_pages' in source else {}
    extra = EXTRACTORS[kind](raw_dir, writer, **options)
    stats = writer.close({'source_id': source['id'], 'license_status': source.get('license_status'),
                          'max_lines': max_lines, **(extra or {})})
    log.info('%s: %s dòng (bỏ %s dòng trùng) → %s', source['id'], stats['lines'], stats['duplicates_dropped'],
             paths.text_dir(source['id']))
    return stats
