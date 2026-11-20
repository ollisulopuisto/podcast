'use strict';

/* Trailer-sivun kehystysmittari.
 *
 * Lataa i18n.js:n, shortcuts.js:n ja trailer.js:n valeselaimeen, antaa
 * sivulle valmiin pilkonnaksi tekeytyvän palvelinvastauksen ja mittaa,
 * mitä raahaukset ja näppäimet tekevät palojen kehyksille (x = koko ruutu,
 * x_panel = puolikaspaneeli) ja palalistan teksteille. Väitteet tekee
 * test_trailer_js.py; tämä vain mittaa.
 *
 * Käyttö: node ui_trailer.js <static-hakemisto>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [staticDir] = process.argv.slice(2);

/* ------------------------------------------------------------ valepuu */

function makeClassList(el) {
  const set = new Set();
  return {
    add: (...names) => names.forEach((n) => set.add(n)),
    remove: (...names) => names.forEach((n) => set.delete(n)),
    toggle: (name, force) => {
      const want = force === undefined ? !set.has(name) : !!force;
      if (want) set.add(name); else set.delete(name);
      return want;
    },
    contains: (name) => set.has(name),
  };
}

function makeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [],
    parentNode: null,
    dataset: {},
    attributes: {},
    style: {},
    _text: '',
    value: '',
    disabled: false,
    readOnly: false,
    naturalWidth: 1920,
    naturalHeight: 1080,
    complete: true,
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join('');
    },
    set textContent(v) {
      this.children = [];
      this._text = String(v);
    },
    append(...nodes) { this.children.push(...nodes); },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return this.attributes[name] ?? null; },
    addEventListener(type, fn) {
      (this._handlers[type] = this._handlers[type] || []).push(fn);
    },
    _handlers: {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 200 }; },
    setPointerCapture() {},
    scrollIntoView() {},
    click() { (this._handlers.click || []).forEach((fn) => fn({})); },
    getContext() { return canvas2d; },
    width: 540,
    height: 960,
  };
  el.classList = makeClassList(el);
  return el;
}

const draws = [];
const outlines = [];
const canvas2d = {
  clearRect() { draws.length = 0; outlines.length = 0; }, drawImage(...args) { draws.push(args.slice(1)); }, setLineDash() {}, strokeRect(...args) { outlines.push(args); },
  fillRect() {}, fillText() {},
  strokeStyle: '', lineWidth: 0, fillStyle: '', font: '', textAlign: '',
};

const byId = new Map();
function elById(id) {
  if (!byId.has(id)) byId.set(id, makeElement('div'));
  return byId.get(id);
}
// Lomakearvot, joita sivu lukee käynnistyessä ja latautuessa.
for (const [id, value] of [['tr-lane', 'top'], ['tr-mode', 'scenes'],
  ['tr-sens', '50'], ['tr-min', '0.6'], ['tr-every', '3']]) {
  elById(id).value = value;
}
// Kuvan lataus: src:n asetus laukaisee onloadin, kuten selaimessa.
const img = elById('tr-img');
Object.defineProperty(img, 'src', {
  set(_) { Promise.resolve().then(() => { if (this.onload) this.onload(); }); },
  get() { return ''; },
});

const doc = {
  body: makeElement('body'),
  documentElement: makeElement('html'),
  activeElement: null,
  _handlers: {},
  getElementById: (id) => elById(id),
  createElement: (tag) => makeElement(tag),
  createTextNode: (text) => ({ textContent: String(text) }),
  querySelectorAll: () => [],
  addEventListener(type, fn) {
    (this._handlers[type] = this._handlers[type] || []).push(fn);
  },
};

/* Palvelin: kiinteä pilkonta, vienti vain tallentaa saapuvan rungon. */
const cannedPlan = {
  ok: true, path: '/t.mp4', name: 't', width: 1920, height: 1080,
  fps: 25, duration: 8, has_audio: true,
  pieces: [{ start: 0, end: 4, x: 0.4 }, { start: 4, end: 8, x: 0.6 }],
};
const sent = [];
const fetchStub = async (url, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : null;
  if (body) sent.push({ url, body });
  if (String(url).startsWith('/api/trailer/plan')) {
    return { ok: true, json: async () => JSON.parse(JSON.stringify(cannedPlan)) };
  }
  if (String(url).startsWith('/api/trailer/export')) {
    return { ok: true, json: async () => ({ ok: true, path: '/t trailer.fcpxml', pieces: body.pieces.length }) };
  }
  return { ok: true, json: async () => ({ language: 'fi' }) };
};

const stored = new Map();
const context = {
  localStorage: { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, v) },
  document: doc,
  navigator: { platform: 'MacIntel', userAgent: 'Mozilla/5.0 (Macintosh)' },
  location: { search: '' },
  window: { addEventListener() {}, location: { href: '' } },
  fetch: fetchStub,
  setTimeout, clearTimeout, setInterval, clearInterval,
  URLSearchParams, encodeURIComponent,
  console, JSON, Math, Object, Number, String, Array, Boolean, Date, Set, Map, Promise,
};
context.globalThis = context;
vm.createContext(context);
for (const name of ['i18n.js', 'shortcuts.js', 'trailer.js']) {
  vm.runInContext(fs.readFileSync(path.join(staticDir, name), 'utf8'), context, { filename: name });
}
const ev = (code) => vm.runInContext(code, context);

/* ------------------------------------------------------------ mittaus */

const frame = elById('tr-frame');
const list = elById('tr-list');
const pointer = (type, init) =>
  (frame._handlers[type] || []).forEach((fn) => fn({ pointerId: 1, ...init }));
const key = (init) =>
  (doc._handlers.keydown || []).forEach((fn) => fn({ target: { tagName: 'DIV' }, ...init }));
const rowTexts = () => list.children.map((li) => li.textContent);
const lastExport = () => {
  for (let i = sent.length - 1; i >= 0; i -= 1) {
    if (sent[i].url === '/api/trailer/export') return sent[i].body.pieces;
  }
  return null;
};

(async () => {
  await new Promise((r) => setImmediate(r));   // start()
  await ev('load("/t.mp4")');
  await new Promise((r) => setImmediate(r));

  const out = {};
  out.initialRows = rowTexts();

  // Tavallinen raahaussarja: koko ruudun kehys liikkuu.
  pointer('pointerdown', { clientX: 700, altKey: false });
  pointer('pointermove', { clientX: 800, altKey: false });
  pointer('pointerup', { altKey: false });
  out.afterPlainDrag = { rows: rowTexts() };
  await ev('exportFcpxml()');
  out.plainExport = lastExport();

  // Option-raahaus: Option jäädytetään alasvetoon; Optionin päästö
  // kesken ei vaihda kohdetta. Valitaan ensin toinen pala.
  await ev('selectPiece(1)');
  pointer('pointerdown', { clientX: 500, altKey: true });
  pointer('pointermove', { clientX: 900, altKey: true });
  pointer('pointermove', { clientX: 950, altKey: false });   // Option lipsahti
  pointer('pointerup', { altKey: false });
  out.afterOptionDrag = { rows: rowTexts() };
  await ev('exportFcpxml()');
  out.optionExport = lastExport();

  // Näppäimet: tavalliset nuolet koko ruutuun, Option-nuolet paneeliin,
  // Vaihto suurentaa askelen kummassakin.
  key({ key: 'ArrowLeft' });
  key({ key: 'ArrowRight', shiftKey: true });
  key({ key: 'ArrowLeft', altKey: true });
  key({ key: 'ArrowRight', altKey: true, shiftKey: true });
  await ev('exportFcpxml()');
  out.keysExport = lastExport();
  out.afterKeys = { rows: rowTexts() };

  // Puolitus kopioi molemmat kehykset, yhdistys pitää edellisen.
  await ev('selectPiece(0)');
  ev('splitAt(0)');
  out.afterSplit = { rows: rowTexts() };
  ev('mergePrev(1)');
  out.afterMerge = { rows: rowTexts() };

  out.defaultLayout = ev('layout');
  const measurements = [];
  for (const choice of ['wide', 'halves']) {
    ev(`setLayout('${choice}')`);
    for (const lane of ['top', 'bottom', 'none']) {
      elById('tr-lane').value = lane;
      ev('drawComposite()');
      await ev('exportFcpxml()');
      measurements.push({choice, lane, draws: JSON.parse(JSON.stringify(draws)),
        outlines: JSON.parse(JSON.stringify(outlines)), body: sent.at(-1).body});
    }
  }
  out.layouts = measurements;
  out.remembered = Object.fromEntries(stored);
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
