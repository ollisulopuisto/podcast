'use strict';

/* Käyttöliittymän savutesti.
 *
 * `node --check` tarkistaa vain syntaksin, eikä siis huomaa viittausta
 * muuttujaan tai kenttään jota ei ole. Piirto keskeytyy siihen hiljaa, ja
 * ruudulle jää tyhjä paneeli — ei virhettä, ei mitään.
 *
 * Tämä lataa i18n.js:n, app.js:n ja jokaisen mod_*.js:n valeselaimeen,
 * ajaa kuoren oikealla palvelimen tuottamalla tilalla ja piirtää jokaisen
 * moduulin molemmilla kielillä. Napit myös painetaan: piirto yksin kattaa
 * puolet koodista, käsittelijät ovat se toinen puoli.
 *
 * Käyttö: node ui_smoke.js <static-hakemisto> <vastaukset.json>
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [staticDir, answersPath] = process.argv.slice(2);
const answers = JSON.parse(fs.readFileSync(answersPath, 'utf8'));

const byId = new Map();
const created = [];

function makeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [],
    dataset: {},
    attributes: {},
    style: {},
    _handlers: {},
    _text: '',
    _id: '',
    value: '',
    checked: false,
    disabled: false,
    innerHTML: '',
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    get id() { return this._id; },
    set id(v) { this._id = String(v); byId.set(this._id, this); },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get className() { return [...this.classList._set].join(' '); },
    set className(v) {
      this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean));
    },
    classList: {
      _set: new Set(),
      add(...n) { n.forEach((x) => this._set.add(x)); },
      remove(...n) { n.forEach((x) => this._set.delete(x)); },
      toggle(n, on) {
        const want = on === undefined ? !this._set.has(n) : !!on;
        if (want) this._set.add(n); else this._set.delete(n);
      },
      contains(n) { return this._set.has(n); },
    },
    appendChild(node) { this.children.push(node); node.parentNode = this; return node; },
    append(...nodes) { nodes.forEach((n) => this.appendChild(n)); },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => n && this.appendChild(n)); },
    removeChild(node) { this.children = this.children.filter((c) => c !== node); },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === 'id') this.id = value;
      if (name === 'value') this.value = String(value);
      if (name === 'checked') this.checked = true;
      if (name === 'disabled') this.disabled = true;
      if (name.startsWith('data-')) this.dataset[name.slice(5)] = String(value);
    },
    getAttribute(name) { return this.attributes[name] ?? null; },
    addEventListener(name, fn) { (this._handlers[name] ||= []).push(fn); },
    dispatchEvent(event) {
      const name = event && event.type ? event.type : String(event);
      (this._handlers[name] || []).forEach((fn) => fn({ type: name, target: this }));
      return true;
    },
    querySelector(selector) { return descend(this).find((n) => matches(n, selector)) || null; },
    querySelectorAll(selector) { return descend(this).filter((n) => matches(n, selector)); },
    select() {},
    focus() {},
  };
  created.push(el);
  return el;
}

function descend(node) {
  const out = [];
  for (const child of node.children) { out.push(child); out.push(...descend(child)); }
  return out;
}

function matches(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  const [tag, rest] = selector.split(' ');
  if (rest) return matches(node, rest);
  return node.tagName === tag.toUpperCase();
}

/* index.html:n tunnukselliset elementit. Ne luetaan oikeasta tiedostosta,
   jotta poistettu id kaataa testin sen sijaan että jäisi hiljaa toimimatta.

   Myös luokat luetaan: `class="log hidden"` on alkutila siinä missä mikä
   tahansa muukin, ja ilman sitä valeselain aloittaa auki olevasta lokista
   ja tyhjentämättömästä bannerista — eli tilasta jota kukaan ei näe. */
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const root = makeElement('body');
for (const tag of html.matchAll(/<[a-zA-Z][^>]*>/g)) {
  const id = /\sid="([^"]+)"/.exec(tag[0]);
  if (!id) continue;
  const el = makeElement('div');
  el.id = id[1];
  const cls = /\sclass="([^"]+)"/.exec(tag[0]);
  if (cls) el.className = cls[1];
  root.appendChild(el);
}

const document = {
  documentElement: { lang: 'fi' },
  body: root,
  createElement: makeElement,
  getElementById(id) {
    if (!byId.has(id)) throw new Error(`index.html:stä puuttuu id="${id}"`);
    return byId.get(id);
  },
  querySelector(s) { return root.querySelector(s); },
  querySelectorAll(s) { return root.querySelectorAll(s); },
};

const calls = [];
async function fetchStub(url, options) {
  calls.push(url);
  const key = String(url).split('?')[0];
  if (!(key in answers)) throw new Error(`odottamaton kutsu: ${key}`);
  return { ok: true, status: 200, json: async () => answers[key] };
}

const sandbox = {
  document,
  window: {},
  navigator: { language: 'fi-FI' },
  localStorage: { getItem: () => null, setItem: () => {}, },
  fetch: fetchStub,
  setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms || 0, 5)),
  clearTimeout: (id) => clearTimeout(id),
  setInterval: () => 0,
  clearInterval: () => {},
  Event: class { constructor(type) { this.type = type; } },
  Date,
  Math,
  JSON,
  Number,
  String,
  Object,
  Boolean,
  Array,
  Error,
  console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const file of ['i18n.js', 'app.js', 'mod_transcribe.js', 'mod_silence.js',
                    'mod_script.js', 'mod_merge.js']) {
  vm.runInContext(fs.readFileSync(path.join(staticDir, file), 'utf8'), sandbox, { filename: file });
}

/* Piirto on asynkroninen: paneeli hakee tietonsa palvelimelta. Muutama
   tikki riittää, koska hakuja on ketjussa korkeintaan kaksi. */
async function settle() {
  for (let i = 0; i < 8; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

(async () => {
  await vm.runInContext('PM.start()', sandbox);
  await settle();

  /* Moduulilista tulee palvelimelta, ei tästä: uusi moduuli jättää itsensä
     testamatta huomaamatta vain jos tämä lista on käsin kopioitu. */
  const keys = vm.runInContext(
    'Array.from(PM.modules.keys()).join(",")', sandbox).split(',');

  for (const lang of ['fi', 'en']) {
    vm.runInContext(`I18N.set('${lang}')`, sandbox);
    for (const key of keys) {
      vm.runInContext(`PM.session = ${JSON.stringify('/tmp/jakso.nhsx')}; PM.selectModule('${key}')`, sandbox);
      await settle();
      /* Litteroinnin siirto kysyy lähdettä, jota ei ole ennen kuin se
         kirjoitetaan: kenttä täytetään ja muutos lähetetään, jotta myös
         ennakko piirtyy. */
      if (key === 'merge') {
        const source = byId.get('mg-source');
        source.value = '/tmp/lahde.nhsx';
        const panel = byId.get('panels').children[0];
        panel.dispatchEvent({ type: 'input', target: source });
        await settle();
      }
      /* Tyhjä paneeli on juuri se vika jota tämä etsii: piirto keskeytyi
         eikä siitä sanottu mitään. Siksi tyhjyys on virhe, ei tulos. */
      const panel = byId.get('panels').children[0];
      if (!panel || descend(panel).length < 6) {
        throw new Error(`moduulin ${key} paneeli jäi tyhjäksi kielellä ${lang}`);
      }
      if (!descend(panel).some((n) => n.tagName === 'BUTTON')) {
        throw new Error(`moduulissa ${key} ei ole yhtään nappia`);
      }
    }
  }

  /* Ajon aikana ruudulla on prosentti ja arvio jäljellä olevasta. «1/3» yksin
     seisoo paikallaan minuutteja, ja juuri silloin kysytään eteneekö mikään.
     Loki on kiinni kunnes se avataan: se on ajon lokia, ei ajon tilaa. */
  const running = { id: 1, module: 'transcribe', running: true, stepsDone: 1, stepsTotal: 3,
                    fraction: 0.5, step: 'olli.wav', log: ['a', 'b'], result: {},
                    elapsed: 90, stepElapsed: 30 };
  vm.runInContext(`PM.showJob(${JSON.stringify(running)})`, sandbox);
  /* Kaksi arviota erikseen: tämä tiedosto ja koko työ. Yksi luku ei vastaa
     kumpaankaan kysymykseen — «15 %» kertoo ajosta eikä siitä tiedostosta
     jota juuri odotetaan. */
  const perFile = byId.get('job-file').textContent;
  const overall = byId.get('job-all').textContent;
  for (const [what, said] of [['tiedoston', perFile], ['koko työn', overall]]) {
    if (!said.includes('%')) throw new Error(`${what} osuus puuttuu: «${said}»`);
    if (!/\d/.test(said.slice(said.lastIndexOf('·')))) {
      throw new Error(`${what} arvio jäljellä olevasta puuttuu: «${said}»`);
    }
  }
  if (perFile === overall) throw new Error(`arviot ovat sama luku: «${perFile}»`);
  if (!byId.get('job-log').classList.contains('hidden')) {
    throw new Error('loki on auki ilman että sitä pyydettiin');
  }
  byId.get('job-log-toggle').dispatchEvent({ type: 'click' });
  if (byId.get('job-log').classList.contains('hidden')) {
    throw new Error('loki ei avaudu napista');
  }

  // Kaikki luodut napit painetaan. Käsittelijä joka viittaa olemattomaan
  // kenttään kaatuu tässä eikä käyttäjän ruudulla.
  // Tilannekuva ennen silmukkaa: painallus luo lisää elementtejä, ja
  // elävän listan läpi käyminen ei pääty koskaan.
  for (const el of created.slice()) {
    for (const fn of el._handlers.click || []) {
      await fn({ type: 'click', target: el, preventDefault() {} });
    }
  }
  await settle();

  // Työn tila piirretään kaikissa lopputiloissa.
  const shapes = [
    { id: 1, module: 'transcribe', running: true, stepsDone: 1, stepsTotal: 3,
      fraction: 0.5, step: 'olli.wav', log: ['a', 'b'], result: {}, elapsed: 90 },
    { id: 2, module: 'silence', running: false, ok: true, log: ['valmis'],
      result: { written: '/tmp/jakso vaimennettu.nhsx' }, elapsed: 12 },
    { id: 3, module: 'silence', running: false, error: 'meni pieleen', log: [], result: {}, elapsed: 1 },
    { id: 4, module: 'silence', running: false, cancelled: true, log: [], result: {}, elapsed: 1 },
    { id: 5, module: 'transcribe', running: true, stepsTotal: 0, fraction: null,
      log: [], result: {}, elapsed: 1 },
  ];
  for (const job of shapes) {
    vm.runInContext(`PM.showJob(${JSON.stringify(job)})`, sandbox);
  }

  if (!calls.includes('/api/state')) throw new Error('kuori ei kysynyt tilaa');
  if (byId.get('tabs').children.length !== keys.length) {
    throw new Error('välilehtiä ei piirretty');
  }
  for (const needed of ['/api/transcribe/info', '/api/silence/info',
                        '/api/transcribe/plan', '/api/silence/preview',
                        '/api/script/preview', '/api/merge/info',
                        '/api/merge/preview']) {
    if (!calls.includes(needed)) throw new Error(`moduuli ei kutsunut ${needed}`);
  }
  console.log(`OK — ${created.length} elementtiä, ${calls.length} kutsua`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
