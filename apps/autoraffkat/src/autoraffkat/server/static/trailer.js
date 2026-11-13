/* Trailer-sivu: pilko, kehystä käsin tarvittaessa, vie kolmikaistainen FCPXML.
   Tila on tässä; palvelin laskee ja kirjoittaa. */
'use strict';

const $ = (id) => document.getElementById(id);
const FRAME_W = 1080;       // projektin leveys
const HALF_H = 960;         // puolikaspaneelin korkeus
const FULL_H = 1920;        // koko ruudun korkeus

let plan = null;            // palvelimen vastaus: polku, mitat, palat
let pieces = [];            // {start, end, x, manual}
let sel = 0;
let dialect = 'fcp';
let busy = false;

function banner(text, bad) {
  const box = $('tr-banner');
  box.textContent = text || '';
  box.classList.toggle('hidden', !text);
  box.classList.toggle('error', !!bad);
}

function fmt(seconds) {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
}

async function api(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || T('app.exportFailed', { error: '' }));
  return data;
}

/* Ikkunan leveys lähteen leveydestä kaistan kuvasuhteelle (täyttö, ks.
   trailer.window): sama laskenta kuin palvelimella. */
function windowFraction(frameH) {
  const fill = Math.max(FRAME_W / plan.width, frameH / plan.height);
  return Math.min(1, FRAME_W / fill / plan.width);
}

function boxLeft(x, frac) {
  return Math.min(Math.max(x - frac / 2, 0), 1 - frac);
}

function renderBoxes() {
  if (!plan || !pieces[sel]) return;
  const x = pieces[sel].x;
  [['tr-box-half', HALF_H], ['tr-box-full', FULL_H]].forEach(([id, h]) => {
    const frac = windowFraction(h);
    const box = $(id);
    box.style.left = `${boxLeft(x, frac) * 100}%`;
    box.style.width = `${frac * 100}%`;
  });
  drawComposite();
}

function drawComposite() {
  const canvas = $('tr-comp');
  const img = $('tr-img');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!plan || !img.complete || !img.naturalWidth) return;
  const x = pieces[sel].x;
  const lane = $('tr-lane').value;
  const crop = (frameH, dx, dy, dw, dh) => {
    const frac = windowFraction(frameH);
    const sw = img.naturalWidth * frac;
    const sh = sw * (dh / dw);
    const sx = boxLeft(x, frac) * img.naturalWidth;
    const sy = Math.max(0, (img.naturalHeight - sh) / 2);
    ctx.drawImage(img, sx, sy, sw, Math.min(sh, img.naturalHeight), dx, dy, dw, dh);
  };
  const W = canvas.width;
  const H = canvas.height;
  crop(FULL_H, 0, 0, W, H);
  if (lane !== 'none') {
    const top = lane === 'top';
    crop(HALF_H, 0, top ? 0 : H / 2, W, H / 2);
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.strokeRect(2, top ? H / 2 + 2 : 2, W - 4, H / 2 - 4);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(0, top ? H / 2 : 0, W, 0);
    ctx.fillStyle = '#fff';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(T('trailer.yourVideo'), W / 2, top ? H * 0.75 : H * 0.25);
  }
}

function showFrame() {
  if (!plan || !pieces[sel]) return;
  const p = pieces[sel];
  const mid = (p.start + p.end) / 2;
  const img = $('tr-img');
  img.onload = () => { renderBoxes(); };
  img.src = `/api/trailer/frame?path=${encodeURIComponent(plan.path)}&t=${mid.toFixed(2)}`;
}

function renderList() {
  const list = $('tr-list');
  list.textContent = '';
  $('tr-count').textContent = T('trailer.pieces', { n: pieces.length });
  pieces.forEach((p, i) => {
    const li = document.createElement('li');
    li.className = 'tr-piece' + (i === sel ? ' selected' : '');
    const main = document.createElement('button');
    main.type = 'button';
    main.className = 'ghost tr-piece-main';
    main.textContent = `${String(i + 1).padStart(2, '0')}  ${fmt(p.start)}–${fmt(p.end)}  ` +
      `${Math.round(p.x * 100)} %  ${p.manual ? T('trailer.manual') : T('trailer.auto')}`;
    main.addEventListener('click', () => { sel = i; renderList(); showFrame(); });
    const split = document.createElement('button');
    split.type = 'button';
    split.className = 'ghost small';
    split.textContent = T('trailer.split');
    split.disabled = p.end - p.start < 0.6;
    split.addEventListener('click', () => {
      const mid = (p.start + p.end) / 2;
      pieces.splice(i, 1, { ...p, end: mid }, { ...p, start: mid });
      if (sel > i) sel += 1;
      renderList();
      showFrame();
    });
    const merge = document.createElement('button');
    merge.type = 'button';
    merge.className = 'ghost small';
    merge.textContent = T('trailer.merge');
    merge.disabled = i === pieces.length - 1;
    merge.addEventListener('click', () => {
      pieces.splice(i, 2, { ...p, end: pieces[i + 1].end });
      if (sel > i) sel -= 1;
      renderList();
      showFrame();
    });
    li.append(main, split, merge);
    list.append(li);
  });
}

function renderDest() {
  const host = $('tr-dest');
  host.textContent = '';
  host.setAttribute('aria-label', T('export.dest.label'));
  ['fcp', 'resolve'].forEach((value) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ghost';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(value === dialect));
    b.textContent = T(`export.dest.${value}`);
    b.addEventListener('click', () => { dialect = value; renderDest(); });
    host.append(b);
  });
}

function renderAll() {
  $('tr-name').textContent = plan ? plan.name : '—';
  $('tr-meta').textContent = plan
    ? `${plan.width}×${plan.height} · ${plan.fps.toFixed(2)} fps · ${fmt(plan.duration)}`
    : T('trailer.noFile');
  $('tr-export').disabled = !plan || busy;
  $('tr-apply').disabled = !plan || busy;
  renderDest();
  renderList();
  showFrame();
}

async function load(path) {
  if (busy) return;
  busy = true;
  $('tr-status').textContent = T('trailer.measuring');
  banner('');
  try {
    const mode = $('tr-mode').value;
    const body = {
      path,
      threshold: Number($('tr-sens').value) / 100,
      min_len: Number($('tr-min').value),
    };
    if (mode === 'every') body.every = Number($('tr-every').value);
    plan = await api('/api/trailer/plan', body);
    pieces = plan.pieces.map((p) => ({ ...p, manual: false }));
    sel = 0;
  } catch (err) {
    banner(err.message, true);
  } finally {
    busy = false;
    $('tr-status').textContent = '';
    renderAll();
  }
}

async function exportFcpxml() {
  if (!plan || busy) return;
  busy = true;
  $('tr-export').disabled = true;
  $('tr-status').textContent = T('app.exporting');
  try {
    const data = await api('/api/trailer/export', {
      path: plan.path,
      pieces: pieces.map(({ start, end, x }) => ({ start, end, x })),
      lane: $('tr-lane').value,
      dialect,
    });
    const box = $('tr-exported');
    box.textContent = '';
    box.classList.remove('hidden');
    const said = document.createElement('span');
    said.className = 'said';
    said.textContent = T('trailer.exported', { n: data.pieces });
    const field = document.createElement('input');
    field.type = 'text';
    field.readOnly = true;
    field.value = data.path;
    field.setAttribute('aria-label', T('path.export'));
    field.addEventListener('focus', () => field.select());
    const show = document.createElement('button');
    show.className = 'ghost small';
    show.textContent = T('export.reveal');
    show.addEventListener('click', () => api('/api/reveal', { path: data.path })
      .catch((err) => banner(err.message, true)));
    box.append(said, field, show);
    banner('');
  } catch (err) {
    banner(err.message, true);
  } finally {
    busy = false;
    $('tr-status').textContent = '';
    $('tr-export').disabled = false;
  }
}

function setX(clientX) {
  const rect = $('tr-frame').getBoundingClientRect();
  if (!rect.width || !pieces[sel]) return;
  pieces[sel].x = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  pieces[sel].manual = true;
  renderBoxes();
}

function bind() {
  document.querySelectorAll('[data-t]').forEach((el) => { el.textContent = T(el.dataset.t); });
  $('tr-open').addEventListener('click', async () => {
    try {
      const data = await api('/api/trailer/pick');
      if (data.path) load(data.path);
      else if (data.unavailable) banner(T('trailer.noPicker'), true);
    } catch (err) { banner(err.message, true); }
  });
  $('tr-mode').addEventListener('change', () => {
    const every = $('tr-mode').value === 'every';
    $('tr-every-row').classList.toggle('hidden', !every);
    $('tr-sens-row').classList.toggle('hidden', every);
    $('tr-min-row').classList.toggle('hidden', every);
  });
  $('tr-sens').addEventListener('input', () => {
    $('tr-sens-out').textContent = (Number($('tr-sens').value) / 100).toFixed(2).replace('.', ',');
  });
  $('tr-apply').addEventListener('click', () => plan && load(plan.path));
  $('tr-export').addEventListener('click', exportFcpxml);
  $('tr-lane').addEventListener('change', drawComposite);
  const frame = $('tr-frame');
  let dragging = false;
  frame.addEventListener('pointerdown', (e) => { dragging = true; frame.setPointerCapture(e.pointerId); setX(e.clientX); renderList(); });
  frame.addEventListener('pointermove', (e) => { if (dragging) setX(e.clientX); });
  frame.addEventListener('pointerup', () => { dragging = false; renderList(); });
}

async function start() {
  try {
    const state = await (await fetch('/api/state')).json();
    if (state && state.language) setLang(state.language);
    document.documentElement.lang = LANG;
  } catch { /* oletuskieli */ }
  bind();
  renderAll();
  const path = new URLSearchParams(location.search).get('path');
  if (path) load(path);
}

start();
