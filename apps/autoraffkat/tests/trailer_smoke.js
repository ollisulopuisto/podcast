'use strict';

/* Trailer-sivun savutesti: trailer.js valeselaimessa.
 *
 * `node --check` ei huomaa määrittelemätöntä muuttujaa tai käsittelijää joka
 * kaatuu vasta klikatessa. Tämä lataa i18n.js:n ja trailer.js:n, antaa sille
 * suunnitelman ja laukaisee jokaisen käsittelijän.
 *
 * Käyttö: node trailer_smoke.js <static-hakemisto> <kieli>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [staticDir, lang] = process.argv.slice(2);
const created = [];
const registry = new Map();

function makeElement(tag) {
  const classes = new Set();
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _handlers: {},
    children: [],
    dataset: {},
    style: {},
    attrs: {},
    value: '',
    textContent: '',
    className: '',
    disabled: false,
    complete: true,
    naturalWidth: 640,
    naturalHeight: 360,
    width: 202,
    height: 360,
    classList: {
      _set: classes,
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
      contains: (c) => classes.has(c),
    },
    addEventListener(type, fn) { (el._handlers[type] = el._handlers[type] || []).push(fn); },
    setAttribute(k, v) { el.attrs[k] = v; },
    append(...kids) { el.children.push(...kids); },
    appendChild(kid) { el.children.push(kid); return kid; },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 225 }),
    setPointerCapture() {},
    select() {},
    getContext: () => new Proxy({}, { get: (_, k) => (k === 'canvas' ? el : () => {}), set: () => true }),
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text === undefined ? el.children.map((c) => c.textContent || '').join('') : el._text; },
    set(v) { el.children = []; el._text = v === '' ? undefined : v; },
  });
  created.push(el);
  return el;
}

const sels = new Map();
const document = {
  documentElement: {},
  createElement: makeElement,
  getElementById(id) {
    if (!registry.has(id)) { const el = makeElement('div'); el.id = id; registry.set(id, el); }
    return registry.get(id);
  },
  querySelectorAll: () => [],
};

const plan = {
  ok: true, path: '/x/t.mp4', name: 't', width: 1920, height: 1080, fps: 25,
  duration: 60, has_audio: true,
  pieces: [{ start: 0, end: 20, x: 0.2 }, { start: 20, end: 40, x: 0.5 }, { start: 40, end: 60, x: 0.8 }],
};
const calls = [];
const context = {
  document,
  location: { search: '?path=%2Fx%2Ft.mp4' },
  URLSearchParams,
  fetch: async (url, init) => {
    calls.push([String(url), init && init.body]);
    const table = {
      '/api/state': { language: lang },
      '/api/trailer/plan': plan,
      '/api/trailer/pick': { path: '/x/t.mp4' },
      '/api/trailer/export': { ok: true, path: '/x/t trailer.fcpxml', pieces: 3 },
      '/api/reveal': { ok: true },
    };
    const key = String(url).split('?')[0];
    if (!(key in table)) throw new Error(`savutesti: tuntematon reitti ${url}`);
    return { ok: true, json: async () => table[key] };
  },
  console, JSON, Math, Object, Number, String, Array, Boolean, Date, Promise,
  encodeURIComponent,
};
context.globalThis = context;
vm.createContext(context);
for (const name of ['i18n.js', 'trailer.js']) {
  vm.runInContext(fs.readFileSync(path.join(staticDir, name), 'utf8'), context, { filename: name });
}

let failures = 0;
const fail = (msg) => { console.error(`trailer_smoke: ${msg}`); failures += 1; };
const tick = () => new Promise((r) => setImmediate(r));
const id = (name) => document.getElementById(name);
const fire = async (el, type, ev) => {
  for (const fn of el._handlers[type] || []) await fn({ clientX: 100, pointerId: 1, ...ev });
  await tick();
};
const buttons = (label) => created.filter((e) => e.tagName === 'BUTTON' && e.textContent === label);

(async () => {
  try {
    for (let i = 0; i < 5; i++) await tick();
    if (!calls.some(([u]) => u === '/api/trailer/plan')) fail('suunnitelmaa ei pyydetty ?path=:sta');
    if (id('tr-list').children.length !== 3) fail(`palalistassa ${id('tr-list').children.length} riviä, odotettiin 3`);

    // jako: valittu pala puolittuu ja ruutu seuraa uutta keskikohtaa
    const T = (k) => vm.runInContext(`T(${JSON.stringify(k)})`, context);
    const split = buttons(T('trailer.split'))[0];
    if (!split) fail('jakopainiketta ei löytynyt');
    else {
      await fire(split, 'click');
      const t = new URLSearchParams(id('tr-img').src.split('?')[1]).get('t');
      if (Number(t) !== 5) fail(`jaon jälkeen ruutu t=${t}, odotettiin 5 (ensimmäisen puolikkaan keskikohta)`);
      if (id('tr-list').children.length !== 4) fail('jako ei lisännyt riviä');
    }
    // yhdistys
    const merge = buttons(T('trailer.merge'))[0];
    if (merge) await fire(merge, 'click');
    if (id('tr-list').children.length !== 3) fail('yhdistys ei poistanut riviä');

    // käsin kehystys, kaista, tila, toteutus
    await fire(id('tr-frame'), 'pointerdown');
    await fire(id('tr-frame'), 'pointermove');
    await fire(id('tr-frame'), 'pointerup');
    id('tr-lane').value = 'bottom';
    await fire(id('tr-lane'), 'change');
    id('tr-mode').value = 'every';
    await fire(id('tr-mode'), 'change');
    id('tr-sens').value = '40';
    await fire(id('tr-sens'), 'input');
    await fire(id('tr-apply'), 'click');
    const resolve = buttons(T('export.dest.resolve'))[0];
    if (resolve) await fire(resolve, 'click');
    await fire(id('tr-open'), 'click');
    await fire(id('tr-export'), 'click');
    const sent = calls.filter(([u]) => u === '/api/trailer/export').pop();
    if (!sent) fail('vientiä ei lähetetty');
    else {
      const body = JSON.parse(sent[1]);
      if (body.dialect !== 'resolve' || body.lane !== 'bottom') fail('vientiin ei päätynyt valinta');
      if (!Array.isArray(body.pieces) || !body.pieces.length) fail('viennissä ei paloja');
    }
    if (!String(id('tr-exported').textContent).length) fail('viennin vahvistusta ei näytetty');
    if (String(id('tr-banner').textContent).length) fail(`bannerissa virhe: ${id('tr-banner').textContent}`);
  } catch (err) {
    fail(`poikkeus: ${err && err.stack || err}`);
  }
  if (failures) process.exit(1);
  console.log('trailer_smoke: ok');
})();
