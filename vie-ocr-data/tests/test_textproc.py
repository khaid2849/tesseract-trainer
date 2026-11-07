"""python -m unittest discover -s tests (từ thư mục vie-ocr-data)."""
import os
import sys
import unicodedata
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_gt  # noqa: E402
import textproc  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_nfd_becomes_nfc(self):
        nfd = unicodedata.normalize('NFD', 'Hợp đồng mua bán thiết bị y tế')
        self.assertNotEqual(nfd, 'Hợp đồng mua bán thiết bị y tế')
        out = textproc.normalize(nfd)
        self.assertEqual(out, 'Hợp đồng mua bán thiết bị y tế')
        self.assertTrue(unicodedata.is_normalized('NFC', out))

    def test_every_output_line_is_nfc(self):
        raw = unicodedata.normalize('NFD', 'Điều 5. Bên B có trách nhiệm bảo hành thiết bị trong thời hạn 24 tháng.')
        lines = list(textproc.clean_lines(raw))
        self.assertTrue(lines)
        self.assertTrue(all(unicodedata.is_normalized('NFC', line) for line in lines))

    def test_whitespace_and_invisible_chars(self):
        self.assertEqual(textproc.normalize('  Giá trị​  hợp\tđồng \n'), 'Giá trị hợp đồng')


class TestClean(unittest.TestCase):
    def test_drops_urls_and_emails(self):
        lines = list(textproc.clean_lines('Liên hệ phòng kinh doanh qua https://example.com hoặc a.b@example.com nhé'))
        self.assertEqual(lines, ['Liên hệ phòng kinh doanh qua hoặc nhé'])

    def test_length_limits_and_split(self):
        self.assertEqual(list(textproc.clean_lines('Quá ngắn')), [])
        long = 'Bên A thanh toán cho Bên B toàn bộ giá trị hợp đồng ' * 4
        lines = list(textproc.clean_lines(long))
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(textproc.MIN_LEN <= len(line) <= textproc.MAX_LEN for line in lines))

    def test_rejects_non_vietnamese_script(self):
        self.assertEqual(list(textproc.clean_lines('Санкт-Петербург является городом федерального')), [])
        self.assertEqual(list(textproc.clean_lines('Kayıt noktaları satılan ağaçlık çalık şimdi')), [])

    def test_dedup(self):
        dedup = textproc.Dedup()
        self.assertTrue(dedup.add('Hợp đồng số 01/2026'))
        self.assertFalse(dedup.add('Hợp đồng số 01/2026'))


class TestWikitext(unittest.TestCase):
    def test_strip(self):
        text = ("'''Bộ luật Dân sự''' {{Thông tin|a={{b}}}} là [[văn bản|văn bản pháp luật]] [[Tập tin:x.jpg|nhỏ|ảnh]]"
                "<ref>Nguồn</ref> của [[Việt Nam]].[[en:Civil Code]]")
        plain = textproc.normalize(textproc.strip_wikitext(text))
        self.assertEqual(plain, 'Bộ luật Dân sự là văn bản pháp luật của Việt Nam.')


class TestSelection(unittest.TestCase):
    def test_quotas_respect_availability(self):
        share = build_gt.quotas({'a': 10, 'b': 1000}, 100, {})
        self.assertEqual(share['a'], 10)
        self.assertEqual(sum(share.values()), 100)

    def test_quotas_weights(self):
        share = build_gt.quotas({'a': 1000, 'b': 1000}, 100, {'a': 3})
        self.assertEqual(sum(share.values()), 100)
        self.assertGreater(share['a'], share['b'])


if __name__ == '__main__':
    unittest.main()
