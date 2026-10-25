'use strict';

/* Pikanäppäinten mittari.
 *
 * Lataa i18n.js:n ja app.js:n valeselaimeen, painaa näppäimiä ja kertoo
 * JSON-muodossa mitä tapahtui. Väitteet tekee test_shortcuts.py; tämä vain
 * mittaa, jotta jokainen lupaus on oma testinsä eikä yksi kaatuminen peitä
 * muita.
 *
 * Valeselain on tarkoituksella pienempi kuin ui_smoke.js:n: tässä ei piirretä
 * raitoja eikä esikatselua, vaan otsikon painikkeet, ohjeikkuna ja yksi
 * raitakortti. Sen sijaan tämä tuntee puun — vanhemmat, kohdistuksen ja
 * yksinkertaiset valitsimet — koska kohdistuksen loukku ja palautus ovat
 * juuri sitä mitä mitataan.
 *
 * Käyttö: node ui_shortcuts.js <static-hakemisto> <mac|other>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [staticDir, platform] = process.argv.slice(2);

const NAVIGATORS = {
  mac: { platform: 'MacIntel', userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)' },
  other: { platform: 'Linux x86_64', userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' },
};

/* ------------------------------------------------------------ valepuu */

let doc = null;

function matchesOne(el, sel) {
  sel = sel.trim();
  if (!sel) return false;
  if (sel.startsWith('.')) return el.classList.contains(sel.slice(1));
  if (sel.startsWith('[')) {
    const m = /^\[([a-z-]+)(?:="([^"]*)")?\]/.exec(sel);
    if (!m) return false;
    const negated = /:not\(\[tabindex="-1"\]\)/.test(sel);
    const value = m[1].startsWith('data-')
      ? el.dataset[m[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())]
      : el.attributes[m[1]];
    if (value === undefined) return false;
    if (m[2] !== undefined && String(value) !== m[2]) return false;
    if (negated && String(el.attributes.tabindex) === '-1') return false;
    return true;
  }
  return el.tagName === sel.toUpperCase();
}

function makeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [],
    parentNode: null,
    dataset: {},
    attributes: {},
    style: { setProperty() {}, removeProperty() {} },
    _handlers: {},
    _text: '',
    _id: '',
    disabled: false,
    hidden: false,
    get id() { return this._id; },
    set id(v) { this._id = String(v); this.attributes.id = this._id; },
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join('');
    },
    set textContent(v) {
      this.children.forEach((c) => { c.parentNode = null; });
      this.children = [];
      this._text = String(v);
    },
    classList: null,
    append(...nodes) {
      nodes.forEach((n) => {
        if (typeof n === 'string') n = doc.createTextNode(n);
        if (n.parentNode) n.parentNode.children.splice(n.parentNode.children.indexOf(n), 1);
        n.parentNode = this;
        this.children.push(n);
      });
    },
    appendChild(n) { this.append(n); return n; },
    prepend(...nodes) {
      nodes.reverse().forEach((n) => {
        if (typeof n === 'string') n = doc.createTextNode(n);
        n.parentNode = this;
        this.children.unshift(n);
      });
    },
    remove() {
      if (this.parentNode) {
        this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1);
        this.parentNode = null;
      }
    },
    replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === 'id') this._id = String(value);
    },
    getAttribute(name) {
      return this.attributes[name] === undefined ? null : this.attributes[name];
    },
    removeAttribute(name) { delete this.attributes[name]; },
    hasAttribute(name) { return this.attributes[name] !== undefined; },
    addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); },
    removeEventListener(type, fn) {
      this._handlers[type] = (this._handlers[type] || []).filter((f) => f !== fn);
    },
    focus() { doc.activeElement = this; },
    blur() { if (doc.activeElement === this) doc.activeElement = doc.body; },
    contains(node) {
      for (let n = node; n; n = n.parentNode) if (n === this) return true;
      return false;
    },
    closest(sel) {
      for (let n = this; n && n.tagName; n = n.parentNode) {
        if (sel.split(',').some((s) => matchesOne(n, s))) return n;
      }
      return null;
    },
    querySelectorAll(sel) {
      const out = [];
      const walk = (n) => n.children.forEach((c) => {
        if (!c.tagName) return;
        if (sel.split(',').some((s) => matchesOne(c, s))) out.push(c);
        walk(c);
      });
      walk(this);
      return out;
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    click() { fire(this, 'click', {}); },
    getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 20 }; },
    select() {},
  };
  const set = new Set();
  el.classList = {
    add(...n) { n.forEach((x) => set.add(x)); },
    remove(...n) { n.forEach((x) => set.delete(x)); },
    toggle(n, on) {
      if (on === undefined ? !set.has(n) : on) set.add(n); else set.delete(n);
    },
    contains(n) { return set.has(n); },
  };
  Object.defineProperty(el, 'className', {
    get() { return [...set].join(' '); },
    set(v) { set.clear(); String(v).split(/\s+/).filter(Boolean).forEach((x) => set.add(x)); },
  });
  if (el.tagName === 'DIALOG') {
    /* Oikea <dialog>: modaali avaus ja sulku, ja sulkeminen kertoo itsestään
       close-tapahtumalla kuten selain. */
    el.open = false;
    el.showModal = function showModal() { this.open = true; this.attributes.open = ''; };
    el.close = function close() {
      if (!this.open) return;
      this.open = false;
      delete this.attributes.open;
      fire(this, 'close', {});
    };
  }
  return el;
}

function fire(el, type, init) {
  const event = Object.assign({
    type, target: el, defaultPrevented: false,
    metaKey: false, ctrlKey: false, altKey: false, shiftKey: false,
  }, init);
  event.preventDefault = () => { event.defaultPrevented = true; };
  event.stopPropagation = () => { event.stopped = true; };
  for (let n = el; n && !event.stopped; n = n.parentNode) {
    (n._handlers && n._handlers[type] || []).slice().forEach((fn) => fn.call(n, event));
  }
  return event;
}

/* ------------------------------------------------------------ lataus */

const windowHandlers = {};
const byId = new Map();

doc = {
  body: null,
  activeElement: null,
  createElement: (tag) => makeElement(tag),
  createTextNode: (text) => ({ nodeType: 3, _t: String(text), children: [],
    get textContent() { return this._t; }, parentNode: null }),
  getElementById(id) {
    if (byId.has(id)) return byId.get(id);
    const hit = doc.body.querySelectorAll(`[id="${id}"]`)[0];
    if (hit) return hit;
    const made = makeElement('div');
    made.id = id;
    doc.body.append(made);
    byId.set(id, made);
    return made;
  },
  querySelectorAll(sel) { return doc.body.querySelectorAll(sel); },
  querySelector(sel) { return doc.body.querySelector(sel); },
  addEventListener() {},
};
doc.body = makeElement('body');
doc.activeElement = doc.body;

/* Sivun kiinteät elementit index.html:n mukaan: painikkeet ja ohjeikkuna. */
for (const [id, tag] of [['open', 'button'], ['reload', 'button'], ['relink', 'button'],
  ['render', 'button'], ['render-stop', 'button'], ['export', 'button'],
  ['shortcuts', 'button'], ['shortcut-sheet', 'dialog'], ['project-title', 'input']]) {
  const el = makeElement(tag);
  el.id = id;
  doc.body.append(el);
  byId.set(id, el);
}

const minimalState = {
  error: 'savutesti: ei projektia', languages: ['fi', 'en'], language: 'fi',
  tracks: [], globals: {}, audio: {}, mix: { progress: {} },
};

const context = {
  document: doc,
  navigator: NAVIGATORS[platform] || NAVIGATORS.other,
  window: {
    addEventListener(type, fn) { (windowHandlers[type] = windowHandlers[type] || []).push(fn); },
    devicePixelRatio: 1,
  },
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  fetch: async () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(minimalState)),
    text: async () => '' }),
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  AbortController: function AbortController() { this.abort = () => {}; this.signal = null; },
  console, JSON, Math, Object, Number, String, Array, Boolean, Date, Set, Map,
  encodeURIComponent,
};
context.globalThis = context;
vm.createContext(context);
for (const name of ['i18n.js', 'app.js']) {
  vm.runInContext(fs.readFileSync(path.join(staticDir, name), 'utf8'), context, { filename: name });
}

const ev = (code) => vm.runInContext(code, context);
const has = (name) => ev(`typeof ${name} !== 'undefined'`);

/* Näppäimen painallus kuten selain: ensin kohde ja sen vanhemmat, sitten
   ikkuna. */
function press(target, init) {
  const event = fire(target, 'keydown', init);
  if (!event.stopped) (windowHandlers.keydown || []).forEach((fn) => fn(event));
  return event;
}

/* Vakoojat toiminnoille. Rekisterin toiminnot kutsuvat funktioita nimeltä,
   joten globaalin korvaaminen riittää. */
const spied = { exportXml: 0, openXml: 0 };
for (const name of Object.keys(spied)) {
  context[name] = function spy() { spied[name] += 1; };
}

const sheet = () => doc.getElementById('shortcut-sheet');
const sheetOpen = () => !!sheet().open || sheet().attributes.open !== undefined;

(async () => {
  await new Promise((r) => setImmediate(r));   // boot() valmiiksi

  const out = { platform, errors: [] };
  const guard = (label, fn) => {
    try { return fn(); } catch (err) { out.errors.push(`${label}: ${err.message}`); return null; }
  };

  /* -------------------------------------------------- rekisteri ja tekstit */
  out.strings = { fi: ev('Object.keys(STRINGS.fi)'), en: ev('Object.keys(STRINGS.en)') };
  out.registry = has('SHORTCUTS') ? ev(`SHORTCUTS.map((s) => ({
    id: s.id, group: s.group, label: s.label, scope: s.scope || [],
    control: s.control || null, text: s.text || null, pointer: s.pointer || null,
    combos: (s.combos || []).map((c) => ({ key: c.key, mod: !!c.mod })),
  }))`) : [];
  out.groups = has('SHORTCUT_GROUPS') ? ev('SHORTCUT_GROUPS.slice()') : [];

  /* -------------------------------------------------- ohjeikkuna kielittäin */
  out.sheet = {};
  out.hints = {};
  for (const lang of ['fi', 'en']) {
    guard(`kieli ${lang}`, () => {
      context.setLang(lang);
      ev('renderStatic()');
    });
    const rows = sheet().querySelectorAll('[data-shortcut]');
    out.sheet[lang] = {
      ids: rows.map((r) => r.dataset.shortcut),
      rows: Object.fromEntries(rows.map((r) => [r.dataset.shortcut, r.textContent])),
      text: sheet().textContent,
      labelledby: sheet().getAttribute('aria-labelledby'),
    };
    out.hints[lang] = {};
    for (const id of ['open', 'export', 'shortcuts']) {
      const el = doc.getElementById(id);
      const kbd = el.querySelectorAll('kbd');
      out.hints[lang][id] = {
        text: el.textContent,
        kbd: kbd.map((k) => k.textContent),
        title: el.getAttribute('title'),
        aria: el.getAttribute('aria-keyshortcuts'),
      };
    }
    out.hints[lang].labels = Object.fromEntries(out.registry.map((s) => [s.id, context.T(s.label)]));
    out.hints[lang].groups = Object.fromEntries(out.groups.map((g) => [g, context.T(`keys.group.${g}`)]));
  }

  out.macLike = has('isMacLike') ? Object.fromEntries([
    ['MacIntel', { platform: 'MacIntel' }],
    ['iPad', { platform: 'iPad' }],
    ['uaData macOS', { userAgentData: { platform: 'macOS' } }],
    ['Win32', { platform: 'Win32' }],
    ['Linux', { platform: 'Linux x86_64' }],
    ['uaData Windows', { userAgentData: { platform: 'Windows' }, platform: 'Win32' }],
    ['ua only Mac', { userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)' }],
    ['none', null],
  ].map(([name, nav]) => [name, !!context.isMacLike(nav)])) : {};

  /* -------------------------------------------------- käsittelijän reaktiot */
  const KEYS = [];
  for (let c = 32; c < 127; c += 1) KEYS.push(String.fromCharCode(c));
  KEYS.push('Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown',
    'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown');
  for (let f = 1; f <= 12; f += 1) KEYS.push(`F${f}`);
  const MODS = [{}, { shiftKey: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true },
    { ctrlKey: true, shiftKey: true }, { metaKey: true, shiftKey: true },
    { metaKey: true, altKey: true }];

  const field = doc.getElementById('project-title');
  const button = doc.getElementById('open');
  /* Mihin luettelon tilaan painallus osui, tai null. Kortilta näppäin
     kuplii ikkunaan, joten kortin painallus voi osua myös sivun riviin. */
  const matched = (scopes, e) => {
    if (!has('SHORTCUTS') || !has('matchesCombo')) return null;
    for (const scope of scopes) {
      if (ev('SHORTCUTS').some((s) => (s.scope || []).includes(scope)
        && (s.combos || []).some((c) => context.matchesCombo(c, e)))) return scope;
    }
    return null;
  };

  const battery = (name, setup, target, scopes, reset) => {
    const rows = [];
    for (const key of KEYS) {
      for (const mods of MODS) {
        setup();
        const was = { open: sheetOpen(), focus: doc.activeElement,
          calls: spied.exportXml + spied.openXml,
          picked: has('picked') ? ev('picked') : null };
        const event = guard(`${name} ${key}`, () => press(target(), Object.assign({ key }, mods)));
        if (!event) continue;
        const reacted = event.defaultPrevented || was.open !== sheetOpen()
          || was.calls !== spied.exportXml + spied.openXml
          || (has('picked') && was.picked !== ev('picked'));
        if (reacted) {
          rows.push({ key, mods: Object.keys(mods), matched: matched(scopes, event) });
        }
        reset();
      }
    }
    return rows;
  };
  const closeAll = () => {
    if (sheetOpen()) {
      if (has('closeShortcuts')) ev('closeShortcuts()');
      else if (sheet().close) sheet().close();
    }
  };
  const openSheet = () => {
    if (!sheetOpen() && has('openShortcuts')) ev('openShortcuts()');
  };

  out.battery = {
    page: battery('sivu', () => { closeAll(); button.focus(); }, () => button, ['page'], closeAll),
    field: battery('kenttä', () => { closeAll(); field.focus(); }, () => field, ['page'], closeAll),
    sheet: battery('ikkuna', () => { openSheet(); }, () => doc.activeElement, ['sheet'], closeAll),
  };
  closeAll();

  /* -------------------------------------------------- tilanteet */
  const sc = {};
  closeAll();
  const before = doc.getElementById('reload');
  before.focus();
  let e = press(before, { key: '?', shiftKey: true });
  sc.questionOpens = sheetOpen();
  sc.questionPrevented = e.defaultPrevented;
  sc.focusInside = sheet().contains(doc.activeElement) && doc.activeElement !== sheet()
    ? 'child' : (doc.activeElement === sheet() ? 'sheet' : 'outside');
  /* Loukku: Tab ja vaihto+Tab pysyvät ikkunassa, ja ulos karannut
     kohdistus palaa sisään. */
  e = press(doc.activeElement, { key: 'Tab' });
  sc.tabStaysInside = sheet().contains(doc.activeElement);
  sc.tabPrevented = e.defaultPrevented;
  e = press(doc.activeElement, { key: 'Tab', shiftKey: true });
  sc.shiftTabStaysInside = sheet().contains(doc.activeElement);
  doc.getElementById('export').focus();
  press(doc.activeElement, { key: 'Tab' });
  sc.escapedFocusReturns = sheet().contains(doc.activeElement);
  /* Kysymysmerkki ikkunan sisällä ei sulje sitä kahdesti eikä kaada. */
  e = press(doc.activeElement, { key: 'Escape' });
  sc.escapeCloses = !sheetOpen();
  sc.escapePrevented = e.defaultPrevented;
  sc.focusReturned = doc.activeElement === before;
  /* Ikkunan sulkeminen ? -näppäimellä. */
  before.focus();
  press(before, { key: '?' });
  press(doc.activeElement, { key: '?' });
  sc.questionToggles = !sheetOpen();
  sc.toggleFocusReturned = doc.activeElement === before;
  /* Sulkupainike ikkunassa. */
  before.focus();
  press(before, { key: '?' });
  const closer = sheet().querySelectorAll('button')[0] || null;
  sc.closeButton = closer ? { text: closer.textContent, aria: closer.getAttribute('aria-label') } : null;
  if (closer) fire(closer, 'click', {});
  sc.closeButtonCloses = !sheetOpen();
  closeAll();
  /* Selaimen oma sulku (dialogin Escape) palauttaa kohdistuksen myös. */
  before.focus();
  press(before, { key: '?' });
  if (sheet().close) sheet().close();
  sc.nativeCloseReturnsFocus = !sheetOpen() && doc.activeElement === before;
  closeAll();
  /* Otsikon painike avaa ikkunan. */
  const opener = doc.getElementById('shortcuts');
  opener.focus();
  fire(opener, 'click', {});
  sc.buttonOpens = sheetOpen();
  press(doc.activeElement, { key: 'Escape' });
  sc.buttonFocusReturned = doc.activeElement === opener;
  closeAll();
  /* Kirjoittaminen kenttään ei avaa ikkunaa. */
  sc.typed = {};
  for (const [name, tag, attrs] of [['text input', 'input', { type: 'text' }],
    ['search input', 'input', { type: 'search' }], ['number input', 'input', { type: 'number' }],
    ['textarea', 'textarea', {}], ['select', 'select', {}],
    ['contenteditable', 'div', { contenteditable: 'true' }]]) {
    const el = makeElement(tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    if (attrs.type) el.type = attrs.type;
    if (attrs.contenteditable) el.isContentEditable = true;
    doc.body.append(el);
    el.focus();
    const typed = press(el, { key: '?', shiftKey: true });
    sc.typed[name] = { opened: sheetOpen(), prevented: typed.defaultPrevented };
    closeAll();
  }
  /* Valintaruutu ei ole kirjoituskenttä: ? toimii siinäkin. */
  const box = makeElement('input');
  box.setAttribute('type', 'checkbox');
  box.type = 'checkbox';
  doc.body.append(box);
  box.focus();
  press(box, { key: '?' });
  sc.checkboxOpens = sheetOpen();
  closeAll();
  /* Modifioitu ? on selaimen tai käyttöjärjestelmän, ei meidän. */
  button.focus();
  press(button, { key: '?', metaKey: true });
  sc.cmdQuestionOpens = sheetOpen();
  closeAll();
  /* Vanhat pikanäppäimet toimivat kuten ennen, myös kentästä. */
  const calls0 = { ...spied };
  button.focus();
  e = press(button, { key: 'e', metaKey: true });
  sc.cmdE = { exports: spied.exportXml - calls0.exportXml, prevented: e.defaultPrevented };
  e = press(button, { key: 'E', ctrlKey: true, shiftKey: true });
  sc.ctrlShiftE = spied.exportXml - calls0.exportXml;
  field.focus();
  e = press(field, { key: 'o', ctrlKey: true });
  sc.ctrlOFromField = { opens: spied.openXml - calls0.openXml, prevented: e.defaultPrevented };
  /* Ikkunan ollessa auki ⌘E sulkee sen ja vie. */
  before.focus();
  press(before, { key: '?' });
  const exp0 = spied.exportXml;
  press(doc.activeElement, { key: 'e', metaKey: true });
  sc.cmdEFromSheet = { exports: spied.exportXml - exp0, closed: !sheetOpen() };
  closeAll();
  /* Kielen vaihto kesken avoimen ikkunan. */
  context.setLang('fi');
  ev('renderStatic()');
  before.focus();
  press(before, { key: '?' });
  const fiText = sheet().textContent;
  context.setLang('en');
  guard('kielen vaihto', () => ev('renderStatic()'));
  sc.langSwitch = { fi: fiText, en: sheet().textContent, stillOpen: sheetOpen(),
    focusInside: sheet().contains(doc.activeElement) };
  closeAll();
  sc.redrawAllRendersStatic = /function redrawAll\(\)\s*\{\s*renderStatic\(\);/.test(
    fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8'));

  out.scenarios = sc;
  out.keydownListeners = Object.keys(windowHandlers).includes('keydown')
    ? windowHandlers.keydown.length : 0;
  process.stdout.write(JSON.stringify(out));
})().catch((err) => {
  process.stderr.write(`${err.stack}\n`);
  process.exit(1);
});
