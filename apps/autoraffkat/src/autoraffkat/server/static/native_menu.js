'use strict';

/* macOS-valikkorivin sisältö ja sen ajo. Puhtaat funktiot omassa tiedostossaan, jotta
   testi lataa ne sellaisenaan (kuten sync_timeline.js). Käyttää vain argumenttina
   annettua `env`iä; app.js antaa sen. Natiivi valikko ei omista mitään: jokainen kohta
   on työkalurivin nappi tai sen valinta, ja valittuna se painaa samaa nappia
   (`runNativeChoice`), joten nappi, näppäin ja valikko kutsuvat yhtä käsittelijää. */

/* Valikot ja niiden kohdat. `cmd` on komento (nappi tai erikoiskomento, ks. app.js
   `nativeUsable`), `label` käännösavain, `keys` pikanäppäinrivin id (`SHORTCUTS`), josta
   näppäinvihje luetaan. `native` merkitsee kohdan jonka pywebviewin oma natiivikohta
   korvaa (leikepöytä toimii tekstikentissä vain natiivina). `os` merkitsee kohdan jonka
   AppKit ajaa itse vastaanottajaketjussa oikealla keyEquivalentilla (ikkunan pienennys
   ja sulkeminen) — sivulle ei lähetetä komentoa. `languages` on kielialivalikko, jonka
   kohdat `env.languages()` antaa (kuten `history`). */
const NATIVE_MENUS = [
  { id: 'file', label: 'menu.file', items: [
    { cmd: 'open-media', label: 'app.openMedia', keys: 'openMedia' },
    { cmd: 'open', label: 'app.open', keys: 'open' },
    { cmd: 'reload', label: 'app.reload', keys: 'reload' },
    { cmd: 'relink', label: 'app.relink' },
    { sep: true },
    { cmd: 'render', label: 'app.render', keys: 'render' },
    { cmd: 'render-stop', label: 'menu.renderStop', keys: 'renderStop' },
    { sep: true },
    { cmd: 'export', label: 'app.export', keys: 'export' },
    { submenu: 'menu.exportTo', items: [
      { cmd: 'export-dest', arg: 'fcp', label: 'export.dest.fcp', radio: true },
      { cmd: 'export-dest', arg: 'resolve', label: 'export.dest.resolve', radio: true },
    ] },
    { sep: true },
    { cmd: 'trailer', label: 'menu.trailer', keys: 'trailer' },
  ] },
  { id: 'edit', label: 'menu.edit', items: [
    { cmd: 'history-undo', label: 'history.undo', keys: 'undo' },
    { cmd: 'history-redo', label: 'history.redo', keys: 'redo' },
    { history: true, submenu: 'menu.history' },
    { sep: true },
    { cmd: 'edit.cut', label: 'menu.cut', native: true },
    { cmd: 'edit.copy', label: 'menu.copy', native: true },
    { cmd: 'edit.paste', label: 'menu.paste', native: true },
    { cmd: 'edit.select_all', label: 'menu.selectAll', native: true },
    { sep: true },
    { cmd: 'mark-in', label: 'range.markIn' },
    { cmd: 'mark-out', label: 'range.markOut' },
    { cmd: 'range-clear', label: 'range.clear' },
  ] },
  { id: 'audio', label: 'menu.audio', items: [
    { cmd: 'mix', label: 'audio.run', keys: 'mix' },
  ] },
  { id: 'view', label: 'menu.view', items: [
    { languages: 'menu.language' },
  ] },
  { id: 'window', label: 'menu.window', items: [
    { cmd: 'window.minimize', label: 'menu.minimize', os: true },
    { cmd: 'window.close', label: 'menu.closeWindow', os: true },
  ] },
  { id: 'help', label: 'menu.help', items: [
    { cmd: 'shortcuts', label: 'keys.button', keys: 'help' },
  ] },
];

/* Trailer-sivun valikot: Pala-valikko näyttää samat näppäimet joilla sivu toimii
   (↑↓ valitsee, ←→ kehystää, M yhdistää edelliseen). Komennot ovat trailer.js:n
   toimintoja; sivun `env` päättää käytettävyyden (esim. ensimmäistä palaa ei voi
   yhdistää edelliseen). */
const TRAILER_MENUS = [
  { id: 'file', label: 'menu.file', items: [
    { cmd: 'trailer-back', label: 'trailer.back' },
    { cmd: 'trailer-export', label: 'trailer.export' },
  ] },
  { id: 'edit', label: 'menu.edit', items: [
    { cmd: 'edit.cut', label: 'menu.cut', native: true },
    { cmd: 'edit.copy', label: 'menu.copy', native: true },
    { cmd: 'edit.paste', label: 'menu.paste', native: true },
    { cmd: 'edit.select_all', label: 'menu.selectAll', native: true },
  ] },
  { id: 'clip', label: 'menu.clip', items: [
    { cmd: 'clip-prev', label: 'trailer.prev', keys: 'clipPrev' },
    { cmd: 'clip-next', label: 'trailer.next', keys: 'clipNext' },
    { sep: true },
    { cmd: 'clip-left', label: 'trailer.nudgeLeft', keys: 'clipLeft' },
    { cmd: 'clip-right', label: 'trailer.nudgeRight', keys: 'clipRight' },
    { sep: true },
    { cmd: 'clip-split', label: 'trailer.split' },
    { cmd: 'clip-merge-prev', label: 'trailer.merge', keys: 'clipMerge' },
  ] },
  { id: 'window', label: 'menu.window', items: [
    { cmd: 'window.minimize', label: 'menu.minimize', os: true },
    { cmd: 'window.close', label: 'menu.closeWindow', os: true },
  ] },
];

/* Komennot jotka toimivat vaikka pikanäppäinikkuna (modaali) on auki: vain sen oma
   avaus ja sulku. Muu jätetään koskematta, jotta valikko ei muokkaa projektia ikkunan
   takaa. */
const NATIVE_WHILE_SHEET = new Set(['shortcuts']);

/* Valikon speksi: `{id, label, items}`-lista, jonka `native_menu.py` piirtää. `env`:
   `T(key)`, `keysText(rowId)`, `usable(cmd, arg)`, `checked(cmd, arg)`,
   `history()` (lista `{id, label, current}`), `sheetOpen()`. */
function nativeMenuSpec(env, menus = NATIVE_MENUS) {
  const sheet = env.sheetOpen();
  const build = (entries) => {
    const out = [];
    entries.forEach((entry) => {
      if (entry.sep) {
        out.push({ kind: 'separator' });
      } else if (entry.history) {
        const items = env.history().map((node) => ({
          kind: 'item', id: 'history-goto', arg: String(node.id), label: node.label,
          keys: '', enabled: !sheet, checked: !!node.current,
        }));
        if (items.length) out.push({ kind: 'submenu', label: env.T(entry.submenu), items });
      } else if (entry.languages) {
        const items = env.languages().map((lang) => ({
          kind: 'item', id: 'lang', arg: lang.id, label: lang.label, keys: '',
          enabled: !sheet && env.usable('lang', lang.id), checked: !!lang.current,
        }));
        if (items.length) out.push({ kind: 'submenu', label: env.T(entry.languages), items });
      } else if (entry.submenu) {
        out.push({ kind: 'submenu', label: env.T(entry.submenu), items: build(entry.items) });
      } else {
        const item = {
          kind: 'item', id: entry.cmd, label: env.T(entry.label),
          keys: entry.keys ? env.keysText(entry.keys) : '',
          enabled: entry.os ? true
            : !entry.native && env.usable(entry.cmd, entry.arg)
            && (!sheet || NATIVE_WHILE_SHEET.has(entry.cmd)),
        };
        if (entry.arg !== undefined) item.arg = entry.arg;
        if (entry.radio) item.checked = !!env.checked(entry.cmd, entry.arg);
        out.push(item);
      }
    });
    return out;
  };
  return menus.map((menu) => ({ id: menu.id, label: env.T(menu.label), items: build(menu.items) }));
}

/* Valittu natiivi kohta ajetaan kuten napin painallus. Palauttaa true kun komento
   ajettiin. Pikanäppäinikkunan ollessa auki muu kuin sen oma komento hylätään. */
function runNativeChoice(choice, env) {
  if (!choice || typeof choice.id !== 'string') return false;
  if (env.sheetOpen() && !NATIVE_WHILE_SHEET.has(choice.id)) return false;
  if (!env.usable(choice.id, choice.arg)) return false;
  env.run(choice.id, choice.arg === undefined ? null : choice.arg);
  return true;
}

/* Pitää natiivin valikon ajan tasalla: `push()` lähettää speksin kun se muuttui,
   `push(true)` (kun ikkuna saa kohdistuksen) heti ja aina. Vain kohdistuksen saanut
   ikkuna lähettää, koska valikkorivi kuuluu etumaiselle ikkunalle. Ei tee mitään ilman
   kääreen `set_native_menu`a, joten selainvälilehti ei muutu. */
function createNativeMenuSync({ getSpec, getApi, hasFocus, onActive }) {
  let last = '';
  return {
    push(force = false) {
      const api = getApi();
      if (!api || typeof api.set_native_menu !== 'function' || !hasFocus()) return false;
      const spec = getSpec();
      const text = JSON.stringify(spec);
      if (!force && text === last) return false;
      last = text;
      Promise.resolve(api.set_native_menu(spec))
        .then((ok) => { if (ok && onActive) onActive(); })
        .catch(() => { last = ''; });
      return true;
    },
  };
}
