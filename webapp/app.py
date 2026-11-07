"""Local web app to fine-tune Tesseract: run with ./run.sh then open http://127.0.0.1:8765."""
import json
import os
import sys

from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.routing import Map, Rule
from werkzeug.serving import run_simple
from werkzeug.utils import safe_join, send_file
from werkzeug.wrappers import Request, Response

import pipeline

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

url_map = Map([
    Rule('/', endpoint='index'),
    Rule('/static/<path:path>', endpoint='static'),
    Rule('/api/state', endpoint='state'),
    Rule('/api/setup', endpoint='setup', methods=['POST']),
    Rule('/api/upload', endpoint='upload', methods=['POST']),
    Rule('/api/process', endpoint='process', methods=['POST']),
    Rule('/api/sources/<sid>', endpoint='source', methods=['POST', 'DELETE']),
    Rule('/api/lines', endpoint='lines', methods=['GET', 'POST']),
    Rule('/api/lines/bulk', endpoint='lines_bulk', methods=['POST']),
    Rule('/api/lines/approve-matched', endpoint='approve_matched', methods=['POST']),
    Rule('/api/match', endpoint='match', methods=['POST']),
    Rule('/api/import-vod', endpoint='import_vod', methods=['POST']),
    Rule('/api/train', endpoint='train', methods=['POST']),
    Rule('/api/eval', endpoint='evaluate', methods=['POST']),
    Rule('/api/stop', endpoint='stop', methods=['POST']),
    Rule('/api/job', endpoint='job'),
    Rule('/line/<sid>/<name>', endpoint='line_image'),
    Rule('/download/<name>', endpoint='download'),
])


def as_json(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False), status=status, mimetype='application/json')


def body(request):
    return request.get_json(silent=True) or {}


def job_state():
    job = pipeline.runner.current
    return job.as_dict() if job else None


# ---------------------------------------------------------------- handlers
def index(request):
    return send_file(os.path.join(STATIC, 'index.html'), request.environ, max_age=0)


def static(request, path):
    full = safe_join(STATIC, path)
    if not full or not os.path.isfile(full):
        raise NotFound()
    return send_file(full, request.environ, max_age=0)


def state(request):
    with pipeline.store.lock:
        sources = sorted(pipeline.store.sources.values(), key=lambda s: s['added'])
    return as_json({
        'env': pipeline.environment(), 'sources': sources, 'counts': pipeline.counts(),
        'models': pipeline.list_models(), 'job': job_state(),
    })


def setup(request):
    pipeline.runner.start('setup', pipeline.setup_job)
    return as_json({'ok': True})


def upload(request):
    role = request.form.get('role', 'train')
    if role not in ('train', 'eval'):
        return as_json({'error': 'role'}, 400)
    added, errors = [], []
    for storage in request.files.getlist('files'):
        try:
            added.append(pipeline.add_source(storage.filename, storage.stream, role))
        except ValueError as error:
            errors.append(str(error))
    started = False
    if added and not pipeline.runner.busy():
        pipeline.runner.start('process', pipeline.process_job)
        started = True
    return as_json({'added': added, 'errors': errors, 'processing': started})


def process(request):
    pipeline.runner.start('process', pipeline.process_job)
    return as_json({'ok': True})


def source(request, sid):
    if sid not in pipeline.store.sources:
        raise NotFound()
    if request.method == 'DELETE':
        if pipeline.runner.busy():
            return as_json({'error': 'Đang có việc chạy, đợi xong rồi xoá'}, 409)
        pipeline.delete_source(sid)
        return as_json({'ok': True})
    role = body(request).get('role')
    if role not in ('train', 'eval'):
        return as_json({'error': 'role'}, 400)
    with pipeline.store.lock:
        pipeline.store.sources[sid]['role'] = role
        pipeline.store.save()
    return as_json({'ok': True})


def lines(request):
    if request.method == 'POST':
        data = body(request)
        return as_json(pipeline.update_line(data['name'], data.get('text'), data.get('status')))
    args = request.args
    return as_json(pipeline.list_lines(
        source=args.get('source') or None, status=args.get('status') or None, sort=args.get('sort', 'conf'),
        offset=int(args.get('offset', 0)), limit=min(int(args.get('limit', 30)), 200)))


def lines_bulk(request):
    data = body(request)
    for name in data.get('names', []):
        pipeline.update_line(name, status=data['status'])
    return as_json({'ok': True})


def approve_matched(request):
    data = body(request)
    count = pipeline.approve_matched(float(data.get('min_score', 0.97)), dry_run=bool(data.get('dry_run', True)))
    return as_json({'count': count})


def match(request):
    pipeline.runner.start('match', pipeline.match_job)
    return as_json({'ok': True})


def import_vod(request):
    role = body(request).get('role', 'train')
    if role not in ('train', 'eval'):
        return as_json({'error': 'role'}, 400)
    if pipeline.runner.busy():
        return as_json({'error': 'Đang có việc chạy, đợi xong rồi nhập'}, 409)
    added = pipeline.import_vod(role)
    if added:
        pipeline.runner.start('process', pipeline.process_job)
    return as_json({'added': len(added)})


def train(request):
    params = body(request)
    if pipeline.list_models() and any(m['model'] == params.get('model') for m in pipeline.list_models()) \
            and not params.get('overwrite'):
        return as_json({'error': f'Model "{params.get("model")}" đã có. Đổi tên hoặc tick "Ghi đè".'}, 409)
    pipeline.runner.start('train', pipeline.train_job, params)
    return as_json({'ok': True})


def evaluate(request):
    pipeline.runner.start('eval', pipeline.evaluate_job, body(request)['model'])
    return as_json({'ok': True})


def stop(request):
    pipeline.runner.stop()
    return as_json({'ok': True})


def job(request):
    return as_json(job_state())


def line_image(request, sid, name):
    full = safe_join(pipeline.LINES, sid, 'scan', name)
    if not full or not os.path.isfile(full):
        raise NotFound()
    return send_file(full, request.environ, max_age=3600)


def download(request, name):
    full = safe_join(pipeline.MODELS, name)
    if not full or not name.endswith('.traineddata') or not os.path.isfile(full):
        raise NotFound()
    return send_file(full, request.environ, as_attachment=True, download_name=name)


HANDLERS = {
    'index': index, 'static': static, 'state': state, 'setup': setup, 'upload': upload, 'process': process,
    'source': source, 'lines': lines, 'lines_bulk': lines_bulk, 'train': train, 'evaluate': evaluate,
    'approve_matched': approve_matched, 'match': match, 'import_vod': import_vod,
    'stop': stop, 'job': job, 'line_image': line_image, 'download': download,
}


@Request.application
def application(request):
    adapter = url_map.bind_to_environ(request.environ)
    try:
        endpoint, values = adapter.match()
        return HANDLERS[endpoint](request, **values)
    except HTTPException as error:
        return error
    except (RuntimeError, ValueError, KeyError) as error:
        return as_json({'error': str(error)}, 400)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    # App không có đăng nhập mà chứa tài liệu khách: mặc định chỉ máy này vào được, máy khác dùng SSH tunnel
    host = os.environ.get('TT_HOST', '127.0.0.1')
    print(f'Tesseract trainer: http://{host}:{port}  (dữ liệu: {pipeline.WORK})')
    run_simple(host, port, application, threaded=True, use_reloader=False)
