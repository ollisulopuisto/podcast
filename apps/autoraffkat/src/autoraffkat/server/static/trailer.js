/* Trailer-sivu: pilko, kehystä käsin tarvittaessa, vie kolmikaistainen FCPXML.
   Tila on tässä; palvelin laskee ja kirjoittaa. */
'use strict';

const $ = (id) => document.getElementById(id);
const FRAME_W = 1080;       // projektin leveys
const HALF_H = 960;         // puolikaspaneelin korkeus
const FULL_H = 1920;        // koko ruudun korkeus

let plan = null;            // palvelimen vastaus: polku, mitat, palat
let pieces = [];            // {start, end, x, x_panel, manual, manual_panel}
let sel = 0;
let dialect = 'fcp';
let layout = 'wide';
try {
  const saved = localStorage.getItem('autoraffkat.trailer.layout');
  if (saved === 'wide' || saved === 'halves') layout = saved;
} catch { /* Tallennus voi olla estetty; valinta toimii silti. */ }
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

/* Puolikkaan vientizoomi: ei zoomia, paneeli peitetään täsmälleen
   (skaala 960/1080; käyttäjän 50/50-käsikorjaus 2026-11-20). Esikatselun
   ja viennin on näytettävä sama ikkuna. */
const HALF_ZOOM = 1;

function panelHeight() {
  return layout === 'wide' ? Math.round(FRAME_W * 9 / 16 / 2) * 2 : HALF_H;
}

function laneZoom(frameH) {
  return frameH === HALF_H ? HALF_ZOOM : 1;
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

/* Viennin näkyvä ikkuna: peittävä ikkuna kiinnitetään lähteen sisään
   (sama kiinnitys kuin trailer.window), ja zoomi kiristää näkyvän
   osuuden sen keskipisteen ympärille (fcp_panel: skaala × zoom). */
function exportWindow(x, frameH) {
  const cover = windowFraction(frameH);
  const frac = cover / laneZoom(frameH);
  const centre = boxLeft(x, cover) + cover / 2;
  return { left: centre - frac / 2, frac };
}

function renderBoxes() {
  if (!plan || !pieces[sel]) return;
  const p = pieces[sel];
  [['tr-box-half', panelHeight(), p.x_panel], ['tr-box-full', FULL_H, p.x]].forEach(([id, h, x]) => {
    const win = exportWindow(x, h);
    const box = $(id);
    box.style.left = `${win.left * 100}%`;
    box.style.width = `${win.frac * 100}%`;
  });
  drawComposite();
}

function drawComposite() {
  const canvas = $('tr-comp');
  const img = $('tr-img');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!plan || !img.complete || !img.naturalWidth) return;
  const p = pieces[sel];
  const lane = $('tr-lane').value;
  const crop = (frameH, x, dx, dy, dw, dh) => {
    const win = exportWindow(x, frameH);
    const sw = img.naturalWidth * win.frac;
    const sh = sw * (dh / dw);
    const sx = win.left * img.naturalWidth;
    const sy = Math.max(0, (img.naturalHeight - sh) / 2);
    ctx.drawImage(img, sx, sy, sw, Math.min(sh, img.naturalHeight), dx, dy, dw, dh);
  };
  const W = canvas.width;
  const H = canvas.height;
  crop(FULL_H, p.x, 0, 0, W, H);
  if (lane !== 'none') {
    const top = lane === 'top';
    const panelH = H * panelHeight() / FULL_H;
    const remainingH = H - panelH;
    crop(panelHeight(), p.x_panel, 0, top ? 0 : remainingH, W, panelH);
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.strokeRect(2, top ? panelH + 2 : 2, W - 4, remainingH - 4);
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(0, top ? panelH : 0, W, remainingH);
    ctx.fillStyle = '#fff';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(T('trailer.yourVideo'), W / 2, top ? panelH + remainingH / 2 : remainingH / 2);
  }
}

/* Valitsee palan ja näyttää sen keskikohdan. */
function selectPiece(i) {
  if (!pieces.length) return;
  sel = Math.max(0, Math.min(i, pieces.length - 1));
  renderList();
  showFrame();
  const row = $('tr-list').children[sel];
  if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
}

/* Kehityksen siirto: x on kuvan keskipiste 0–1-välillä. Paneeli-ikkuna
   (puolikas) on oma kehyksensä: Option-muunnos siirtää vain sitä. */
function nudge(dx, panel) {
  if (!pieces[sel]) return;
  const field = panel ? 'x_panel' : 'x';
  const flag = panel ? 'manual_panel' : 'manual';
  pieces[sel][field] = Math.min(1, Math.max(0, pieces[sel][field] + dx));
  pieces[sel][flag] = true;
  renderList();
  showFrame();
}

function splitAt(i) {
  const p = pieces[i];
  if (!p || p.end - p.start < 0.6) return;
  const mid = (p.start + p.end) / 2;
  pieces.splice(i, 1, { ...p, end: mid }, { ...p, start: mid });
  if (sel > i) sel += 1;
  renderList();
  showFrame();
}

/* Palan tajuaa kuuluvaksi edelliseen vasta nähtyään seuraavan otoksen —
   siksi yhdistys menee aina edelliseen, ei seuraavaan. */
function mergePrev(i) {
  if (i < 1 || i >= pieces.length) return;
  pieces.splice(i - 1, 2, { ...pieces[i - 1], end: pieces[i].end });
  if (sel >= i) sel -= 1;
  renderList();
  showFrame();
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
    const fullPct = Math.round(p.x * 100);
    const panelPct = Math.round(p.x_panel * 100);
    // Molemmat prosentit vain kun ikkunat eriytetty: koskematon pala näyttää
    // samalta kuin ennen.
    const pct = fullPct === panelPct ? `${fullPct} %` : `${fullPct} % | ${panelPct} %`;
    main.textContent = `${String(i + 1).padStart(2, '0')}  ${fmt(p.start)}–${fmt(p.end)}  ` +
      `${pct}  ${(p.manual || p.manual_panel) ? T('trailer.manual') : T('trailer.auto')}`;
    main.addEventListener('click', () => selectPiece(i));
    const split = document.createElement('button');
    split.type = 'button';
    split.className = 'ghost small';
    split.textContent = T('trailer.split');
    split.disabled = p.end - p.start < 0.6;
    split.addEventListener('click', () => splitAt(i));
    const merge = document.createElement('button');
    merge.type = 'button';
    merge.className = 'ghost small';
    merge.textContent = T('trailer.merge');
    merge.disabled = i === 0;
    merge.setAttribute('aria-keyshortcuts', ariaKeys(trailerShortcut('clipMerge')));
    merge.addEventListener('click', () => mergePrev(i));
    li.append(main, split, merge);
    list.append(li);
  });
}

/* Asettelun vaihto ei pilko uudelleen eikä hukkaa käsin tehtyjä kehyksiä. */
function setLayout(value) {
  if (value !== 'wide' && value !== 'halves') return;
  layout = value;
  try { localStorage.setItem('autoraffkat.trailer.layout', value); }
  catch { /* Tallennuksen esto ei estä vientiä. */ }
  renderLayout();
  renderBoxes();
}

function renderLayout() {
  const host = $('tr-layout');
  const focused = Array.from(host.children).indexOf(document.activeElement);
  host.textContent = '';
  host.setAttribute('aria-label', T('trailer.layout'));
  ['wide', 'halves'].forEach((value) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost';
    button.setAttribute('aria-pressed', String(layout === value));
    button.textContent = T(`trailer.layout.${value}`);
    button.addEventListener('click', () => setLayout(value));
    host.append(button);
  });
  if (focused >= 0 && typeof host.children[focused].focus === 'function') {
    host.children[focused].focus();
  }
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
  renderLayout();
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
    // Paneelin kehys alkaa koko ruudun kehyksestä: mikään ei muutu ennen
    // kuin käyttäjä eriyttää ikkunat Option-raahauksella.
    pieces = plan.pieces.map((p) => ({
      ...p, x_panel: p.x, manual: false, manual_panel: false,
    }));
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
      pieces: pieces.map(({ start, end, x, x_panel }) => ({ start, end, x, x_panel })),
      lane: $('tr-lane').value,
      layout,
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

function setX(clientX, panel) {
  const rect = $('tr-frame').getBoundingClientRect();
  if (!rect.width || !pieces[sel]) return;
  const p = pieces[sel];
  const value = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  p[panel ? 'x_panel' : 'x'] = value;
  p[panel ? 'manual_panel' : 'manual'] = true;
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
  frame.setAttribute('aria-keyshortcuts',
    `${ariaKeys(trailerShortcut('clipLeft'))} ${ariaKeys(trailerShortcut('clipRight'))}`);
  $('tr-list').setAttribute('aria-keyshortcuts',
    `${ariaKeys(trailerShortcut('clipPrev'))} ${ariaKeys(trailerShortcut('clipNext'))}`);
  let dragging = false;
  // Muunnos jäädytetään alasvetoon: Optionin lipsahtaminen kesken raahauksen
  // ei vaihda kohde-ikkunaa (eikä kehys hyppää).
  let dragPanel = false;
  frame.addEventListener('pointerdown', (e) => {
    dragging = true;
    dragPanel = !!e.altKey;
    frame.setPointerCapture(e.pointerId);
    setX(e.clientX, dragPanel);
    renderList();
  });
  frame.addEventListener('pointermove', (e) => { if (dragging) setX(e.clientX, dragPanel); });
  frame.addEventListener('pointerup', () => {
    dragging = false;
    dragPanel = false;
    document.body.classList.remove('tr-panel-drag');
    renderList();
  });
  // Option pohjassa: paneeli-ikkuna korostuu ja kursori vaihtuu.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Alt') document.body.classList.add('tr-panel-drag');
  });
  document.addEventListener('keyup', (e) => {
    if (e.key === 'Alt' && !dragging) document.body.classList.remove('tr-panel-drag');
  });
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

/* Näppäimet rekisterissä, kuten pääsivulla (shortcuts.js): ↑/↓ valitsee palan,
   ←/→ siirtää kehystä (⇧ suurempi askel), M yhdistää edelliseen. Vihjeet ja
   aria-keyshortcuts johdetaan samoista riveistä. */
const NUDGE = 0.01;
const NUDGE_SHIFT = 0.05;
const TRAILER_SHORTCUTS = [
  { id: 'clipPrev', group: 'clip', label: 'trailer.prev', combos: [{ key: 'ArrowUp' }],
    scope: ['page'], run: () => selectPiece(sel - 1) },
  { id: 'clipNext', group: 'clip', label: 'trailer.next', combos: [{ key: 'ArrowDown' }],
    scope: ['page'], run: () => selectPiece(sel + 1) },
  { id: 'clipLeft', group: 'clip', label: 'trailer.nudgeLeft',
    combos: [{ key: 'ArrowLeft' }, { shift: true, key: 'ArrowLeft' }],
    scope: ['page'], run: (e) => nudge(-(e && e.shiftKey ? NUDGE_SHIFT : NUDGE)) },
  { id: 'clipRight', group: 'clip', label: 'trailer.nudgeRight',
    combos: [{ key: 'ArrowRight' }, { shift: true, key: 'ArrowRight' }],
    scope: ['page'], run: (e) => nudge(e && e.shiftKey ? NUDGE_SHIFT : NUDGE) },
  { id: 'clipPanelLeft', group: 'clip', label: 'trailer.nudgePanelLeft',
    combos: [{ alt: true, key: 'ArrowLeft' }, { alt: true, shift: true, key: 'ArrowLeft' }],
    scope: ['page'], run: (e) => nudge(-(e && e.shiftKey ? NUDGE_SHIFT : NUDGE), true) },
  { id: 'clipPanelRight', group: 'clip', label: 'trailer.nudgePanelRight',
    combos: [{ alt: true, key: 'ArrowRight' }, { alt: true, shift: true, key: 'ArrowRight' }],
    scope: ['page'], run: (e) => nudge(e && e.shiftKey ? NUDGE_SHIFT : NUDGE, true) },
  { id: 'clipMerge', group: 'clip', label: 'trailer.merge', combos: [{ key: 'm' }],
    scope: ['page'], run: () => mergePrev(sel) },
];

const trailerShortcut = (rowId) => TRAILER_SHORTCUTS.find((s) => s.id === rowId);

document.addEventListener('keydown', (e) => {
  /* Lomakekentissä (myös liukusäädin) nuolet ovat kentän omia. */
  const t = e.target && e.target.tagName;
  if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') return;
  shortcutKeyIn(TRAILER_SHORTCUTS, e, 'page', null);
});

/* Natiivivalikot: sama silta kuin pääsivulla (app.js startNativeMenu), mutta
   trailer-sivun komennoilla. Ilman pywebview-käärettä ei tehdä mitään. */
function trailerEnv() {
  const cur = pieces[sel];
  const usable = (cmd) => {
    if (cmd === 'trailer-back') return true;
    if (cmd === 'trailer-export') return !!plan && !busy;
    if (cmd === 'clip-prev') return sel > 0;
    if (cmd === 'clip-next') return sel < pieces.length - 1;
    if (cmd === 'clip-left' || cmd === 'clip-right') return pieces.length > 0;
    if (cmd === 'clip-split') return !!cur && cur.end - cur.start >= 0.6;
    if (cmd === 'clip-merge-prev') return sel > 0;
    return false;
  };
  const run = (cmd) => {
    if (cmd === 'trailer-back') window.location.href = '/';
    else if (cmd === 'trailer-export') $('tr-export').click();
    else if (cmd === 'clip-prev') selectPiece(sel - 1);
    else if (cmd === 'clip-next') selectPiece(sel + 1);
    else if (cmd === 'clip-left') nudge(-NUDGE);
    else if (cmd === 'clip-right') nudge(NUDGE);
    else if (cmd === 'clip-split') splitAt(sel);
    else if (cmd === 'clip-merge-prev') mergePrev(sel);
  };
  return {
    T, usable, run,
    sheetOpen: () => false,
    keysText: (rowId) => {
      const row = trailerShortcut(rowId);
      return row ? comboText(row.combos[0], onMac()) : '';
    },
  };
}

function startNativeMenu() {
  if (typeof createNativeMenuSync !== 'function') return;
  const nativeSync = createNativeMenuSync({
    getSpec: () => nativeMenuSpec(trailerEnv(), TRAILER_MENUS),
    getApi: () => (typeof window !== 'undefined' && window.pywebview
      ? window.pywebview.api : null),
    hasFocus: () => typeof document.hasFocus !== 'function' || document.hasFocus(),
    onActive: () => document.body.classList.add('native-menus'),
  });
  window.__autoraffkatNativeRun = (choice) => runNativeChoice(choice, trailerEnv());
  setInterval(() => nativeSync.push(false), 750);
  window.addEventListener('focus', () => nativeSync.push(true));
  window.addEventListener('pywebviewready', () => nativeSync.push(true));
}

start();
startNativeMenu();
