'use strict';

/* Mediasynkan arviointi seuraa /api/state-vastausta. HTTP- tai JSON-virhe
   ilman media_sync-tilaa on epäonnistunut kysely: seurannan pitää yrittää
   uudelleen eikä kaatua job.current-luvun TypeErroriin (Devin-arvio
   2026-11-18). Valeselain vastaa ensin kahdella virheellä ja sitten valmiilla
   työllä; tulos pitää liittyä eikä virheilmoitusta saa näkyä.
 *
 * Käyttö: node ui_media_poll.js <app.js:n polku>
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
    children: [], dataset: {}, style: {}, className: '', innerHTML: '', textContent: '',
    append() {}, appendChild(c) { return c; }, handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; }, setAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 20,
                                    width: 100, height: 20, x: 0, y: 0 }),
    clientWidth: 1200, width: 1200, height: 120, value: 'auto', disabled: false,
  };
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

const stateReplies = [
  { ok: false, body: { detail: 'busy' } },
  { ok: true, body: { detail: 'no media_sync here' } },
  { ok: true, body: { media_sync: { running: false, ready: true, error: '',
                                    current: '', fraction: 1, result: { tracks: [] } } } },
];
let stateCalls = 0;
const context = {
  document: documentStub,
  window: { addEventListener() {}, devicePixelRatio: 2 },
  getComputedStyle: () => ({ getPropertyValue: () => '#123456' }),
  fetch: async (url) => {
    if (url === '/api/media/estimate') {
      return { ok: true, json: async () => ({ accepted: true }) };
    }
    const reply = stateReplies[Math.min(stateCalls++, stateReplies.length - 1)];
    return { ok: reply.ok, json: async () => reply.body };
  },
  setTimeout: (fn) => { fn(); return 0; }, clearTimeout() {},
  setInterval: () => 0, clearInterval() {},
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
vm.runInContext(`
  mediaImport = { paths: ['/a.mp4', '/b.wav'], reference: '/a.mp4', result: null };
  renderMediaSync = () => {};
`, context);

(async () => {
  await vm.runInContext('estimateMediaSync()', context);
  assert.equal(stateCalls, 3, 'seuranta ei yrittänyt uudelleen virhevastausten jälkeen');
  assert.deepEqual(
    JSON.parse(vm.runInContext('JSON.stringify(mediaImport.result)', context)),
    { tracks: [] }, 'valmis tulos ei liittynyt virhevastausten jälkeen');
  /* Viisi peräkkäistä virhettä päättää seurannan käännetyllä viestillä. */
  stateCalls = 0;
  stateReplies.splice(0, stateReplies.length, { ok: false, body: { detail: 'down' } });
  await vm.runInContext('estimateMediaSync()', context);
  const shown = registry.get('media-sync-progress').textContent;
  assert.ok(shown.includes(vm.runInContext("T('sync.pollFailed')", context)),
            'seurannan päättävä virhe ei käytä käännettyä viestiä: ' + shown);
  assert.ok(!shown.includes('State poll failed'), 'käännös puuttuu suomesta');
  /* Vertailukameran vaihto nollaa kentät, joten käsin muokkauksen merkki
     ei saa jäädä (Devin-arvio 2026-11-18). */
  vm.runInContext("mediaImport.edited = { '/b.wav': true }", context);
  registry.get('media-sync-reference').handlers.change({ target: { value: '/c.mp4' } });
  assert.deepEqual(
    JSON.parse(vm.runInContext('JSON.stringify(mediaImport.edited)', context)), {},
    'vertailukameran vaihto jätti käsin muokkauksen merkin');
  console.log('media poll: error responses are retried');
})().catch((err) => { console.error(err); process.exit(1); });
