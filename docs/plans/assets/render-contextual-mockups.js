// Renders docs/plans/assets/contextual-controls-mockup.html to the PNGs the plan embeds.
// Usage: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node render-contextual-mockups.js [chromium]
// Fails if the page makes any non-file request: the mockup must run offline.
const path = require('path');

function playwright() {
  try { return require('playwright'); } catch (err) {
    return require('/opt/node-tools/node_modules/playwright');
  }
}

const dir = __dirname;
const page = 'file://' + path.join(dir, 'contextual-controls-mockup.html');
// 1280×820 is pywebview's default window and 960×600 its min_size (autoraffkat gui.py).
const shots = [
  ['menu', 'en', 1280, 820], ['menu', 'fi', 960, 600],
  ['carry', 'en', 1280, 820], ['carry', 'fi', 960, 600],
  ['palette', 'en', 1280, 820], ['palette', 'fi', 960, 600],
];

(async () => {
  const executablePath = process.argv[2] || '/opt/pw-browsers/chromium';
  const browser = await playwright().chromium.launch({ executablePath });
  const outside = [];
  for (const [state, lang, width, height] of shots) {
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    const tab = await context.newPage();
    tab.on('request', (r) => { if (!r.url().startsWith('file://')) outside.push(r.url()); });
    tab.on('pageerror', (e) => { console.error(`${state}/${lang}: ${e.message}`); process.exitCode = 1; });
    await tab.goto(`${page}?state=${state}&lang=${lang}`);
    await tab.screenshot({ path: path.join(dir, `contextual-${state}-${lang}-${width}.png`) });
    await context.close();
  }
  await browser.close();
  if (outside.length) { console.error('external requests:', outside); process.exitCode = 1; }
  else console.log('ok: 6 screenshots, no external requests');
})();
