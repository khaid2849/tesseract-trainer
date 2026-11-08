"""train_job gom dòng (không chạy tesstrain): python -m unittest discover -s tests (từ thư mục webapp)."""
import os
import sys
import tempfile
import unittest

if 'pipeline' not in sys.modules:  # không bao giờ chạy trên thư mục dữ liệu thật
    os.environ['TT_WORK'] = tempfile.mkdtemp(prefix='tt-test-')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline  # noqa: E402


class StopBeforeTesstrain(Exception):
    pass


def add_source(sid, role, n_auto, n_scan):
    folder = os.path.join(pipeline.LINES, sid)
    for sub in ('auto', 'scan'):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    for i in range(n_auto):
        base = os.path.join(folder, 'auto', f'{sid}_a{i:03d}')
        open(base + '.png', 'wb').close()
        with open(base + '.gt.txt', 'w', encoding='utf-8') as f:
            f.write(f'dòng pdf {i}\n')
    with open(os.path.join(folder, 'corpus.txt'), 'w', encoding='utf-8') as f:
        f.write(''.join(f'dòng pdf {i}\n' for i in range(n_auto)))
    pipeline.store.sources[sid] = {'id': sid, 'role': role, 'status': 'done', 'auto_lines': n_auto,
                                   'corpus_lines': n_auto}
    for i in range(n_scan):
        name = f'{sid}_s{i:03d}'
        open(os.path.join(folder, 'scan', name + '.png'), 'wb').close()
        pipeline.store.lines[name] = {'source': sid, 'text': f'dòng scan {i}', 'status': 'approved'}


class TestTrainLines(unittest.TestCase):
    def setUp(self):
        pipeline.store.data = {'sources': {}, 'lines': {}}
        add_source('pdf', 'train', n_auto=300, n_scan=0)
        add_source('scan', 'train', n_auto=0, n_scan=100)
        add_source('held_out', 'eval', n_auto=50, n_scan=50)
        os.makedirs(pipeline.LANGDATA, exist_ok=True)
        for ext in ('wordlist', 'punc', 'numbers'):
            open(os.path.join(pipeline.LANGDATA, f'vie.{ext}'), 'w').close()
        self.saved = pipeline.environment, pipeline.run_cmd
        pipeline.environment = lambda: {'ready': True}

        def stop(*_args, **_kwargs):
            raise StopBeforeTesstrain()
        pipeline.run_cmd = stop

    def tearDown(self):
        pipeline.environment, pipeline.run_cmd = self.saved

    def gather(self, **params):
        job = pipeline.Job('train')
        with self.assertRaises(StopBeforeTesstrain):
            pipeline.train_job(job, dict({'model': 'test_model', 'iterations': 100, 'real_weight': 2}, **params))
        gt_dir = os.path.join(pipeline.TESSTRAIN, 'data', 'test_model-ground-truth')
        names = [n[:-len('.gt.txt')] for n in os.listdir(gt_dir) if n.endswith('.gt.txt')]
        pngs = [n for n in os.listdir(gt_dir) if n.endswith('.png')]
        self.assertEqual(len(names), len(pngs))
        self.assertFalse([n for n in names if n.startswith('held_out')], 'dòng Đánh giá lọt vào train')
        return job.metrics, names

    def test_no_limit_uses_everything(self):
        metrics, names = self.gather(max_lines=0)
        self.assertEqual((metrics['lines_auto'], metrics['lines_scan']), (300, 100))
        self.assertEqual(len(names), 300 + 100 * 2)

    def test_limit_keeps_pdf_scan_ratio(self):
        metrics, names = self.gather(max_lines=250)  # có 300 + 100×2 = 500 → lấy một nửa
        self.assertEqual((metrics['lines_auto'], metrics['lines_scan']), (150, 50))
        self.assertEqual(len(names), 150 + 50 * 2)
        self.assertEqual(metrics, self.gather(max_lines=250)[0], 'lấy mẫu phải lặp lại được')

    def test_limit_above_available_is_noop(self):
        metrics, _names = self.gather(max_lines=80000)
        self.assertEqual((metrics['lines_auto'], metrics['lines_scan']), (300, 100))


if __name__ == '__main__':
    unittest.main()
