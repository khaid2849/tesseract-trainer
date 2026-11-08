"""process_job song song: python -m unittest discover -s tests (từ thư mục webapp). OCR giả, không cần tesseract."""
import io
import os
import sys
import tempfile
import threading
import time
import unittest

import numpy as np
import pymupdf
from PIL import Image

WORK = tempfile.mkdtemp(prefix='tt-test-')
os.environ['TT_WORK'] = WORK
os.environ['TT_OCR_WORKERS'] = '4'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402

os.makedirs(pipeline.START_TESSDATA, exist_ok=True)
open(os.path.join(pipeline.START_TESSDATA, pipeline.START_LANG + '.traineddata'), 'wb').close()


def scan_pdf(pages):
    """PDF with image-only pages (no text layer → treated as scan)."""
    document = pymupdf.open()
    for i in range(pages):
        page = document.new_page(width=200, height=200)
        pixels = np.full((50, 50), 255 - i, np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, 'PNG')
        page.insert_image(page.rect, stream=buffer.getvalue())
    return io.BytesIO(document.tobytes())


class FakeOcr:
    """Stands in for tesseract: a few lines per page, records how many pages run at once."""

    def __init__(self, delay=0.05, on_call=None):
        self.delay, self.on_call = delay, on_call
        self.lock = threading.Lock()
        self.running = self.peak = self.calls = 0

    def prepare(self, gray):
        return gray

    def lines(self, image, lang, with_conf=False, tessdata_dir=None):
        with self.lock:
            self.running += 1
            self.calls += 1
            self.peak = max(self.peak, self.running)
            calls = self.calls
        if self.on_call:
            self.on_call(calls)
        time.sleep(self.delay)
        with self.lock:
            self.running -= 1
        assert os.environ.get('OMP_THREAD_LIMIT') == '1'
        return [(f'Dòng số {i} trang mức {int(image[0, 0])}', (0, 20 * i, 40, 20 * i + 15), 90.0) for i in range(3)]


class TestProcessJob(unittest.TestCase):
    def setUp(self):
        pipeline.store.data = {'sources': {}, 'lines': {}}
        self.saved = pipeline.crop_for_labeling.prepare, pipeline.crop_for_labeling.lines

    def tearDown(self):
        pipeline.crop_for_labeling.prepare, pipeline.crop_for_labeling.lines = self.saved

    def use(self, ocr):
        pipeline.crop_for_labeling.prepare, pipeline.crop_for_labeling.lines = ocr.prepare, ocr.lines

    def test_files_processed_in_parallel_with_same_results(self):
        ocr = FakeOcr()
        self.use(ocr)
        a = pipeline.add_source('a.pdf', scan_pdf(5), 'train')
        b = pipeline.add_source('b.pdf', scan_pdf(3), 'train')
        broken = pipeline.add_source('broken.pdf', io.BytesIO(b'not a pdf'), 'train')
        text = pipeline.add_source('t.txt', io.BytesIO('Một dòng chữ đủ dài để vào corpus\n'.encode()), 'eval')
        job = pipeline.Job('process')
        pipeline.process_job(job)

        sources = pipeline.store.sources
        self.assertEqual(sources[a]['status'], 'done')
        self.assertEqual((sources[a]['pages'], sources[a]['scan_pages'], sources[a]['scan_lines']), (5, 5, 15))
        self.assertEqual(sources[b]['scan_lines'], 9)
        self.assertEqual(sources[broken]['status'], 'error')
        self.assertTrue(sources[broken]['error'])
        self.assertEqual((sources[text]['status'], sources[text]['corpus_lines']), ('done', 1))
        self.assertGreater(ocr.peak, 1)
        self.assertEqual(sorted(n for n in pipeline.store.lines if n.startswith(a)),
                         [f'{a}_p{p}_{i:03d}' for p in range(1, 6) for i in range(3)])
        self.assertEqual(pipeline.store.lines[f'{a}_p3_001']['text'], 'Dòng số 1 trang mức 253')
        self.assertTrue(os.path.exists(os.path.join(pipeline.LINES, a, 'scan', f'{a}_p5_002.png')))
        self.assertNotIn('OMP_THREAD_LIMIT', os.environ)
        self.assertAlmostEqual(job.progress, 1.0)

    def test_stop_leaves_unfinished_files_pending(self):
        job = pipeline.Job('process')

        def stop_after_two(calls):
            if calls == 2:
                job.stop_requested = True
        self.use(FakeOcr(on_call=stop_after_two))
        ids = [pipeline.add_source(f'{n}.pdf', scan_pdf(4), 'train') for n in 'abc']
        with self.assertRaises(pipeline.JobStopped):
            pipeline.process_job(job)
        statuses = {pipeline.store.sources[s]['status'] for s in ids}
        self.assertEqual(statuses, {'pending'})


if __name__ == '__main__':
    unittest.main()
