"""Tesseract fine-tune pipeline: uploaded files → labeled line images → tesstrain → .traineddata."""
import argparse
import concurrent.futures
import contextlib
import functools
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections import deque

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageSequence

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)
import crop_for_labeling  # noqa: E402
import eval_lines  # noqa: E402
import make_gt  # noqa: E402
import refmatch  # noqa: E402

WORK = os.path.expanduser(os.environ.get('TT_WORK', '~/Works/tesseract-train'))
TESSTRAIN = os.path.join(WORK, 'tesstrain')
LANGDATA = os.path.join(TESSTRAIN, 'data', 'langdata')
START_TESSDATA = os.path.join(WORK, 'tessdata_start')  # bản vie "best" làm điểm xuất phát, không đụng thư mục hệ thống
DATA = os.path.join(WORK, 'data')
SOURCES = os.path.join(DATA, 'sources')
LINES = os.path.join(DATA, 'lines')
SYNTH = os.path.join(DATA, 'synth')
MODELS = os.path.join(WORK, 'models')
STORE_FILE = os.path.join(DATA, 'store.json')
# Kho dòng giả lập do vie-ocr-data/vod.py build-gt sinh (Wikipedia, Wikisource…): <...>/train, <...>/eval
VOD_HOME = os.path.expanduser(os.environ.get('VOD_HOME') or os.path.join(WORK, 'vie-ocr-data'))
EXTERNAL_GT = os.path.join(VOD_HOME, 'data', 'ground-truth')
VOD_IMPORT_SOURCES = ('congbao_pairs', 'chinhphu_scan', 'congbao')  # PDF tải bằng vod.sh, nhập thẳng vào app
SUGGEST_MIN = 0.8   # khớp bản chữ (đã bỏ dấu) từ mức này thì điền sẵn chữ của bản chữ thay chữ máy đọc

PY = sys.executable
BIN_PATH = '/opt/homebrew/bin:/usr/local/bin:/usr/bin'
TOOLS = ('tesseract', 'lstmtraining', 'combine_tessdata', 'combine_lang_model', 'unicharset_extractor',
         'merge_unicharsets', 'git', 'curl')
INSTALL_HINT = ('Ubuntu: sudo apt install tesseract-ocr make git curl' if sys.platform.startswith('linux')
                else 'macOS: brew install tesseract make git')
TESSDATA_CANDIDATES = ('/opt/homebrew/share/tessdata', '/usr/local/share/tessdata',
                       '/usr/share/tesseract-ocr/5/tessdata', '/usr/share/tesseract-ocr/4.00/tessdata',
                       '/usr/share/tessdata')
START_LANG = 'vie'
BEST_URL = 'https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata'
LANGDATA_URL = 'https://github.com/tesseract-ocr/langdata_lstm/raw/main'
LANGDATA_FILES = ['radical-stroke.txt', 'Latin.unicharset', 'vie/vie.wordlist', 'vie/vie.punc', 'vie/vie.numbers']
TESSTRAIN_REPO = 'https://github.com/tesseract-ocr/tesstrain.git'
MIN_BEST_SIZE = 8_000_000  # tessdata_fast ~1-2 MB, tessdata_best ~12 MB; chỉ bản best fine-tune được
PDF_EXT = ('.pdf',)
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp')
TEXT_EXT = ('.docx', '.txt')
ALLOWED_EXT = PDF_EXT + IMAGE_EXT + TEXT_EXT
MODEL_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{1,40}$')
ITER_RE = re.compile(r'At iteration (\d+)/(\d+)/(\d+).*?BCER train=([\d.]+)%')
EVAL_RE = re.compile(r'Eval Char error rate=([\d.]+)')
FINISHED_RE = re.compile(r'Finished! Selected model with minimal training error rate \(BCER\) = ([\d.]+)')
# số trang OCR cùng lúc, mỗi trang 1 tiến trình tesseract 1 luồng (~100-200 MB RAM)
OCR_WORKERS = max(1, int(os.environ.get('TT_OCR_WORKERS') or min(os.cpu_count() or 1, 8)))
EVAL_LIMIT = 600  # số dòng tối đa mỗi bộ đánh giá, để 1 lần đo vài phút


def env():
    environ = dict(os.environ)
    environ['PATH'] = BIN_PATH + ':' + environ.get('PATH', '')
    return environ


def slug(text):
    text = unicodedata.normalize('NFKD', text.replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_')[:30] or 'file'


def norm_label(text):
    return make_gt.norm(text or '')


# ---------------------------------------------------------------- store
class Store:
    """sources + scan lines that need human labels, persisted as one JSON file."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {'sources': {}, 'lines': {}}
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                self.data = json.load(f)
        for source in self.data['sources'].values():
            if source['status'] == 'processing':  # app bị tắt giữa chừng: xử lý lại từ đầu file đó
                source['status'] = 'pending'

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)

    @property
    def sources(self):
        return self.data['sources']

    @property
    def lines(self):
        return self.data['lines']


store = Store(STORE_FILE)


# ---------------------------------------------------------------- jobs
class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.status = 'running'
        self.progress = 0.0
        self.message = ''
        self.metrics = {}
        self.log_lines = deque(maxlen=400)
        self.started = time.time()
        self.finished = None
        self.stop_requested = False
        self.proc = None

    def log(self, text):
        for line in str(text).rstrip().splitlines():
            self.log_lines.append(line)

    def step(self, message, progress=None):
        self.message = message
        if progress is not None:
            self.progress = progress
        self.log('» ' + message)

    def check_stop(self):
        if self.stop_requested:
            raise JobStopped()

    def as_dict(self):
        return {
            'id': self.id, 'kind': self.kind, 'status': self.status, 'progress': self.progress,
            'message': self.message, 'metrics': self.metrics, 'log': list(self.log_lines)[-200:],
            'started': self.started, 'finished': self.finished,
        }


class JobStopped(Exception):
    pass


class JobRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = None

    def busy(self):
        return self.current is not None and self.current.status == 'running'

    def start(self, kind, func, *args):
        with self.lock:
            if self.busy():
                raise RuntimeError(f'Đang chạy việc "{self.current.kind}", đợi xong hoặc bấm Dừng.')
            job = self.current = Job(kind)
        threading.Thread(target=self._run, args=(job, func, args), daemon=True).start()
        return job

    def _run(self, job, func, args):
        try:
            func(job, *args)
            job.status = 'done'
            job.progress = 1.0
        except JobStopped:
            job.status = 'stopped'
            job.log('Đã dừng theo yêu cầu.')
        except Exception as error:  # noqa: BLE001
            job.status = 'error'
            job.message = str(error)
            job.log(f'LỖI: {error}')
        finally:
            job.finished = time.time()
            store.save()

    def stop(self):
        job = self.current
        if not job or job.status != 'running':
            return
        job.stop_requested = True
        if job.proc and job.proc.poll() is None:
            os.killpg(job.proc.pid, signal.SIGTERM)


runner = JobRunner()


def run_cmd(job, cmd, cwd=None, on_line=None):
    job.log('$ ' + ' '.join(cmd))
    job.proc = subprocess.Popen(cmd, cwd=cwd, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', start_new_session=True)
    for line in job.proc.stdout:
        job.log(line)
        if on_line:
            on_line(line)
    code = job.proc.wait()
    job.proc = None
    job.check_stop()
    if code:
        raise RuntimeError(f'Lệnh lỗi (mã {code}): {" ".join(cmd[:3])} … — xem nhật ký bên dưới')


# ---------------------------------------------------------------- environment
def make_cmd():
    """GNU Make >= 4.2: macOS cần `gmake` (make hệ thống là 3.81), Linux dùng `make`."""
    for name in ('gmake', 'make'):
        path = shutil.which(name, path=env()['PATH'])
        if not path:
            continue
        out = subprocess.run([path, '--version'], capture_output=True, text=True).stdout
        match = re.search(r'GNU Make (\d+)\.(\d+)', out)
        if match and (int(match.group(1)), int(match.group(2))) >= (4, 2):
            return path
    return None


def tesseract_version():
    out = subprocess.run(['tesseract', '--version'], capture_output=True, text=True, env=env())
    match = re.search(r'tesseract v?(\d+)\.(\d+)\.?(\d*)', out.stdout + out.stderr)
    return tuple(int(x or 0) for x in match.groups()) if match else None


def environment():
    tools = {name: shutil.which(name, path=env()['PATH']) for name in TOOLS}
    tools['make (GNU >= 4.2)'] = make_cmd()
    version = tesseract_version() if tools['tesseract'] else None
    start_model = os.path.join(START_TESSDATA, START_LANG + '.traineddata')
    langdata_ok = all(os.path.exists(os.path.join(LANGDATA, os.path.basename(f))) for f in LANGDATA_FILES)
    checks = [
        {'key': 'tools', 'label': 'Tesseract + công cụ train (lstmtraining, combine_lang_model…), GNU make, git, curl',
         'ok': all(tools.values()),
         'hint': '' if all(tools.values()) else
         'Thiếu: ' + ', '.join(k for k, v in tools.items() if not v) + ' → ' + INSTALL_HINT},
        {'key': 'version', 'label': 'Tesseract 5.x' + (f' (đang có {".".join(map(str, version))})' if version else ''),
         'ok': bool(version and version[0] >= 5), 'warn_only': True,
         'hint': '' if version and version[0] >= 5 else
         'Bản 4.x train được nhưng nên dùng 5.x cho khớp server. Ubuntu 22.04: '
         'sudo add-apt-repository ppa:alex-p/tesseract-ocr5 && sudo apt install tesseract-ocr'},
        {'key': 'tesstrain', 'label': 'Bộ công cụ tesstrain',
         'ok': os.path.exists(os.path.join(TESSTRAIN, 'Makefile')), 'hint': ''},
        {'key': 'langdata', 'label': 'Dữ liệu ngôn ngữ tiếng Việt (wordlist, dấu câu, số)',
         'ok': langdata_ok, 'hint': ''},
        {'key': 'start_model', 'label': 'Model vie bản "best" làm điểm xuất phát',
         'ok': os.path.exists(start_model) and os.path.getsize(start_model) > MIN_BEST_SIZE, 'hint': ''},
        {'key': 'fonts', 'label': 'Font có dấu tiếng Việt để sinh dòng giả lập', 'ok': bool(fonts()),
         'hint': '' if fonts() else 'Ubuntu: sudo apt install fonts-liberation fonts-dejavu-core, rồi chạy lại app'},
    ]
    ready = all(c['ok'] for c in checks if not c.get('warn_only'))
    return {'ready': ready, 'checks': checks, 'work_dir': WORK, 'models_dir': MODELS}


@functools.lru_cache(maxsize=1)
def fonts():
    return tuple(make_gt._fonts())


def setup_job(job):
    """Clone tesstrain, download Vietnamese langdata and the vie 'best' start model (only what is missing)."""
    status = {c['key']: c['ok'] for c in environment()['checks']}
    if not status['tools']:
        raise RuntimeError('Thiếu công cụ hệ thống. ' + INSTALL_HINT)
    os.makedirs(WORK, exist_ok=True)
    if not status['tesstrain']:
        job.step('Tải tesstrain (git clone)', 0.1)
        run_cmd(job, ['git', 'clone', '--depth', '1', TESSTRAIN_REPO, TESSTRAIN])
    if not status['langdata']:
        os.makedirs(LANGDATA, exist_ok=True)
        for i, name in enumerate(LANGDATA_FILES):
            job.step(f'Tải langdata {name}', 0.3 + 0.1 * i)
            _download(job, f'{LANGDATA_URL}/{name}', os.path.join(LANGDATA, os.path.basename(name)))
    if not status['start_model']:
        os.makedirs(START_TESSDATA, exist_ok=True)
        target = os.path.join(START_TESSDATA, START_LANG + '.traineddata')
        system = os.path.join(system_tessdata(), START_LANG + '.traineddata')
        if os.path.exists(system) and os.path.getsize(system) > MIN_BEST_SIZE:
            job.step('Chép vie.traineddata (best) từ thư mục Tesseract của máy', 0.9)
            shutil.copy2(system, target)
        else:
            job.step('Tải vie.traineddata bản best (~12 MB)', 0.9)
            _download(job, BEST_URL, target)
    if not status['fonts']:
        job.log('Không tìm thấy font Times New Roman/Arial… có dấu: sẽ không sinh được dòng giả lập.')
    job.step('Môi trường sẵn sàng', 1.0)


def _download(job, url, path):
    # curl dùng kho chứng chỉ của macOS; urllib của Python.org thường thiếu chứng chỉ
    tmp = path + '.part'
    run_cmd(job, ['curl', '-fsSL', '--retry', '2', '-o', tmp, url])
    os.replace(tmp, path)


def system_tessdata():
    out = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, env=env()).stdout
    match = re.search(r'"(.+?)"', out)  # Tesseract 4.x không in đường dẫn
    if match:
        return match.group(1)
    return next((d for d in TESSDATA_CANDIDATES if os.path.isdir(d)), TESSDATA_CANDIDATES[0])


# ---------------------------------------------------------------- sources
def add_source(filename, stream, role):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f'{filename}: không hỗ trợ đuôi {ext} (nhận {", ".join(ALLOWED_EXT)})')
    sid = f'{slug(os.path.splitext(filename)[0])}_{uuid.uuid4().hex[:6]}'
    os.makedirs(SOURCES, exist_ok=True)
    path = os.path.join(SOURCES, sid + ext)
    with open(path, 'wb') as f:
        shutil.copyfileobj(stream, f)
    with store.lock:
        store.sources[sid] = {
            'id': sid, 'name': filename, 'file': os.path.basename(path), 'ext': ext, 'role': role,
            'status': 'pending', 'error': '', 'pages': 0, 'digital_pages': 0, 'scan_pages': 0,
            'auto_lines': 0, 'scan_lines': 0, 'corpus_lines': 0, 'added': time.time(),
        }
        store.save()
    return sid


def delete_source(sid):
    with store.lock:
        source = store.sources.pop(sid, None)
        if not source:
            return
        for name in [n for n, line in store.lines.items() if line['source'] == sid]:
            del store.lines[name]
        store.save()
    shutil.rmtree(os.path.join(LINES, sid), ignore_errors=True)
    path = os.path.join(SOURCES, source['file'])
    if os.path.exists(path):
        os.remove(path)


def process_job(job):
    """Process pending sources. The job thread opens/renders pages (pymupdf is not thread-safe) and hands each scan
    page to a pool of OCR_WORKERS threads, each driving its own single-threaded tesseract process; it moves on to
    the next page/file without waiting, so pages of several files are OCR'd at once."""
    pending = [s for s in store.sources.values() if s['status'] in ('pending', 'error')]
    if pending and not os.path.exists(os.path.join(START_TESSDATA, START_LANG + '.traineddata')):
        raise RuntimeError('Chưa có model vie để đọc nháp bản scan: vào tab "1. Môi trường" bấm "Cài đặt tự động", '
                           'rồi bấm "Xử lý lại file lỗi / đang chờ"')
    if not pending:
        job.step('Không có file nào đang chờ xử lý', 1.0)
        return
    job.step(f'Xử lý {len(pending)} file, OCR song song {OCR_WORKERS} trang một lúc', 0.0)
    batch = _Batch(job, sum(_unit_count(s) for s in pending))
    tasks = batch.tasks
    with _single_thread_tesseract():
        try:
            for i, source in enumerate(pending):
                job.check_stop()
                job.log(f'» Đọc {source["name"]} ({i + 1}/{len(pending)})')
                task = _FileTask(source)
                tasks.append(task)
                try:
                    _submit_source(batch, task)
                except JobStopped:
                    raise
                except Exception as error:  # noqa: BLE001
                    task.error = error
                task.submitted = True
                batch.finish_ready()
            while not batch.finish_ready():
                job.check_stop()
                running = [f for f in batch.futures if not f.done()]
                concurrent.futures.wait(running, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED)
        finally:
            batch.shutdown()
            with store.lock:
                for task in tasks:
                    if not task.finished:  # dừng giữa chừng: làm lại từ đầu file đó ở lần sau
                        task.source['status'] = 'pending'
            store.save()
    job.step(f'Xong {len(pending)} file', 0.97)
    match_job(job, progress_from=0.97)


@contextlib.contextmanager
def _single_thread_tesseract():
    """N tesseract processes each spawning OpenMP threads fight over the cores; one thread each is fastest."""
    old = os.environ.get('OMP_THREAD_LIMIT')
    os.environ['OMP_THREAD_LIMIT'] = '1'
    try:
        yield
    finally:
        if old is None:
            os.environ.pop('OMP_THREAD_LIMIT', None)
        else:
            os.environ['OMP_THREAD_LIMIT'] = old


def _unit_count(source):
    """Pages of a source (for the progress bar); DOCX/TXT count as one."""
    path = os.path.join(SOURCES, source['file'])
    try:
        if source['ext'] in PDF_EXT:
            with pymupdf.open(path) as document:
                return len(document)
        if source['ext'] in IMAGE_EXT:
            with Image.open(path) as image:
                return getattr(image, 'n_frames', 1)
    except Exception:  # noqa: BLE001 — file hỏng: báo lỗi lúc xử lý thật
        pass
    return 1


class _FileTask:
    def __init__(self, source):
        self.source = source
        self.sid = source['id']
        self.folder = os.path.join(LINES, self.sid)
        self.counts = dict(pages=0, digital_pages=0, scan_pages=0, auto_lines=0, scan_lines=0)
        self.corpus = []
        self.futures = []
        self.lock = threading.Lock()
        self.error = None
        self.submitted = False  # job thread đã đọc hết trang, chỉ còn chờ OCR
        self.finished = False


class _Batch:
    """OCR thread pool shared by all files of one process_job, with progress accounting."""

    def __init__(self, job, total_units):
        self.job = job
        self.total = max(total_units, 1)
        self.done_units = 0
        self.done_files = 0
        self.lock = threading.Lock()
        self.pool = concurrent.futures.ThreadPoolExecutor(OCR_WORKERS, thread_name_prefix='ocr')
        # giới hạn số trang đã render chờ OCR (mỗi trang ~9 MB) để job thread không chạy quá xa
        self.slots = threading.Semaphore(OCR_WORKERS * 2)
        self.futures = set()
        self.tasks = []

    def unit_done(self):
        with self.lock:
            self.done_units += 1
            self.job.progress = 0.97 * min(self.done_units / self.total, 1)
            self.job.message = f'Đã xử lý {self.done_units}/{self.total} trang, xong {self.done_files} file'

    def submit(self, task, func, *args):
        while not self.slots.acquire(timeout=0.5):
            self.job.check_stop()
            self.finish_ready()  # file trước xong OCR thì báo xong ngay, không đợi file này đọc hết
        future = self.pool.submit(func, *args)
        future.add_done_callback(lambda _f: self.slots.release())
        task.futures.append(future)
        self.futures.add(future)

    def finish_ready(self):
        """Finalize (in the job thread) every file whose pages are all done; True when all files are finished."""
        for task in self.tasks:
            if task.finished or not task.submitted or not all(f.done() for f in task.futures):
                continue
            for future in task.futures:
                self.futures.discard(future)
                if not future.cancelled() and future.exception() and not task.error:
                    task.error = future.exception()
            if isinstance(task.error, JobStopped):
                raise JobStopped()
            _finish_source(self.job, task)
            task.finished = True
            self.done_files += 1
        return all(task.finished for task in self.tasks)

    def shutdown(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


def _submit_source(batch, task):
    """Read one source in the job thread: text pages are done here, scan pages go to the OCR pool."""
    job, source, sid, folder, counts = batch.job, task.source, task.sid, task.folder, task.counts
    with store.lock:
        source.update(status='processing', error='')
        for name in [n for n, line in store.lines.items() if line['source'] == sid]:
            del store.lines[name]
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(os.path.join(folder, 'auto'))
    os.makedirs(os.path.join(folder, 'scan'))
    path = os.path.join(SOURCES, source['file'])
    rng = random.Random(sid)

    if source['ext'] == '.docx':
        task.corpus = list(make_gt._docx_lines(path))
        batch.unit_done()
    elif source['ext'] == '.txt':
        with open(path, encoding='utf-8', errors='replace') as f:
            task.corpus = f.read().splitlines()
        batch.unit_done()
    elif source['ext'] in PDF_EXT:
        with pymupdf.open(path) as document:
            counts['pages'] = len(document)
            for page in document:
                job.check_stop()
                if page_kind(page) == 'digital':
                    counts['digital_pages'] += 1
                    for line_index, image, text in make_gt.page_samples(page, rng):
                        name = f'{sid}_p{page.number + 1}_{line_index:03d}'
                        make_gt._save(os.path.join(folder, 'auto'), name, image, text)
                        task.corpus.append(text)
                        counts['auto_lines'] += 1
                    batch.unit_done()
                else:
                    counts['scan_pages'] += 1
                    batch.submit(task, _ocr_page, batch, task, page.number + 1, crop_for_labeling.render_gray(page))
    else:
        for number, gray in enumerate(_image_pages(path), 1):
            job.check_stop()
            counts['pages'] = number
            counts['scan_pages'] += 1
            batch.submit(task, _ocr_page, batch, task, number, gray)


def _ocr_page(batch, task, number, gray):
    """Runs in an OCR worker thread: straighten + binarize (OSD) and cut the page into labeled lines."""
    batch.job.check_stop()
    found = _scan_page(task.sid, task.folder, number, crop_for_labeling.prepare(gray))
    with task.lock:
        task.counts['scan_lines'] += found
    batch.unit_done()


def _finish_source(job, task):
    source, counts = task.source, task.counts
    if task.error:
        with store.lock:
            source.update(status='error', error=str(task.error))
        job.log(f'LỖI {source["name"]}: {task.error}')
        store.save()
        return
    corpus = [norm_label(line) for line in task.corpus]
    corpus = [line for line in corpus if len(line) >= make_gt.MIN_CHARS]
    with open(os.path.join(task.folder, 'corpus.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(corpus) + ('\n' if corpus else ''))
    with store.lock:
        source.update(counts, corpus_lines=len(corpus), status='done')
    job.log(f'{source["name"]}: {counts["pages"]} trang ({counts["digital_pages"]} có lớp chữ, '
            f'{counts["scan_pages"]} scan) → {counts["auto_lines"]} dòng tự gán nhãn, '
            f'{counts["scan_lines"]} dòng scan chờ duyệt, {len(corpus)} dòng corpus')
    store.save()


def page_kind(page):
    """'digital' when the page has visible text; invisible text (OCR layer of a scan) counts as 'scan'."""
    visible = 0
    for span in page.get_texttrace():
        if span.get('type') != 3 and span.get('opacity', 1) > 0:
            visible += sum(1 for c in span['chars'] if chr(c[0]).strip())
    return 'digital' if visible >= 20 else 'scan'


def _image_pages(path):
    """Yield 300 DPI grayscale arrays for each frame of an image file (multi-page TIFF included)."""
    with Image.open(path) as image:
        for frame in ImageSequence.Iterator(image):
            gray = np.asarray(frame.convert('L'))
            dpi = (frame.info.get('dpi') or (300, 300))[0]
            if dpi and 72 <= dpi and abs(dpi - 300) > 30:
                gray = cv2.resize(gray, None, fx=300 / dpi, fy=300 / dpi, interpolation=cv2.INTER_CUBIC)
            yield np.ascontiguousarray(gray)


def _scan_page(sid, folder, number, image):
    found = {}
    for index, (text, (x0, y0, x1, y1), conf) in enumerate(
            crop_for_labeling.lines(image, START_LANG, with_conf=True, tessdata_dir=START_TESSDATA)):
        text = norm_label(text)
        if y1 - y0 < 12 or len(text) < 2 or not any(c.isalnum() for c in text):
            continue
        pad = crop_for_labeling.PAD
        crop = image[max(y0 - pad, 0):y1 + pad, max(x0 - pad, 0):x1 + pad]
        name = f'{sid}_p{number}_{index:03d}'
        cv2.imwrite(os.path.join(folder, 'scan', name + '.png'), crop)
        _write_gt(os.path.join(folder, 'scan', name), text)
        found[name] = {'source': sid, 'page': number, 'ocr': text, 'text': text,
                       'conf': round(conf, 1), 'status': 'todo'}
    # OCR mất vài giây mỗi trang: chỉ khoá lúc ghi, nếu không giao diện không đọc được trạng thái suốt lúc xử lý
    with store.lock:
        store.lines.update(found)
    return len(found)


def _write_gt(base, text):
    with open(base + '.gt.txt', 'w', encoding='utf-8') as f:
        f.write(text + '\n')


# ---------------------------------------------------------------- labeling
def list_lines(source=None, status=None, sort='conf', offset=0, limit=30):
    with store.lock:
        items = [dict(line, name=name) for name, line in store.lines.items()
                 if (not source or line['source'] == source) and (not status or line['status'] == status)]
    if sort == 'conf':
        items.sort(key=lambda x: (x['conf'], x['name']))
    elif sort == 'ref':
        items.sort(key=lambda x: (-x.get('ref_score', 0), x['name']))
    else:
        items.sort(key=lambda x: (x['source'], x['page'], x['name']))
    return {'total': len(items), 'items': items[offset:offset + limit]}


def update_line(name, text=None, status=None):
    with store.lock:
        line = store.lines[name]
        if text is not None:
            text = norm_label(text)
            if not text and status == 'approved':
                raise ValueError('Dòng trống: bấm "Bỏ dòng" thay vì duyệt')
            line['text'] = text
            _write_gt(os.path.join(LINES, line['source'], 'scan', name), text)
        if status:
            if status not in ('todo', 'approved', 'rejected'):
                raise ValueError(status)
            line['status'] = status
        store.save()
        return dict(line, name=name)


def reference_index():
    """All text-layer content in the app (Word/PDF/Công báo/DOCX/TXT sources) as one searchable reference library."""
    texts = []
    with store.lock:
        sources = [s for s in store.sources.values() if s['status'] == 'done' and s.get('corpus_lines')]
    for source in sources:
        path = os.path.join(LINES, source['id'], 'corpus.txt')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                texts.append(' '.join(f.read().split('\n')))
    return refmatch.ReferenceIndex(texts), len(sources)


def match_job(job, progress_from=0.0):
    """Fill un-reviewed scan lines with the matching sentence from the reference library (keeps OCR if no match)."""
    index, n_sources = reference_index()
    with store.lock:
        todo = [(n, line) for n, line in store.lines.items() if line['status'] == 'todo']
    if not len(index) or not todo:
        job.log('Khớp bản chữ: chưa có file có lớp chữ nào làm bản chữ' if not len(index) else
                'Khớp bản chữ: không có dòng nào chưa duyệt')
        return
    job.step(f'Khớp {len(todo)} dòng scan với bản chữ ({n_sources} file, {len(index):,} từ)', progress_from)
    found = 0
    for i, (name, line) in enumerate(todo):
        if i % 200 == 0:
            job.check_stop()
            job.progress = progress_from + (1 - progress_from) * i / len(todo)
        ref, score = index.match(line['ocr'])
        with store.lock:
            if line['status'] != 'todo':  # người dùng vừa duyệt trong lúc chạy
                continue
            line['ref'], line['ref_score'] = ref, round(score, 3)
            text = ref if ref and score >= SUGGEST_MIN else line['ocr']
            if text != line['text']:
                line['text'] = text
                _write_gt(os.path.join(LINES, line['source'], 'scan', name), text)
            found += score >= SUGGEST_MIN
    store.save()
    job.metrics['matched'] = found
    job.step(f'Khớp bản chữ: {found}/{len(todo)} dòng được điền sẵn chữ đúng', 1.0)


def approve_matched(min_score, dry_run=True):
    """Approve un-reviewed lines whose suggestion came from the reference text with at least min_score."""
    with store.lock:
        names = [n for n, line in store.lines.items() if line['status'] == 'todo'
                 and line.get('ref') and line.get('ref_score', 0) >= min_score and line['text'] == line['ref']]
        if not dry_run:
            for name in names:
                store.lines[name]['status'] = 'approved'
            store.save()
    return len(names)


def vod_files():
    """PDFs downloaded by vie-ocr-data (government scans, Official Gazette) not imported into the app yet."""
    with store.lock:
        imported = {s.get('origin') for s in store.sources.values()}
    out = {}
    for source_id in VOD_IMPORT_SOURCES:
        folder = os.path.join(VOD_HOME, 'data', 'raw', source_id)
        titles = {}
        index_file = os.path.join(folder, 'index.jsonl')
        if os.path.exists(index_file):
            with open(index_file, encoding='utf-8') as f:
                for record in map(json.loads, f):
                    for item in record.get('files', []):
                        titles[item['file']] = record.get('title') or item['file']
        pairs_file = os.path.join(folder, 'pairs.jsonl')
        if os.path.exists(pairs_file):  # cặp scan ↔ Công báo: bản scan và bản chữ cùng được nhập
            with open(pairs_file, encoding='utf-8') as f:
                for pair in map(json.loads, f):
                    for name in pair['scan_files']:
                        titles[name] = f'[scan] {pair["title"]}'
                    titles[pair['reference_file']] = f'[Công báo] {pair["title"]}'
        files = []
        if os.path.isdir(folder):
            for root, _dirs, names in os.walk(folder):
                files += [os.path.relpath(os.path.join(root, n), folder) for n in names if n.endswith('.pdf')]
        out[source_id] = [{'path': os.path.join(folder, n), 'title': titles.get(n, n)} for n in sorted(files)
                          if os.path.join(folder, n) not in imported]
    return out


def import_vod(role):
    added = []
    for items in vod_files().values():
        for item in items:
            with open(item['path'], 'rb') as f:
                sid = add_source(item['title'][:90] + '.pdf', f, role)
            with store.lock:
                store.sources[sid]['origin'] = item['path']
            added.append(sid)
    store.save()
    return added


def external_lines(split):
    """PNG paths (with a .gt.txt beside) in the vie-ocr-data ground-truth split."""
    folder = os.path.join(EXTERNAL_GT, split)
    if not os.path.isdir(folder):
        return []
    names = {e.name for e in os.scandir(folder)}
    return sorted(os.path.join(folder, n) for n in names if n.endswith('.png') and n[:-4] + '.gt.txt' in names)


def counts():
    by_status = {'todo': 0, 'approved': 0, 'rejected': 0, 'suggested': 0}
    split = {'train': {'auto': 0, 'scan': 0, 'corpus': 0}, 'eval': {'auto': 0, 'scan': 0, 'corpus': 0}}
    with store.lock:
        for line in store.lines.values():
            by_status[line['status']] += 1
            by_status['suggested'] += line['status'] == 'todo' and line.get('ref_score', 0) >= SUGGEST_MIN
            source = store.sources.get(line['source'])
            if source and line['status'] == 'approved':
                split[source['role']]['scan'] += 1
        for source in store.sources.values():
            split[source['role']]['auto'] += source.get('auto_lines', 0)
            split[source['role']]['corpus'] += source.get('corpus_lines', 0)
    external = {'train': len(external_lines('train')), 'eval': len(external_lines('eval')), 'dir': EXTERNAL_GT}
    vod = {k: len(v) for k, v in vod_files().items()}
    return {'labels': by_status, 'split': split, 'default_synth': default_synth(split['train']), 'external': external,
            'vod_import': vod}


def default_synth(train):
    if not train['corpus'] and not train['scan']:
        return 0
    return int(min(8000, max(500, train['auto'] * 0.4)))


# ---------------------------------------------------------------- training
def train_job(job, params):
    model = params['model']
    if not MODEL_NAME_RE.match(model) or model in ('vie', 'eng', 'osd'):
        raise ValueError('Tên model chỉ gồm chữ thường, số, gạch dưới; bắt đầu bằng chữ; không trùng vie/eng/osd')
    if not environment()['ready']:
        raise RuntimeError('Môi trường chưa sẵn sàng: vào tab "1. Môi trường" bấm Cài đặt')
    iterations = int(params.get('iterations') or 10000)
    synth_count = int(params.get('synth') or 0)
    real_weight = max(1, int(params.get('real_weight') or 2))

    data_dir = os.path.join(TESSTRAIN, 'data')
    gt_dir = os.path.join(data_dir, f'{model}-ground-truth')
    out_dir = os.path.join(data_dir, model)
    job.step('Dọn lần train cũ cùng tên model', 0.01)
    for path in (gt_dir, out_dir, os.path.join(data_dir, START_LANG)):
        shutil.rmtree(path, ignore_errors=True)
    if os.path.exists(out_dir + '.traineddata'):
        os.remove(out_dir + '.traineddata')
    os.makedirs(gt_dir)
    os.makedirs(out_dir)

    job.step('Gom dòng từ PDF có lớp chữ và dòng scan đã duyệt', 0.03)
    train_sources = [s for s in store.sources.values() if s['role'] == 'train' and s['status'] == 'done']
    n_auto = n_scan = 0
    corpus = []
    for source in train_sources:
        folder = os.path.join(LINES, source['id'])
        for name in os.listdir(os.path.join(folder, 'auto')):
            _link(os.path.join(folder, 'auto', name), os.path.join(gt_dir, name))
        n_auto += source['auto_lines']
        with open(os.path.join(folder, 'corpus.txt'), encoding='utf-8') as f:
            corpus += f.read().splitlines()
    with store.lock:
        approved = [(n, line) for n, line in store.lines.items() if line['status'] == 'approved'
                    and store.sources.get(line['source'], {}).get('role') == 'train']
    for name, line in approved:
        corpus.append(line['text'])
        base = os.path.join(LINES, line['source'], 'scan', name)
        for copy in range(real_weight):  # dòng scan thật hiếm nên nhân bản để nặng ký hơn dòng giả lập
            target = os.path.join(gt_dir, f'{name}_w{copy}')
            _link(base + '.png', target + '.png')
            _write_gt(target, line['text'])
        n_scan += 1

    n_synth = 0
    if synth_count and corpus:
        job.step(f'Sinh {synth_count} dòng giả lập từ corpus ({len(corpus)} dòng)', 0.05)
        shutil.rmtree(SYNTH, ignore_errors=True)
        os.makedirs(SYNTH)
        corpus_file = os.path.join(SYNTH, 'corpus.txt')
        with open(corpus_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sorted(set(corpus))) + '\n')
        make_gt.text_cmd(argparse.Namespace(corpus=corpus_file, output=SYNTH, count=synth_count, seed=7))
        for name in os.listdir(SYNTH):
            if name.startswith('syn_'):
                _link(os.path.join(SYNTH, name), os.path.join(gt_dir, name))
        n_synth = synth_count

    external = external_lines('train')
    wanted = params.get('external')
    n_external = len(external) if wanted in (None, '') else min(int(wanted), len(external))
    if n_external:
        job.step(f'Thêm {n_external} dòng từ kho vie-ocr-data', 0.07)
        for png in random.Random(7).sample(external, n_external):
            base = os.path.basename(png)[:-4]
            _link(png, os.path.join(gt_dir, base + '.png'))
            _link(png[:-4] + '.gt.txt', os.path.join(gt_dir, base + '.gt.txt'))
    total = n_auto + n_scan * real_weight + n_synth + n_external
    job.metrics.update(lines_auto=n_auto, lines_scan=n_scan, lines_synth=n_synth, lines_external=n_external,
                       lines_total=total, iterations=iterations)
    job.log(f'Dữ liệu train: {n_auto} dòng PDF có lớp chữ + {n_scan} dòng scan đã duyệt (×{real_weight}) '
            f'+ {n_synth} dòng giả lập + {n_external} dòng kho vie-ocr-data = {total} dòng')
    if total < 50:
        raise RuntimeError(f'Chỉ có {total} dòng train, quá ít. Thêm file hoặc duyệt thêm dòng scan '
                           '(tối thiểu vài trăm).')

    for ext in ('wordlist', 'punc', 'numbers'):
        shutil.copy(os.path.join(LANGDATA, f'vie.{ext}'), os.path.join(out_dir, f'{model}.{ext}'))

    job.step('Dựng file .lstmf rồi train (lstmtraining)', 0.08)
    started = time.time()

    def on_line(line):
        match = ITER_RE.search(line)
        if match:
            done = int(match.group(2))
            job.metrics['iteration'] = done
            job.metrics['bcer_train'] = float(match.group(4))
            job.metrics.setdefault('bcer_history', []).append([done, float(match.group(4))])
            job.progress = 0.1 + 0.85 * min(done / iterations, 1)
            elapsed = time.time() - started
            job.message = f'Vòng {done}/{iterations} — lỗi ký tự (train) {match.group(4)}%'
            if done:
                job.metrics['eta_sec'] = int(elapsed / done * max(iterations - done, 0))
        match = EVAL_RE.search(line)
        if match:
            job.metrics['cer_eval_internal'] = float(match.group(1))
        match = FINISHED_RE.search(line)
        if match:  # model xuất ra là checkpoint tốt nhất, không phải vòng cuối
            job.metrics['bcer_train'] = float(match.group(1))

    run_cmd(job, [
        make_cmd(), f'-j{os.cpu_count() or 4}', 'training',
        f'MODEL_NAME={model}', f'START_MODEL={START_LANG}', f'TESSDATA={START_TESSDATA}', f'PY_CMD={PY}',
        'TESSERACT_LANGDATA=data/langdata/radical-stroke.txt data/langdata/Latin.unicharset',
        f'MAX_ITERATIONS={iterations}', 'RATIO_TRAIN=0.95',
    ], cwd=TESSTRAIN, on_line=on_line)

    job.step('Xuất model (best + fast)', 0.96)
    os.makedirs(MODELS, exist_ok=True)
    shutil.copy2(out_dir + '.traineddata', os.path.join(MODELS, f'{model}.traineddata'))
    run_cmd(job, ['lstmtraining', '--stop_training', '--convert_to_int',
                  '--continue_from', os.path.join(out_dir, 'checkpoints', f'{model}_checkpoint'),
                  '--traineddata', os.path.join(out_dir, f'{model}.traineddata'),
                  '--model_output', os.path.join(MODELS, f'{model}_fast.traineddata')], cwd=TESSTRAIN)
    meta = {'model': model, 'created': time.time(), 'duration_sec': int(time.time() - job.started),
            'train': {k: v for k, v in job.metrics.items() if k != 'bcer_history'}, 'eval': {}}
    _save_meta(model, meta)
    job.log(f'Model: {MODELS}/{model}.traineddata và {model}_fast.traineddata')

    if eval_sets():
        evaluate_job(job, model, progress_from=0.97)


def _link(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ---------------------------------------------------------------- evaluation
def eval_sets():
    """{'scan': [png...], 'pdf': [png...]} from sources marked 'eval' (never used for training)."""
    sets = {'scan': [], 'pdf': [], 'ext': external_lines('eval')}
    with store.lock:
        eval_ids = {sid for sid, s in store.sources.items() if s['role'] == 'eval' and s['status'] == 'done'}
        for name, line in sorted(store.lines.items()):
            if line['source'] in eval_ids and line['status'] == 'approved':
                sets['scan'].append(os.path.join(LINES, line['source'], 'scan', name + '.png'))
    for sid in sorted(eval_ids):
        folder = os.path.join(LINES, sid, 'auto')
        sets['pdf'] += sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith('.png'))
    rng = random.Random(0)
    for key in sets:
        if len(sets[key]) > EVAL_LIMIT:
            sets[key] = sorted(rng.sample(sets[key], EVAL_LIMIT))
    return {k: v for k, v in sets.items() if v}


def evaluate_job(job, model, progress_from=0.0):
    sets = eval_sets()
    if not sets:
        raise RuntimeError('Chưa có bộ đánh giá: đánh dấu ít nhất 1 file là "Đánh giá" (và duyệt dòng scan của nó)')
    candidates = [(START_LANG + ' (gốc)', START_LANG, START_TESSDATA),
                  (model, model, MODELS), (model + '_fast', model + '_fast', MODELS)]
    candidates = [c for c in candidates if os.path.exists(os.path.join(c[2], c[1] + '.traineddata'))]
    results = {}
    steps = len(sets) * len(candidates)
    done = 0
    for set_name, files in sets.items():
        results[set_name] = {'lines': len(files), 'models': {}}
        for label, lang, tessdata in candidates:
            job.check_stop()
            job.step(f'Đo {label} trên {len(files)} dòng {set_name}',
                     progress_from + (1 - progress_from) * done / steps)
            result = eval_lines.evaluate(files, lang, f'--oem 1 --psm 7 --tessdata-dir {tessdata}')
            result['confusions'] = [[a, b, n] for (a, b), n in result['confusions']]
            results[set_name]['models'][label] = result
            job.log(f'  {label}: CER {result["CER"]:.2%}, WER {result["WER"]:.2%}, dòng đúng {result["exact"]:.1%}')
            done += 1
    meta = load_meta(model) or {'model': model}
    meta['eval'] = results
    meta['evaluated'] = time.time()
    _save_meta(model, meta)
    job.metrics['eval'] = results


def _save_meta(model, meta):
    os.makedirs(MODELS, exist_ok=True)
    with open(os.path.join(MODELS, f'{model}.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def load_meta(model):
    path = os.path.join(MODELS, f'{model}.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def list_models():
    if not os.path.isdir(MODELS):
        return []
    out = []
    for name in sorted(os.listdir(MODELS)):
        if not name.endswith('.json'):
            continue
        meta = load_meta(name[:-5])
        model = meta['model']
        meta['files'] = [{'name': f, 'size': os.path.getsize(os.path.join(MODELS, f))}
                         for f in (f'{model}.traineddata', f'{model}_fast.traineddata')
                         if os.path.exists(os.path.join(MODELS, f))]
        out.append(meta)
    return sorted(out, key=lambda m: m.get('created', 0), reverse=True)
