'use strict';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (x) => (x == null ? '-' : (x * 100).toFixed(2) + '%');
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString('vi-VN') : '');
const fmtDur = (sec) => {
  if (sec == null) return '';
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return h ? `${h} giờ ${m} phút` : `${m} phút`;
};
const ITER_PER_SEC = 12; // đo trên máy này: ~12 vòng/giây (1 nhân CPU)

let state = null;
let lastJobStatus = null;
const label = { offset: 0, limit: 30, items: [], total: 0, focus: 0 };

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.method = opts.method || 'POST';
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(err) { alert(err.message || err); }

// ---------------------------------------------------------------- tabs
function showTab(name) {
  $$('nav button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + name));
  location.hash = name;
  if (name === 'label') loadLines();
}
$$('nav button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
window.addEventListener('hashchange', () => {
  const name = location.hash.slice(1);
  if ($('#tab-' + name) && !$('#tab-' + name).classList.contains('active')) showTab(name);
});

// ---------------------------------------------------------------- state
async function refresh() {
  state = await api('/api/state');
  renderEnv();
  renderSources();
  renderTrainStats();
  renderModels();
  renderJob(state.job);
}

function renderEnv() {
  const env = state.env;
  $('#work-dir').textContent = env.work_dir;
  $('#models-dir').textContent = env.models_dir;
  $('#env-checks').innerHTML = env.checks.map((c) =>
    `<li class="${c.ok ? 'ok' : (c.warn_only ? 'warn-only' : 'no')}">${esc(c.label)}${c.hint ? `<div class="muted">${esc(c.hint)}</div>` : ''}</li>`).join('');
  $('#btn-setup').textContent = env.ready ? 'Đã sẵn sàng — kiểm tra lại' : 'Cài đặt tự động';
}

const STATUS_TEXT = { pending: 'Đang chờ', processing: 'Đang xử lý…', done: 'Xong', error: 'Lỗi' };

function renderSources() {
  const rows = state.sources.map((s) => `
    <tr>
      <td>${esc(s.name)}</td>
      <td><select data-role="${s.id}">
        <option value="train" ${s.role === 'train' ? 'selected' : ''}>Train</option>
        <option value="eval" ${s.role === 'eval' ? 'selected' : ''}>Đánh giá</option></select></td>
      <td class="num">${s.pages ? `${s.pages}<div class="muted">${s.digital_pages} chữ / ${s.scan_pages} scan</div>` : (s.ext === '.docx' || s.ext === '.txt' ? 'văn bản' : '')}</td>
      <td class="num">${s.auto_lines}${s.corpus_lines && !s.auto_lines ? `<div class="muted">${s.corpus_lines} dòng corpus</div>` : ''}</td>
      <td class="num">${s.scan_lines ? `<a href="#" data-review="${s.id}">${s.scan_lines}</a>` : 0}</td>
      <td>${STATUS_TEXT[s.status] || s.status}${s.error ? `<div class="error">${esc(s.error)}</div>` : ''}</td>
      <td><button class="small danger" data-del="${s.id}">Xoá</button></td>
    </tr>`).join('');
  $('#sources').innerHTML = rows;
  $('#no-sources').hidden = state.sources.length > 0;
  $('#btn-process').hidden = !state.sources.some((s) => s.status === 'pending' || s.status === 'error');

  const scanSources = state.sources.filter((s) => s.scan_lines);
  const current = $('#f-source').value;
  $('#f-source').innerHTML = '<option value="">Tất cả file</option>' +
    scanSources.map((s) => `<option value="${s.id}">${esc(s.name)} (${s.role === 'eval' ? 'đánh giá' : 'train'})</option>`).join('');
  $('#f-source').value = scanSources.some((s) => s.id === current) ? current : '';
  const todo = state.counts.labels.todo;
  $('#todo-badge').textContent = todo ? todo : '';
  const vod = state.counts.vod_import || {};
  const nPairs = vod.congbao_pairs || 0, nScan = vod.chinhphu_scan || 0, nGazette = vod.congbao || 0;
  $('#vod-import').hidden = !(nPairs + nScan + nGazette);
  $('#vod-import-text').textContent = `${nPairs} file của các cặp scan ↔ Công báo, ${nScan} văn bản scan và ` +
    `${nGazette} số Công báo chưa nhập.`;
}

$('#sources').addEventListener('change', async (e) => {
  const sid = e.target.dataset.role;
  if (!sid) return;
  await api('/api/sources/' + sid, { json: { role: e.target.value } }).catch(toast);
  refresh();
});
$('#sources').addEventListener('click', async (e) => {
  const del = e.target.dataset.del, review = e.target.dataset.review;
  if (del) {
    const s = state.sources.find((x) => x.id === del);
    if (!confirm(`Xoá "${s.name}" và mọi dòng (kể cả dòng đã duyệt) lấy từ file này?`)) return;
    await api('/api/sources/' + del, { method: 'DELETE' }).catch(toast);
    refresh();
  }
  if (review) {
    e.preventDefault();
    $('#f-source').value = review;
    label.offset = 0;
    showTab('label');
  }
});

// ---------------------------------------------------------------- upload
async function upload(files) {
  if (!files.length) return;
  const form = new FormData();
  [...files].forEach((f) => form.append('files', f));
  form.append('role', $('input[name=role]:checked').value);
  $('#upload-errors').hidden = true;
  try {
    const res = await api('/api/upload', { method: 'POST', body: form });
    if (res.errors.length) {
      $('#upload-errors').textContent = res.errors.join('\n');
      $('#upload-errors').hidden = false;
    }
    if (res.added.length && !res.processing) {
      $('#upload-errors').textContent = 'Đã tải lên. Đang có việc khác chạy: đợi xong rồi bấm "Xử lý lại file lỗi / đang chờ".';
      $('#upload-errors').hidden = false;
    }
  } catch (err) { toast(err); }
  refresh();
}
const drop = $('#dropzone');
drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files); });
$('#file-input').addEventListener('change', (e) => { upload(e.target.files); e.target.value = ''; });
$('#btn-process').addEventListener('click', () => api('/api/process', { method: 'POST' }).then(refresh, toast));
$('#btn-vod-import').addEventListener('click', async () => {
  try {
    const res = await api('/api/import-vod', { json: { role: $('input[name=role]:checked').value } });
    if (!res.added) alert('Không có file mới.');
  } catch (err) { toast(err); }
  refresh();
});
$('#btn-setup').addEventListener('click', () => api('/api/setup', { method: 'POST' }).then(refresh, toast));

// ---------------------------------------------------------------- labeling
async function loadLines() {
  const params = new URLSearchParams({
    source: $('#f-source').value, status: $('#f-status').value, sort: $('#f-sort').value,
    offset: label.offset, limit: label.limit,
  });
  const res = await api('/api/lines?' + params);
  if (!res.items.length && label.offset > 0) { label.offset = Math.max(0, label.offset - label.limit); return loadLines(); }
  label.items = res.items;
  label.total = res.total;
  label.focus = 0;
  renderLines();
}

function renderLines() {
  const c = state ? state.counts.labels : { todo: 0, approved: 0, rejected: 0, suggested: 0 };
  $('#label-counts').textContent = countsText(c);
  const from = label.total ? label.offset + 1 : 0, to = Math.min(label.offset + label.limit, label.total);
  $('#page-info').textContent = `${from}–${to} / ${label.total}`;
  $('#btn-prev').disabled = label.offset === 0;
  $('#btn-next').disabled = to >= label.total;
  if (!label.items.length) {
    $('#lines').innerHTML = '<p class="muted">Không có dòng nào ở bộ lọc này. Tải PDF/ảnh scan ở tab 2 để có dòng cần duyệt.</p>';
    return;
  }
  $('#lines').innerHTML = label.items.map((l, i) => `
    <div class="line ${l.status}" data-i="${i}">
      <div class="img"><img loading="lazy" src="/line/${encodeURIComponent(l.source)}/${encodeURIComponent(l.name)}.png" alt=""></div>
      <input class="text" lang="vi" spellcheck="false" value="${esc(l.text)}">
      ${l.ocr !== l.text ? `<div class="ocr">Máy đọc: ${esc(l.ocr)}</div>` : ''}
      <div class="meta">
        <span>Trang ${l.page}</span>
        <span class="${l.conf < 80 ? 'conf-low' : ''}">Độ tin của máy ${Math.round(l.conf)}%</span>
        ${l.ref_score >= 0.8 ? `<span class="${l.ref_score >= 0.97 ? 'ref-ok' : 'ref-mid'}" title="Chữ điền sẵn lấy từ bản chữ (file có lớp chữ)">Khớp bản chữ ${Math.round(l.ref_score * 100)}%</span>` : ''}
        <span class="st">${{ todo: 'Chưa duyệt', approved: '✓ Đã duyệt', rejected: '✗ Đã bỏ' }[l.status]}</span>
        <span class="spacer"></span>
        <button class="small" data-act="ocr">Khôi phục chữ máy đọc</button>
        <button class="small danger" data-act="rejected">Bỏ dòng</button>
        <button class="small primary" data-act="approved">Duyệt</button>
      </div>
    </div>`).join('');
  focusLine(0);
}

function focusLine(i) {
  const rows = $$('#lines .line');
  if (!rows.length) return;
  label.focus = Math.max(0, Math.min(i, rows.length - 1));
  rows.forEach((r, k) => r.classList.toggle('focus', k === label.focus));
  const input = $('input.text', rows[label.focus]);
  input.focus({ preventScroll: true });
  rows[label.focus].scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function saveLine(i, status) {
  const row = $(`#lines .line[data-i="${i}"]`);
  const item = label.items[i];
  const text = $('input.text', row).value;
  try {
    const updated = await api('/api/lines', { json: { name: item.name, text, status } });
    label.items[i] = updated;
    row.className = `line ${updated.status}`;
    $('.st', row).textContent = { todo: 'Chưa duyệt', approved: '✓ Đã duyệt', rejected: '✗ Đã bỏ' }[updated.status];
    $('input.text', row).value = updated.text;
    state.counts.labels[item.status] -= 1;
    if (item.status === 'todo' && item.ref_score >= 0.8) state.counts.labels.suggested -= 1;
    state.counts.labels[updated.status] += 1;
    renderCountsOnly();
    focusLine(i + 1);
  } catch (err) { toast(err); }
}

function countsText(c) {
  return `Chưa duyệt ${c.todo} (${c.suggested || 0} dòng đã điền từ bản chữ) · Đã duyệt ${c.approved} · Đã bỏ ${c.rejected}`;
}

function renderCountsOnly() {
  const c = state.counts.labels;
  $('#label-counts').textContent = countsText(c);
  $('#todo-badge').textContent = c.todo ? c.todo : '';
}

$('#lines').addEventListener('keydown', (e) => {
  const row = e.target.closest('.line');
  if (!row || !e.target.matches('input.text')) return;
  const i = Number(row.dataset.i);
  if (e.key === 'Enter') { e.preventDefault(); saveLine(i, e.shiftKey ? 'rejected' : 'approved'); }
  if (e.key === 'ArrowDown') { e.preventDefault(); focusLine(i + 1); }
  if (e.key === 'ArrowUp') { e.preventDefault(); focusLine(i - 1); }
});
$('#lines').addEventListener('focusin', (e) => {
  const row = e.target.closest('.line');
  if (row) { label.focus = Number(row.dataset.i); $$('#lines .line').forEach((r) => r.classList.toggle('focus', r === row)); }
});
$('#lines').addEventListener('click', (e) => {
  const act = e.target.dataset.act;
  if (!act) return;
  const i = Number(e.target.closest('.line').dataset.i);
  if (act === 'ocr') { $(`#lines .line[data-i="${i}"] input.text`).value = label.items[i].ocr; focusLine(i); return; }
  saveLine(i, act);
});
['#f-source', '#f-status', '#f-sort'].forEach((sel) => $(sel).addEventListener('change', () => { label.offset = 0; loadLines(); }));
$('#btn-prev').addEventListener('click', () => { label.offset = Math.max(0, label.offset - label.limit); loadLines(); });
$('#btn-next').addEventListener('click', () => { label.offset += label.limit; loadLines(); });
$('#btn-approve-page').addEventListener('click', async () => {
  const todo = label.items.map((l, i) => [l, i]).filter(([l]) => l.status === 'todo');
  if (!todo.length) return;
  if (!confirm(`Duyệt ${todo.length} dòng chưa duyệt trên trang này với chữ đang hiển thị?\nChỉ bấm khi bạn đã soát hết các dòng này.`)) return;
  for (const [, i] of todo) {
    const text = $(`#lines .line[data-i="${i}"] input.text`).value;
    await api('/api/lines', { json: { name: label.items[i].name, text, status: 'approved' } }).catch(toast);
  }
  await refresh();
  loadLines();
});

$('#btn-match').addEventListener('click', () => api('/api/match', { method: 'POST' }).then(refresh, toast));
$('#btn-approve-matched').addEventListener('click', async () => {
  const min = Number($('#approve-min').value || 97) / 100;
  try {
    const { count } = await api('/api/lines/approve-matched', { json: { min_score: min, dry_run: true } });
    if (!count) { alert('Không có dòng chưa duyệt nào khớp bản chữ từ mức này.'); return; }
    if (!confirm(`Duyệt ${count} dòng chưa duyệt có chữ lấy từ bản chữ, khớp ≥ ${Math.round(min * 100)}%?\n` +
      'Nên xem lướt vài trang theo "Khớp bản chữ cao trước" trước khi bấm.')) return;
    await api('/api/lines/approve-matched', { json: { min_score: min, dry_run: false } });
    await refresh();
    loadLines();
  } catch (err) { toast(err); }
});

// ---------------------------------------------------------------- train
function renderTrainStats() {
  const { train, eval: ev } = state.counts.split;
  $('#c-auto').textContent = train.auto.toLocaleString('vi-VN');
  $('#c-scan').textContent = train.scan.toLocaleString('vi-VN');
  $('#c-corpus').textContent = train.corpus.toLocaleString('vi-VN');
  $('#c-eval').textContent = `${ev.scan} / ${ev.auto}`;
  const ext = state.counts.external;
  $('#c-ext').textContent = `${ext.train.toLocaleString('vi-VN')} / ${ext.eval.toLocaleString('vi-VN')}`;
  const extInput = $('#train-form [name=external]');
  extInput.max = ext.train;
  if (!extInput.dataset.touched) extInput.value = ext.train;
  $('#ext-hint').textContent = ext.train
    ? `dòng giả lập từ Wikipedia/Wikisource… (tạo bằng vod.py build-gt). Có ${ext.train.toLocaleString('vi-VN')} dòng; 0 = không dùng.`
    : `chưa có: chạy vie-ocr-data/vod.py build-gt (đọc ở ${ext.dir})`;
  const synth = $('#train-form [name=synth]');
  if (!synth.dataset.touched) synth.value = state.counts.default_synth;
  updateMaxLinesHint();
  const warns = [];
  if (!state.env.ready) warns.push('Môi trường chưa sẵn sàng: vào tab 1 bấm "Cài đặt tự động".');
  if (train.auto + train.scan === 0) warns.push('Chưa có dòng train nào: tải file ở tab 2 (và duyệt dòng scan ở tab 3).');
  if (state.counts.labels.todo) warns.push(`Còn ${state.counts.labels.todo} dòng scan chưa duyệt: các dòng này sẽ KHÔNG được dùng.`);
  if (!ev.scan && !ev.auto) warns.push('Chưa có bộ đánh giá: sẽ không so được model mới với vie gốc. Đánh dấu 1–2 file là "Đánh giá" ở tab 2.');
  else if (!ev.scan) warns.push('Bộ đánh giá chưa có dòng scan thật đã duyệt: số đo chỉ phản ánh PDF có lớp chữ, chưa phản ánh scan thật.');
  $('#train-warn').textContent = warns.join('\n');
  $('#train-warn').hidden = !warns.length;
  updateEta();
}
function updateEta() {
  const it = Number($('#train-form [name=iterations]').value || 0);
  $('#eta').textContent = it ? `ước tính ~${fmtDur(it / ITER_PER_SEC)} theo tốc độ máy Mac dev; thời gian còn lại thật hiện khi đang train` : '';
}
function updateMaxLinesHint() {
  if (!state.counts) return;
  const { train } = state.counts.split;
  const weight = Number($('#train-form [name=real_weight]').value || 1);
  const available = train.auto + train.scan * weight;
  const max = Number($('#train-form [name=max_lines]').value || 0);
  const used = max && max < available ? max : available;
  $('#max-lines-hint').textContent = `có ${available.toLocaleString('vi-VN')} dòng (PDF + scan × hệ số), sẽ dùng `
    + `${used.toLocaleString('vi-VN')}: lấy ngẫu nhiên, giữ tỉ lệ PDF/scan. 0 = dùng hết. `
    + 'Mỗi dòng phải dựng file .lstmf trước khi train, nên càng nhiều dòng càng lâu.';
}
$('#train-form [name=max_lines]').addEventListener('input', updateMaxLinesHint);
$('#train-form [name=real_weight]').addEventListener('input', updateMaxLinesHint);
$('#train-form [name=iterations]').addEventListener('input', updateEta);
$('#train-form [name=synth]').addEventListener('input', (e) => { e.target.dataset.touched = '1'; });
$('#train-form [name=external]').addEventListener('input', (e) => { e.target.dataset.touched = '1'; });
$('#train-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const params = Object.fromEntries(f.entries());
  params.overwrite = f.has('overwrite');
  try {
    await api('/api/train', { json: params });
    refresh();
  } catch (err) { toast(err); }
});

function renderChart(history) {
  const svg = $('#chart');
  if (!history || history.length < 2) { svg.innerHTML = ''; return; }
  const maxX = history[history.length - 1][0] || 1;
  const maxY = Math.max(...history.map((p) => p[1])) || 1;
  const pts = history.map(([x, y]) => `${(x / maxX) * 600},${150 - (y / maxY) * 140}`).join(' ');
  svg.innerHTML = `<polyline points="${pts}"/><text x="4" y="14">${maxY.toFixed(1)}%</text><text x="4" y="156">0</text>` +
    `<text x="520" y="156">vòng ${maxX}</text>`;
}

// ---------------------------------------------------------------- job
const KIND_TEXT = { setup: 'Cài đặt', process: 'Xử lý file', train: 'Train', eval: 'Đánh giá', match: 'Khớp bản chữ' };
function renderJob(job) {
  const bar = $('#jobbar');
  if (!job) { bar.hidden = true; return; }
  bar.hidden = false;
  const running = job.status === 'running';
  $('#job-kind').textContent = KIND_TEXT[job.kind] + (running ? '' : { done: ' ✓', error: ' ✗', stopped: ' (đã dừng)' }[job.status]);
  $('#job-msg').textContent = job.message;
  $('#job-progress').value = job.progress;
  $('#job-progress').hidden = !running;
  $('#job-stop').hidden = !running;
  $('#log').textContent = job.log.join('\n');
  $$('#btn-setup, #btn-process, #train-form button, #btn-match, #btn-vod-import').forEach((b) => { b.disabled = running; });
  if (job.kind === 'train') {
    $('#train-live').hidden = false;
    const m = job.metrics;
    const parts = [];
    if (m.lines_total) parts.push(`${m.lines_total} dòng train (${m.lines_auto} PDF + ${m.lines_scan} scan + ${m.lines_synth} giả lập + ${m.lines_external || 0} kho ngoài)`);
    if (m.iteration != null) parts.push(`vòng ${m.iteration}/${m.iterations}`);
    if (m.bcer_train != null) parts.push(`lỗi ký tự trên tập train ${m.bcer_train}%`);
    if (m.cer_eval_internal != null) parts.push(`trên 5% giữ lại ${m.cer_eval_internal}%`);
    if (running && m.eta_sec != null) parts.push(`còn ~${fmtDur(m.eta_sec)}`);
    $('#train-metrics').textContent = parts.join(' · ');
    renderChart(m.bcer_history);
  }
}
$('#job-stop').addEventListener('click', () => {
  if (confirm('Dừng việc đang chạy? Train bị dừng phải chạy lại từ đầu.')) api('/api/stop', { method: 'POST' }).catch(toast);
});

async function poll() {
  try {
    const job = await api('/api/job');
    renderJob(job);
    const status = job && job.status;
    if (status !== lastJobStatus) {
      lastJobStatus = status;
      await refresh();
      if ($('#tab-label').classList.contains('active') && status !== 'running') loadLines();
    } else if (status === 'running' && job.kind === 'process') {
      await refresh();
    }
  } catch (err) { /* server tạm không phản hồi */ }
  setTimeout(poll, lastJobStatus === 'running' ? 1500 : 4000);
}

// ---------------------------------------------------------------- models
function renderModels() {
  const models = state.models;
  $('#no-models').hidden = models.length > 0;
  $('#models').innerHTML = models.map((m) => {
    const t = m.train || {};
    const files = (m.files || []).map((f) =>
      `<a href="/download/${encodeURIComponent(f.name)}"><button class="small">Tải ${esc(f.name)} (${(f.size / 1e6).toFixed(1)} MB)</button></a>`).join(' ');
    return `<div class="model">
      <h3>${esc(m.model)}</h3>
      <div class="muted">Train lúc ${fmtTime(m.created)} · ${fmtDur(m.duration_sec)} · ${t.lines_total ?? '?'} dòng
        (${t.lines_auto ?? 0} PDF + ${t.lines_scan ?? 0} scan + ${t.lines_synth ?? 0} giả lập + ${t.lines_external ?? 0} kho ngoài) · ${t.iterations ?? '?'} vòng ·
        lỗi ký tự train cuối ${t.bcer_train ?? '?'}%</div>
      ${evalTable(m)}
      <div class="toolbar">${files}<span class="spacer"></span>
        <button class="small" data-eval="${esc(m.model)}">${m.eval && Object.keys(m.eval).length ? 'Đánh giá lại' : 'Đánh giá'}</button></div>
      <details><summary>Cách dùng model</summary><pre>tesseract anh.png ra -l ${esc(m.model)} --tessdata-dir ${esc(state.env.models_dir)}
# hoặc chép ${esc(m.model)}.traineddata vào thư mục tessdata rồi dùng -l ${esc(m.model)}
# bản _fast: nhỏ hơn ~7 lần, nhanh hơn, kém chính xác hơn chút</pre></details>
    </div>`;
  }).join('');
}

function evalTable(m) {
  const ev = m.eval || {};
  const sets = Object.keys(ev);
  if (!sets.length) return '<p class="muted">Chưa đánh giá (cần file đánh dấu "Đánh giá" ở tab 2).</p>';
  const names = { scan: 'Scan thật đã duyệt', pdf: 'Dòng từ PDF có lớp chữ', ext: 'Dòng giả lập kho vie-ocr-data' };
  let html = '<table class="grid"><thead><tr><th>Bộ đánh giá</th><th>Model</th><th class="num">CER</th><th class="num">WER</th><th class="num">Dòng đúng hết</th><th class="num">CER IN HOA</th><th class="num">s/dòng</th></tr></thead><tbody>';
  for (const set of sets) {
    const models = ev[set].models;
    const base = Object.entries(models).find(([k]) => k.endsWith('(gốc)'));
    for (const [name, r] of Object.entries(models)) {
      let cls = '';
      if (base && name !== base[0]) cls = r.CER < base[1].CER ? 'better' : r.CER > base[1].CER ? 'worse' : '';
      html += `<tr><td>${names[set] || set} <span class="muted">(${ev[set].lines} dòng)</span></td><td>${esc(name)}</td>
        <td class="num ${cls}">${pct(r.CER)}</td><td class="num">${pct(r.WER)}</td><td class="num">${pct(r.exact)}</td>
        <td class="num">${pct(r.CER_upper)}</td><td class="num">${r.sec_per_line.toFixed(2)}</td></tr>`;
    }
  }
  html += '</tbody></table>';
  const scan = ev.scan && ev.scan.models[m.model];
  if (scan && scan.confusions.length) {
    html += `<p class="muted">Model mới còn hay nhầm (đúng → đọc ra: số lần): ${scan.confusions.slice(0, 10)
      .map(([a, b, n]) => `<code>${esc(a)}</code>→<code>${esc(b)}</code>: ${n}`).join(', ')}</p>`;
  }
  return html;
}
$('#models').addEventListener('click', (e) => {
  const model = e.target.dataset.eval;
  if (model) api('/api/eval', { json: { model } }).then(refresh, toast);
});

// ---------------------------------------------------------------- init
(async () => {
  await refresh();
  const tab = location.hash.slice(1) || (state.env.ready ? (state.sources.length ? 'label' : 'files') : 'env');
  showTab(['env', 'files', 'label', 'train', 'models'].includes(tab) ? tab : 'env');
  lastJobStatus = state.job && state.job.status;
  poll();
})();
