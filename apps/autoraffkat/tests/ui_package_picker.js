'use strict';

/* Paketin tiedostopolut valitaan natiivilla valintaikkunalla, ei kirjoiteta.
   Valeselain piirtää paketti-paneelin ja tarkistaa: polkukenttä on vain
   luettava, Valitse-nappi kutsuu /api/pick-file ja tallentaa palautetun
   polun kortille ja pohjalle, ja Generoitu teksti kertoo puuttuvasta
   Tekstityksestä (käyttäjäraportti 2026-11-18).
 *
 * Käyttö: node ui_package_picker.js <app.js:n polku>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('node:assert/strict');

const appPath = process.argv[2];
const src = fs.readFileSync(appPath, 'utf8');

function makeElement(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [], dataset: {}, style: {}, handlers: {},
    className: '', innerHTML: '', value: '', readOnly: false,
    _text: '',
    get textContent() { return this._text; },
    /* Kuten selaimessa: tekstin asetus tyhjentää lapset. */
    set textContent(v) { this._text = v; this.children.length = 0; },
    append(...cs) { this.children.push(...cs); },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(type, fn) { this.handlers[type] = fn; },
    setAttribute() {},
    classList: { add(c) { el.className += ` ${c}`; }, remove() {}, toggle() {} },
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 20,
                                    width: 100, height: 20, x: 0, y: 0 }),
    clientWidth: 1200, width: 1200, height: 120,
  };
  return el;
}
const registry = new Map();
const documentStub = {
  createElement: (tag) => makeElement(tag),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  getElementById(id) {
    if (!registry.has(id)) registry.set(id, makeElement('div'));
    return registry.get(id);
  },
  querySelector: () => makeElement('div'),
  querySelectorAll: () => [],
  addEventListener() {},
};
const requests = [];
let pickReply = { path: '/Volumes/x/alpha.mov' };
const context = {
  document: documentStub,
  window: { addEventListener() {}, devicePixelRatio: 2 },
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  fetch: async (url, opts) => {
    requests.push({ url, body: opts && opts.body });
    return { ok: true, json: async () => pickReply };
  },
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  AbortController: function () { this.abort = () => {}; this.signal = null; },
  console, JSON, Math, Object, Number, String, Array, Boolean, Date, Promise, Error,
  encodeURIComponent,
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(path.dirname(appPath), 'i18n.js'), 'utf8'),
  context, { filename: 'i18n.js' });
vm.runInContext(src.replace(/\bboot\(\);\s*$/, ''), context, { filename: 'app.js' });

function walk(node, out = []) {
  out.push(node);
  (node.children || []).forEach((c) => walk(c, out));
  return out;
}
const all = () => walk(registry.get('package-panel'));

vm.runInContext(`
  state = { generated_available: false, package: {
    intro: { mode: 'file', path: '', text: '', duration: 5 },
    outro: { mode: 'generated', path: '', text: '', duration: 5 },
    credits: { mode: 'off', placement: 'end', path: '', text: '', duration: 8 },
    beds: { mode: 'intro_outro', intro_path: '', outro_path: '',
            throughout_path: '', keep_music_level: false } } };
  renderPackage();
`, context);

(async () => {
  let nodes = all();
  const fields = nodes.filter((n) => n.className === 'path-field');
  assert.equal(fields.length, 3, 'intro-tiedosto ja kaksi pohjaa pitää olla valintakenttiä');
  fields.forEach((f) => assert.equal(f.children[0].readOnly, true,
    'polkukenttä ei saa ottaa kirjoitettua tekstiä'));
  const texts = nodes.filter((n) => n.tagName === 'P').map((n) => n.textContent);
  assert.ok(texts.some((t) => t.includes('AUTORAFFKAT_TEKSTITYS')),
            'puuttuva Tekstitys ei näy käyttäjälle: ' + texts.join('|'));
  const options = nodes.filter((n) => n.tagName === 'OPTION').map((n) => n.textContent);
  assert.ok(options.some((t) => t.includes('Tekstitys puuttuu')),
            'Generoitu teksti -valinta ei kerro puutteesta');

  const choose = fields[0].children.find((c) => c.textContent === 'Valitse…');
  await choose.handlers.click();
  const pick = requests.find((r) => r.url === '/api/pick-file');
  assert.ok(pick, 'Valitse ei kutsunut /api/pick-file');
  assert.equal(vm.runInContext('state.package.intro.path', context), '/Volumes/x/alpha.mov');
  nodes = all();
  const shown = nodes.filter((n) => n.className === 'path-field')[0].children[0];
  assert.equal(shown.value, '/Volumes/x/alpha.mov', 'valittu polku ei näy kentässä');

  /* Peruttu valinta (tyhjä polku) ei muuta mitään. */
  pickReply = { path: '' };
  const again = nodes.filter((n) => n.className === 'path-field')[1]
    .children.find((c) => c.textContent === 'Valitse…');
  await again.handlers.click();
  assert.equal(vm.runInContext('state.package.beds.intro_path', context), '');

  /* Palvelin sanoo ettei valitsinta ole: ei polkua, ei kaatumista. */
  pickReply = { path: '', unavailable: true };
  await again.handlers.click();
  assert.equal(vm.runInContext('state.package.beds.intro_path', context), '');

  /* Tekstitys löytyy: varoitus katoaa. */
  vm.runInContext('state.generated_available = true; renderPackage();', context);
  const after = all().filter((n) => n.tagName === 'P').map((n) => n.textContent);
  assert.ok(!after.some((t) => t.includes('AUTORAFFKAT_TEKSTITYS')),
            'varoitus jäi näkyviin vaikka Tekstitys löytyy');
  /* Tilavastaus kesken istunnon: Tekstitys asennetaan, varoitus väistyy ilman
     sivun latausta (Devin-arvio 2026-11-18). */
  vm.runInContext('state.generated_available = false; renderPackage();', context);
  assert.ok(all().filter((n) => n.tagName === 'P')
    .some((n) => n.textContent.includes('AUTORAFFKAT_TEKSTITYS')));
  vm.runInContext('noteGeneratedAvailability({ generated_available: true });', context);
  assert.ok(!all().filter((n) => n.tagName === 'P')
    .some((n) => n.textContent.includes('AUTORAFFKAT_TEKSTITYS')),
    'varoitus jäi näkyviin kun tilavastaus kertoi Tekstityksen löytyvän');
  vm.runInContext('noteGeneratedAvailability({ progress: {} });', context);
  assert.equal(vm.runInContext('state.generated_available', context), true,
    'tilavastaus ilman kenttää ei saa nollata saatavuutta');
  console.log('package panel: native file pickers and generated-text notice');
})().catch((err) => { console.error(err); process.exit(1); });
