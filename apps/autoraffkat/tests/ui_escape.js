'use strict';

/* Leikkauslistan puhujanimet menevät innerHTML:ään. Nimi on käyttäjän
   kirjoittama tai aineistosta tullut merkkijono, joten sen on päästävä
   ruudulle tekstinä — ei merkkaavana osana sivua. Tämä ajaa renderCuts():n
   valeselaimessa vihamielisellä nimellä ja vaatii että rivin merkkijono
   sisältää nimen pakotettuna eikä koskaan raakana.
 *
 * boot() leikataan latauksesta pois: tämä testi ajaa vain renderCuts()-funktion
 * eikä käynnistä verkkoliikennettä. Muu latausaikainen koodi (pikanäppäimet,
 * pudotuskuuntelijat) saa ajaa — valeselain kestää ne.
 *
 * Käyttö: node ui_escape.js <app.js:n polku>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('node:assert/strict');

const appPath = process.argv[2];
const src = fs.readFileSync(appPath, 'utf8');

function makeElement(tag) {
  return {
    tagName: (tag || 'div').toUpperCase(),
    children: [], dataset: {}, style: {}, _handlers: {},
    className: '', innerHTML: '', textContent: '',
    append(...cs) { this.children.push(...cs); },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, setAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 20,
                                    width: 100, height: 20, x: 0, y: 0 }),
    clientWidth: 1200, width: 1200, height: 120,
  };
}

const registry = new Map();
const tbody = makeElement('tbody');
const documentStub = {
  createElement: (tag) => makeElement(tag),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  getElementById(id) {
    if (!registry.has(id)) registry.set(id, makeElement('div'));
    return registry.get(id);
  },
  querySelector: (sel) => (sel === '#cut-table tbody' ? tbody : makeElement('div')),
  querySelectorAll: () => [],
  addEventListener() {},
};

/* Tägi- ja attribuuttirajat rikkova nimi: jos tämä pääsee merkkijonoon
   raakana, selain rakentaisi siitä uusia solmuja ja attribuutteja. */
const HOSTILE = '<img src=x onerror=alert(1)>" data-x="';

const context = {
  document: documentStub,
  window: { addEventListener() {}, devicePixelRatio: 2 },
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  fetch: async () => { throw new Error('tämä testi ei tee verkkopyyntöjä'); },
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  AbortController: function () { this.abort = () => {}; this.signal = null; },
  console, JSON, Math, Object, Number, String, Array, Boolean, Date,
  encodeURIComponent,
};
context.globalThis = context;
vm.createContext(context);

vm.runInContext(
  fs.readFileSync(path.join(path.dirname(appPath), 'i18n.js'), 'utf8'),
  context, { filename: 'i18n.js' });
vm.runInContext(src.replace(/\bboot\(\);\s*$/, ''), context, { filename: 'app.js' });

vm.runInContext(`
  state = { tracks: [], globals: { reactions: true }, audio: {} };
  latest = {
    ok: true, wide_label: 'WIDE', ms: 1, edits: [], counts: {},
    program: { start: 0, duration: 10 },
    segments: [{ label: ${JSON.stringify(HOSTILE)}, angle: 0,
                 start: 0, end: 1, duration: 1 }],
    reactions: [{ speaker: ${JSON.stringify(HOSTILE)}, start: 2, end: 3 }],
    preview: { speakers: [], shots: [], groups: [], silence: [] },
  };
`, context);

vm.runInContext('renderCuts()', context);

const rows = tbody.children.map((r) => r.innerHTML).join('\n');
assert.ok(rows.length > 0, 'renderCuts ei piirtänyt yhtään riviä');
assert.ok(!rows.includes(HOSTILE),
          'puhujan nimi pääsi leikkauslistan innerHTML:ään käsittämättömänä');
assert.ok(!rows.includes('<img'),
          'vihamielinen nimi selviytyisi selaimessa img-solmuksi');
assert.ok(rows.includes('&lt;img'),
          'nimi piirtyy pakotettuna tekstinä');
console.log('renderCuts: hostile speaker label stays inert text');
