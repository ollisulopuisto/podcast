'use strict';

/* Natiivivalikon puhtaiden funktioiden mittari: lataa native_menu.js:n sellaisenaan
   ja kertoo JSON-muodossa mitä funktiot palauttivat. Väitteet ovat
   test_native_menu_js.py:ssä. Käyttö: node ui_native_menu.js <static-hakemisto> */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

(async () => {
const ctx = vm.createContext({ Promise, JSON, String, Set });
vm.runInContext(
  fs.readFileSync(path.join(process.argv[2], 'native_menu.js'), 'utf8')
    + '\nthis.api = { nativeMenuSpec, runNativeChoice, createNativeMenuSync, NATIVE_MENUS, TRAILER_MENUS };',
  ctx,
);
const { nativeMenuSpec, runNativeChoice, createNativeMenuSync, NATIVE_MENUS, TRAILER_MENUS } = ctx.api;

function env(over = {}) {
  const runs = [];
  return Object.assign({
    T: (k) => `T:${k}`,
    keysText: (id) => `K:${id}`,
    usable: () => true,
    checked: (cmd, arg) => arg === 'fcp',
    history: () => [{ id: '1', label: 'a', current: false }, { id: '2', label: 'b', current: true }],
    languages: () => [{ id: 'fi', label: 'L:fi', current: true }, { id: 'en', label: 'L:en', current: false }],
    sheetOpen: () => false,
    run: (cmd, arg) => runs.push([cmd, arg]),
    runs,
  }, over);
}

const out = {};
const spec = nativeMenuSpec(env());
out.menuIds = spec.map((m) => m.id);
const flat = (items) => items.flatMap((i) => (i.items ? flat(i.items) : [i]));
const trailerSpec = nativeMenuSpec(env(), TRAILER_MENUS);
out.trailerMenuIds = trailerSpec.map((m) => m.id);
const trailerAll = trailerSpec.flatMap((m) => flat(m.items));
out.trailerClipItems = trailerAll.filter((i) => i.id && i.id.startsWith('clip-')).map((i) => [i.id, i.keys, i.enabled]);
const all = spec.flatMap((m) => flat(m.items));
out.mixKeys = all.find((i) => i.id === 'mix').keys;
out.exportRadios = all.filter((i) => i.id === 'export-dest').map((i) => [i.arg, i.checked]);
out.historyItems = all.filter((i) => i.id === 'history-goto').map((i) => [i.arg, i.checked]);
out.clipboardEnabled = all.filter((i) => /^edit\./.test(i.id)).map((i) => i.enabled);

const sheetSpec = nativeMenuSpec(env({ sheetOpen: () => true }));
const sheetAll = sheetSpec.flatMap((m) => flat(m.items));
out.sheetEnabled = [...new Set(sheetAll.filter((i) => i.enabled).map((i) => i.id))];
out.disabledWhenUnusable = flat(nativeMenuSpec(env({ usable: () => false }))[0].items)
  .filter((i) => i.kind === 'item').every((i) => i.enabled === false);

const e1 = env();
out.runOk = runNativeChoice({ id: 'render' }, e1);
out.runArgs = runNativeChoice({ id: 'export-dest', arg: 'resolve' }, e1);
out.runCalls = e1.runs;
const e2 = env({ sheetOpen: () => true });
out.sheetBlocksRender = runNativeChoice({ id: 'render' }, e2);
out.sheetAllowsShortcuts = runNativeChoice({ id: 'shortcuts' }, e2);
out.sheetRuns = e2.runs;
out.unusableRefused = runNativeChoice({ id: 'render' }, env({ usable: () => false }));
out.garbageRefused = [runNativeChoice(null, env()), runNativeChoice({ id: 5 }, env())];

let sent = 0;
let focus = true;
let n = 0;
const sync = createNativeMenuSync({
  getSpec: () => ({ n: Math.min(n, 1) }),
  getApi: () => ({ set_native_menu: () => { sent += 1; return Promise.resolve(true); } }),
  hasFocus: () => focus,
});
out.sync = [sync.push(), sync.push(), sync.push(true)];
n = 5; out.sync.push(sync.push());
focus = false; out.sync.push(sync.push(true));
out.sent = sent;
out.noApi = createNativeMenuSync({ getSpec: () => ({}), getApi: () => null, hasFocus: () => true }).push();
const topIds = (menuId) => {
  const menu = spec.find((m) => m.id === menuId);
  if (!menu) return [];
  return menu.items.map((i) => (i.kind === 'submenu' ? `SUB:${i.label}` : i.id))
    .filter(Boolean);
};
out.fileTop = topIds('file');
out.audioTop = topIds('audio');
out.viewTop = topIds('view');
out.helpTop = topIds('help');
out.windowTop = topIds('window');
out.windowSpec = (spec.find((m) => m.id === 'window') || { items: [] }).items
  .map((i) => [i.id, i.enabled, i.keys]);
const unusableSpec = nativeMenuSpec(env({ usable: () => false }));
out.windowEnabledWhenUnusable = (unusableSpec.find((m) => m.id === 'window') || { items: [] })
  .items.every((i) => i.enabled === true);
out.langItems = all.filter((i) => i.id === 'lang').map((i) => [i.arg, i.label, i.checked]);
const sheetLangSpec = nativeMenuSpec(env({ sheetOpen: () => true }));
out.sheetLangDisabled = sheetLangSpec.flatMap((m) => flat(m.items))
  .filter((i) => i.id === 'lang').every((i) => i.enabled === false);

let active = 0;
const syncOn = createNativeMenuSync({
  getSpec: () => ({}),
  getApi: () => ({ set_native_menu: () => Promise.resolve(true) }),
  hasFocus: () => true,
  onActive: () => { active += 1; },
});
syncOn.push(true);
const syncOff = createNativeMenuSync({
  getSpec: () => ({}),
  getApi: () => ({ set_native_menu: () => Promise.resolve(false) }),
  hasFocus: () => true,
  onActive: () => { active += 10; },
});
syncOff.push(true);
await Promise.resolve();
await Promise.resolve();
out.onActive = active;

out.everyItemHasId = NATIVE_MENUS.length;
console.log(JSON.stringify(out));
})().catch((err) => { console.error(err); process.exit(1); });
