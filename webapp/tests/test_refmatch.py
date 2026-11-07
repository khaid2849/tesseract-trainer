"""python -m unittest discover -s tests (từ thư mục webapp)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import refmatch  # noqa: E402

REFERENCE = ('PHẦN I - CĂN CỨ KÝ KẾT HỢP ĐỒNG Căn cứ Luật Thương mại số 36/2005/QH11 ngày 14/06/2005; '
             'Căn cứ Nghị định số 177/2026/NĐ-CP ngày 19 tháng 5 năm 2026 của Chính phủ; '
             'Hôm nay, tại Văn phòng Công ty Cổ phần Xây Lắp và Cơ Điện An Phát, chúng tôi gồm:')


class TestMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = refmatch.ReferenceIndex([REFERENCE, 'Tài liệu khác hoàn toàn không liên quan gì cả'])

    def test_fixes_ocr_diacritics(self):
        text, score = self.index.match('PHÀN I - CĂN CỨ KỶ KÉT HỢP ĐÒNG')
        self.assertEqual(text, 'PHẦN I - CĂN CỨ KÝ KẾT HỢP ĐỒNG')
        self.assertGreaterEqual(score, 0.97)

    def test_line_inside_paragraph(self):
        text, score = self.index.match('Hôm nay, tại Văn phòng Công ty Cô phần Xây Lắp và Cơ Điện An Phát, chúng tôi gồm:')
        self.assertEqual(text, 'Hôm nay, tại Văn phòng Công ty Cổ phần Xây Lắp và Cơ Điện An Phát, chúng tôi gồm:')
        self.assertGreaterEqual(score, 0.97)

    def test_same_template_different_numbers_is_rejected(self):
        text, score = self.index.match('Căn cứ Nghị định số 48/2022/NĐ-CP ngày 26 tháng 7 năm 2022 của Chính phủ;')
        self.assertLess(score, 0.8)

    def test_unknown_or_short_line(self):
        self.assertEqual(self.index.match('Bên B.'), (None, 0.0))
        self.assertLess(self.index.match('Một câu không hề có trong bản chữ tham chiếu nào')[1], 0.8)


if __name__ == '__main__':
    unittest.main()
