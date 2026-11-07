"""Text normalization and cleaning: NFC, markup removal, line length, Vietnamese character filter, dedup."""
import hashlib
import html
import re
import unicodedata

VI_LOWER = ('aàáảãạăằắẳẵặâầấẩẫậbcdđeèéẻẽẹêềếểễệfghiìíỉĩịjklmnoòóỏõọôồốổỗộơờớởỡợpqrstuùúủũụưừứửữựvwxyỳýỷỹỵz')
VI_LETTERS = set(VI_LOWER) | set(VI_LOWER.upper())
# Ký tự có dấu riêng của tiếng Việt: dùng để cân bằng tần suất khi chọn dòng
VI_DIACRITICS = sorted(c for c in VI_LETTERS if unicodedata.decomposition(c) or c in 'đĐ')
ALLOWED = VI_LETTERS | set('0123456789 .,;:!?()[]{}"\'-–—/\\%&+*=<>≤≥±°§@#…“”‘’«»_|~^$€₫×÷')
MIN_LEN, MAX_LEN = 10, 80
MIN_ALLOWED_RATIO = 1.0  # một ký tự lạ trong nhãn (ı, ş, chữ Hán…) là dạy model sai
MIN_LETTER_RATIO = 0.5

URL_RE = re.compile(r'(https?://|www\.)\S+', re.I)
EMAIL_RE = re.compile(r'\S+@\S+\.\w+')
SPACE_RE = re.compile(r'\s+')


def nfc(text):
    return unicodedata.normalize('NFC', text)


def normalize(text):
    """NFC + one-line + collapse whitespace; the single source of truth for every label."""
    text = nfc(text).replace(' ', ' ').replace('​', '').replace('﻿', '')
    return SPACE_RE.sub(' ', text).strip()


def split_long(text, max_len=MAX_LEN):
    """Split at word boundaries into chunks of at most max_len characters (one OCR line each)."""
    chunks, current = [], ''
    for word in text.split(' '):
        if len(word) > max_len:
            continue
        candidate = f'{current} {word}' if current else word
        if len(candidate) > max_len:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def acceptable(line):
    if not MIN_LEN <= len(line) <= MAX_LEN:
        return False
    allowed = sum(c in ALLOWED for c in line)
    letters = sum(c in VI_LETTERS for c in line)
    non_space = len(line) - line.count(' ')
    return allowed / len(line) >= MIN_ALLOWED_RATIO and letters / max(non_space, 1) >= MIN_LETTER_RATIO


def clean_lines(raw):
    """Yield OCR-ready lines from one paragraph of raw text."""
    text = normalize(EMAIL_RE.sub(' ', URL_RE.sub(' ', html.unescape(raw))))
    if len(text) < MIN_LEN:
        return
    for chunk in (split_long(text) if len(text) > MAX_LEN else [text]):
        chunk = chunk.strip()
        if acceptable(chunk):
            yield chunk


class Dedup:
    """Memory-light exact dedup (8-byte digests)."""

    def __init__(self):
        self.seen = set()

    def add(self, line):
        key = hashlib.blake2b(line.encode('utf-8'), digest_size=8).digest()
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


# ---------------------------------------------------------------- wikitext
NAMESPACE_LINK = re.compile(r'^\s*:?\s*(file|image|tập tin|hình|thể loại|category|wikipedia|wp|bản mẫu|template|'
                            r'tác giả|author|trang|page|chỉ mục|index|wikt|wiktionary|commons|'
                            r'[a-z]{2,3}(-[a-z]+)?)\s*:', re.I)
INNER_LINK = re.compile(r'\[\[([^\[\]]*)\]\]')
TEMPLATE = re.compile(r'\{\{[^{}]*\}\}')
TABLE = re.compile(r'\{\|[^{}]*?\|\}', re.S)
WIKI_RE = [
    (re.compile(r'<!--.*?-->', re.S), ' '),
    (re.compile(r'<ref[^>/]*/>', re.I), ' '),
    (re.compile(r'<ref[^>]*>.*?</ref>', re.I | re.S), ' '),
    (re.compile(r'<(math|code|pre|gallery|timeline|score|syntaxhighlight|source|poem)[^>]*>.*?</\1>', re.I | re.S),
     ' '),
    (re.compile(r'\[(?:https?:)?//\S+\s+([^\]]+)\]'), r'\1'),
    (re.compile(r'\[(?:https?:)?//\S+\]'), ' '),
    (re.compile(r'<[^>]+>'), ' '),
    (re.compile(r"'{2,}"), ''),
    (re.compile(r'__[A-ZÀ-Ỹ_]+__'), ' '),
    (re.compile(r'^=+\s*(.*?)\s*=+\s*$', re.M), r'\1'),
    (re.compile(r'^[*#:;]+\s*', re.M), ''),
]


def _link(match):
    inner = match.group(1)
    if NAMESPACE_LINK.match(inner):
        return ' '
    return inner.split('|')[-1]


def strip_wikitext(text):
    """Plain text from MediaWiki markup (good enough for OCR lines; leftovers are dropped by acceptable())."""
    for _ in range(10):  # bản mẫu/bảng/liên kết lồng nhau: gỡ từ trong ra
        new = TABLE.sub(' ', TEMPLATE.sub(' ', text))
        if new == text:
            break
        text = new
    for _ in range(5):
        new = INNER_LINK.sub(_link, text)
        if new == text:
            break
        text = new
    for pattern, repl in WIKI_RE:
        text = pattern.sub(repl, text)
    return text.replace('{{', ' ').replace('}}', ' ').replace('[[', ' ').replace(']]', ' ')
