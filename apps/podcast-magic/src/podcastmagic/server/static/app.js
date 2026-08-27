'use strict';

/* Kuori. Se tuntee istunnon, moduulit ja työjonon — ei sitä mitä moduulit
   tekevät. Moduuli rekisteröi itsensä ``PM.registerModule``illa ja saa
   paneelin sekä kahvan istuntoon ja työn käynnistykseen.

   Istunto on kuoressa eikä moduulissa, koska se on sama tiedosto molemmille:
   litterointi kirjoittaa sen, vaimennus lukee sen, ja välilehden vaihtaminen
   kesken työn ei saa hukata valintaa. */

const PM = {
  modules: new Map(),
  order: [],
  active: '',
  state: null,
  session: '',
  lastJobId: 0,
  polling: null,

  registerModule(spec) {
    this.modules.set(spec.key, spec);
  },

  t(key, vars) { return I18N.t(key, vars); },

  // ---- pikku apurit ------------------------------------------------------

  el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (name === 'class') node.className = value;
      else if (name === 'text') node.textContent = value;
      else if (name === 'html') node.innerHTML = value;
      else if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
      else if (value === true) node.setAttribute(name, '');
      else if (value !== false && value != null) node.setAttribute(name, value);
    }
    for (const child of children || []) {
      if (child) node.appendChild(child);
    }
    return node;
  },

  async api(path, body) {
    const options = body === undefined
      ? {}
      : { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) };
    const response = await fetch(path, options);
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      const message = (data && (data.detail || data.error)) || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return data;
  },

  banner(message, isError) {
    const node = document.getElementById('banner');
    node.textContent = message || '';
    node.classList.toggle('hidden', !message);
    node.classList.toggle('error', !!isError);
  },

  // ---- istunto -----------------------------------------------------------

  setSession(path) {
    this.session = path || '';
    document.getElementById('session').value = this.session;
    document.getElementById('browser').classList.add('hidden');
    this.noteSession();
    const module = this.modules.get(this.active);
    if (module && module.onSession) module.onSession(this.session);
  },

  async noteSession() {
    const note = document.getElementById('session-note');
    if (!this.session) { note.textContent = ''; return; }
    try {
      const found = await this.api(`/api/exists?path=${encodeURIComponent(this.session)}`);
      note.textContent = found.file ? '' : this.t('app.notFound');
    } catch {
      note.textContent = '';
    }
  },

  async browse(dir) {
    const box = document.getElementById('browser');
    box.classList.remove('hidden');
    let listing;
    try {
      listing = await this.api(`/api/browse?dir=${encodeURIComponent(dir || '')}`);
    } catch (error) {
      this.banner(this.t('app.noServer', { error: error.message }), true);
      return;
    }
    const list = this.el('ul', {}, []);
    if (listing.parent) {
      list.appendChild(this.el('li', {}, [
        this.el('button', { class: 'dir', text: this.t('app.up'),
                            onclick: () => this.browse(listing.parent) }),
      ]));
    }
    for (const entry of listing.dirs) {
      list.appendChild(this.el('li', {}, [
        this.el('button', { class: 'dir', text: entry.name,
                            onclick: () => this.browse(entry.path) }),
      ]));
    }
    for (const entry of listing.files) {
      const when = new Date(entry.mtime * 1000);
      const button = this.el('button', {
        class: `file${entry.derived ? ' derived' : ''}`,
        onclick: () => this.setSession(entry.path),
      }, [
        this.el('span', { class: 'when', text: when.toLocaleDateString() }),
        this.el('span', { text: entry.name }),
      ]);
      list.appendChild(this.el('li', {}, [button]));
    }
    if (!listing.dirs.length && !listing.files.length) {
      list.appendChild(this.el('li', {}, [
        this.el('button', { class: 'muted', text: this.t('app.noSessions'), disabled: true }),
      ]));
    }
    box.replaceChildren(
      this.el('div', { class: 'here', text: listing.dir }),
      list,
    );
  },

  /* Natiivi valintaikkuna, kun ohjelma ajetaan omana sovelluksenaan.
     Selaimessa sitä ei ole — silloin jää oma selain, joka on siksi
     olemassa eikä varasijana. */
  async pick() {
    const bridge = window.pywebview && window.pywebview.api;
    if (bridge && bridge.open_session_dialog) {
      const chosen = await bridge.open_session_dialog();
      if (chosen) { this.setSession(chosen); return; }
      return;
    }
    const box = document.getElementById('browser');
    if (!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
    const here = this.session
      ? this.session.replace(/\/[^/]*$/, '')
      : (this.state && this.state.startDir) || '';
    this.browse(here);
  },

  // ---- työ ---------------------------------------------------------------

  async run(module, path, body, button) {
    if (!this.session) { this.banner(this.t('app.pickFirst'), true); return; }
    this.banner('');
    if (button) { button.classList.add('busy'); button.disabled = true; }
    try {
      const job = await this.api(path, { session: this.session, ...body });
      this.showJob(job);
      this.startPolling();
    } catch (error) {
      this.banner(error.message, true);
    } finally {
      if (button) { button.classList.remove('busy'); button.disabled = false; }
    }
  },

  startPolling() {
    if (this.polling) return;
    this.polling = setInterval(async () => {
      let job;
      try { job = await this.api('/api/job'); } catch { return; }
      this.showJob(job);
      if (!job || !job.running) { clearInterval(this.polling); this.polling = null; }
    }, 500);
  },

  showJob(job) {
    const panel = document.getElementById('job');
    if (!job || !job.id) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');

    const step = document.getElementById('job-step');
    const parts = [];
    if (job.stepsTotal) parts.push(`${job.stepsDone}/${job.stepsTotal}`);
    if (job.step) parts.push(job.step);
    if (job.elapsed > 60) parts.push(this.t('app.elapsed', { m: (job.elapsed / 60).toFixed(1) }));
    step.textContent = parts.join(' · ');

    /* Osuus koko työstä: valmiit vaiheet plus nykyisen vaiheen osuus.
       Pelkkä «2/4» seisoo paikallaan minuutteja, ja juuri silloin kysytään
       eteneekö mikään. */
    const fill = document.getElementById('job-fill');
    const total = job.stepsTotal || 0;
    let ratio = null;
    if (total > 0) {
      const inside = typeof job.fraction === 'number' ? job.fraction : 0;
      ratio = Math.min(1, (job.stepsDone + inside) / total);
    } else if (typeof job.fraction === 'number') {
      ratio = job.fraction;
    }
    const unknown = job.running && ratio === null;
    fill.classList.toggle('indeterminate', unknown);
    fill.style.width = unknown ? '' : `${Math.round((ratio || (job.running ? 0 : 1)) * 100)}%`;

    const log = document.getElementById('job-log');
    const text = (job.log || []).join('\n');
    if (log.textContent !== text) {
      const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
      log.textContent = text;
      if (atBottom) log.scrollTop = log.scrollHeight;
    }

    document.getElementById('cancel').classList.toggle('hidden', !job.running);
    this.showResult(job);

    if (job.id !== this.lastJobId && !job.running) {
      this.lastJobId = job.id;
      const module = this.modules.get(job.module);
      if (module && module.onFinished) module.onFinished(job);
    }
  },

  showResult(job) {
    const box = document.getElementById('job-result');
    if (job.running) { box.classList.add('hidden'); return; }

    if (job.cancelled) {
      box.classList.remove('hidden');
      box.replaceChildren(this.el('span', { class: 'muted', text: this.t('app.cancelled') }));
      return;
    }
    if (job.error) {
      box.classList.remove('hidden');
      box.replaceChildren(
        this.el('span', { class: 'said', style: 'color:var(--error)', text: this.t('app.failed') }),
        this.el('span', { text: job.error }),
      );
      return;
    }
    const written = job.result && job.result.written;
    if (!written) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    const field = this.el('input', { type: 'text', readonly: true, value: written,
                                     onclick: (event) => event.target.select() });
    box.replaceChildren(
      this.el('span', { class: 'said', text: this.t('app.done') }),
      field,
      this.el('button', { class: 'ghost', text: this.t('app.reveal'),
                          onclick: () => this.api('/api/reveal', { path: written }).catch(() => {}) }),
    );
  },

  // ---- kuoren piirto -----------------------------------------------------

  selectModule(key) {
    this.active = key;
    try { localStorage.setItem('pm.module', key); } catch { /* yksityinen ikkuna */ }
    document.querySelectorAll('#tabs button').forEach((button) => {
      button.classList.toggle('on', button.dataset.key === key);
    });
    const panels = document.getElementById('panels');
    panels.replaceChildren();
    const module = this.modules.get(key);
    if (!module) return;
    const root = this.el('section', { class: 'panel' }, []);
    panels.appendChild(root);
    module.render(root, this);
    I18N.apply(root);
  },

  renderTabs() {
    const tabs = document.getElementById('tabs');
    tabs.replaceChildren(...this.state.modules.map((spec) => this.el('button', {
      'data-key': spec.key,
      text: spec.title[I18N.lang] || spec.title.fi,
      title: spec.blurb[I18N.lang] || spec.blurb.fi,
      onclick: () => this.selectModule(spec.key),
    })));
  },

  renderLanguages() {
    const box = document.getElementById('language');
    box.replaceChildren(...['fi', 'en'].map((lang) => this.el('button', {
      class: lang === I18N.lang ? 'on' : '',
      text: lang.toUpperCase(),
      onclick: () => { I18N.set(lang); this.redraw(); },
    })));
  },

  redraw() {
    I18N.apply(document);
    this.renderLanguages();
    this.renderTabs();
    this.selectModule(this.active);
    this.noteSession();
  },

  async start() {
    I18N.set(I18N.detect());
    try {
      this.state = await this.api('/api/state');
    } catch (error) {
      this.banner(I18N.t('app.noServer', { error: error.message }), true);
      return;
    }
    document.getElementById('version').textContent = `v${this.state.version}`;
    if (!this.state.ffmpeg) this.banner(I18N.t('app.noFfmpeg'));

    let remembered = null;
    try { remembered = localStorage.getItem('pm.module'); } catch { /* yksityinen ikkuna */ }
    const keys = this.state.modules.map((m) => m.key);
    this.active = keys.includes(remembered) ? remembered : keys[0];

    document.getElementById('browse').addEventListener('click', () => this.pick());
    document.getElementById('session').addEventListener('change', (event) => {
      this.setSession(event.target.value.trim());
    });
    document.getElementById('cancel').addEventListener('click', () => {
      this.api('/api/job/cancel', {}).catch(() => {});
    });

    this.redraw();
    if (this.state.session) this.setSession(this.state.session);
    if (this.state.job) { this.showJob(this.state.job); if (this.state.job.running) this.startPolling(); }
  },
};
