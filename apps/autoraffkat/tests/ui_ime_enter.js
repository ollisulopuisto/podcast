'use strict';

/* IME-yhdistelmäsyötön (CJK) Enter on yhdistelmän vahvistusnäppäin, ei
   lähetys: kansikuvien addPerson-kentän keydown-kuuntelija kutsui add():ia
   tarkistamatta event.isComposing / keyCode 229 -tilaa, joten yhdistelmän
   vahvistus lisäsi henkilön kenttään kesken syötön. Tämä ajaa
   shotCoverage():n valeselaimessa ja painaa Enteriä molemmissa tiloissa.
 *
 * boot() leikataan latauksesta pois kuten ui_escape.js:ssä; schedule ja
   renderTracks korvataan tyhjillä, koska add() kutsuu niitä onnistuessaan.
 *
 * Käyttö: node ui_ime_enter.js <app.js:n polku>
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
    className: '', innerHTML: '', textContent: '', value: '', checked: false,
    append(...cs) { this.children.push(...cs); },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(name, fn) { this._handlers[name] = fn; },
    setAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
  };
}

const documentStub = {
  createElement: (tag) => makeElement(tag),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  getElementById: () => makeElement('div'),
  querySelector: () => makeElement('div'),
  querySelectorAll: () => [],
  addEventListener() {},
};

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

/* add() tallentaa ja piirtää uudestaan; tässä mitataan vain lisäystä. */
vm.runInContext('schedule = () => {}; renderTracks = () => {};', context);

const media = { key: 't1', name: 'Raita 1', config: {} };
const box = vm.runInContext('shotCoverage', context)(media, []);

const walk = (el) => [el, ...(el.children || []).flatMap(walk)];
const addPerson = walk(box).find((el) => el.className === 'coverage-add-person');
assert.ok(addPerson, 'addPerson-kenttää ei löytynyt shotCoverage():n puusta');
assert.ok(addPerson._handlers.keydown, 'addPerson-kentällä ei ole keydown-kuuntelijaa');

addPerson.value = 'Uusi henkilö';
addPerson._handlers.keydown({ key: 'Enter', isComposing: true });
assert.ok(media.config.covers.length === 0,
          'IME-yhdistelmän Enter lisäsi henkilön (isComposing)');
addPerson._handlers.keydown({ key: 'Enter', keyCode: 229 });
assert.ok(media.config.covers.length === 0,
          'IME-yhdistelmän Enter lisäsi henkilön (keyCode 229)');
addPerson._handlers.keydown({ key: 'Enter' });
assert.ok(media.config.covers.length === 1 && media.config.covers[0] === 'Uusi henkilö',
          'tavallinen Enter ei enää lisännyt henkilöä');

console.log('shotCoverage: IME-yhdistelmän Enter jää toiminnoksi vain selaimelle');
