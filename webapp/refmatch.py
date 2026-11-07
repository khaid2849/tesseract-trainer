"""Suggest the true text of an OCR'd scan line by finding it in reference text (text-layer PDFs, DOCX…).

Candidates come from word trigrams with diacritics stripped, so OCR accent errors (ổ→ồ, Ấ→Á) still hit. The score is
measured on diacritic-free text too: it says "this is the same sentence", independent of how badly OCR read the accents
(those badly-read lines are exactly the valuable ones).
"""
import collections
import re
import unicodedata

WORD_RE = re.compile(r'\S+')
DIGITS_RE = re.compile(r'\d+')
MAX_POSTINGS = 400        # cụm 3 từ quá phổ biến (vd. "theo quy dinh") không giúp định vị → bỏ
CANDIDATES = 3
MIN_WORDS = 3


def fold(word):
    """Lowercase, no diacritics, no surrounding punctuation: the matching key of a word."""
    word = unicodedata.normalize('NFD', word.lower().replace('đ', 'd'))
    word = ''.join(c for c in word if not unicodedata.combining(c))
    return word.strip('.,;:!?()[]{}"\'“”‘’«»…-–—')


def fold_text(text):
    text = unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
    return ''.join(c for c in text if not unicodedata.combining(c))


def distance(a, b):
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def similarity(a, b):
    return 1 - distance(a, b) / max(len(a), len(b), 1)


class ReferenceIndex:
    def __init__(self, texts):
        """texts: iterable of reference documents (str); words never span two documents."""
        self.words = []          # chữ gốc (có dấu)
        self.keys = []           # khoá so khớp
        self.doc_end = []        # vị trí từ cuối cùng của mỗi tài liệu, để cửa sổ không vượt sang tài liệu khác
        for text in texts:
            for word in WORD_RE.findall(unicodedata.normalize('NFC', text)):
                self.words.append(word)
                self.keys.append(fold(word))
            self.doc_end.append(len(self.words))
        postings = collections.defaultdict(list)
        for i in range(len(self.keys) - 2):
            postings[(self.keys[i], self.keys[i + 1], self.keys[i + 2])].append(i)
        self.postings = {k: v for k, v in postings.items() if len(v) <= MAX_POSTINGS}

    def __len__(self):
        return len(self.words)

    def _bounds(self, position):
        start = 0
        for end in self.doc_end:
            if position < end:
                return start, end
            start = end
        return start, len(self.words)

    def match(self, line):
        """(suggested text, score 0..1) or (None, 0.0) when nothing similar exists."""
        words = WORD_RE.findall(line)
        keys = [fold(w) for w in words]
        if len(words) < MIN_WORDS or not self.postings:
            return None, 0.0
        votes = collections.Counter()
        for i in range(len(keys) - 2):
            for position in self.postings.get((keys[i], keys[i + 1], keys[i + 2]), ()):
                votes[position - i] += 1
        best, best_key = None, (0.0, 0.0)
        folded_line = fold_text(line)
        line_digits = DIGITS_RE.findall(line)
        n = len(words)
        for start, _count in votes.most_common(CANDIDATES):
            low, high = self._bounds(max(start, 0))
            for a in (start - 1, start, start + 1):
                for length in (n - 1, n, n + 1):
                    if a < low or length < 1 or a + length > high:
                        continue
                    candidate = ' '.join(self.words[a:a + length])
                    if DIGITS_RE.findall(candidate) != line_digits:
                        continue  # cùng câu mẫu nhưng khác số/ngày (vd. "Căn cứ Nghị định số …") → nhãn sẽ sai số
                    key = (similarity(folded_line, fold_text(candidate)), similarity(line, candidate))
                    if key > best_key:
                        best, best_key = candidate, key
        return best, best_key[0]
