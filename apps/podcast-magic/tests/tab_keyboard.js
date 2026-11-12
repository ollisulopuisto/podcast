'use strict';
/* Välilehtien näppäiskäyttäytyminen: aktivointi, tabindex, paneeli ja
   kohdistus varmistetaan yhdessä, ei tekstivipujen kautta.

   - Ctrl+<n> välilehden ollessa kohdistettuna siirtää kohdistuksen uuteen
     välilehteen; muualta ammuttu pikanäppäin jättää kohdistuksen paikalleen.
   - Alt/Ctrl/Meta/Shift+nuoli jätetään selaimelle (historia, muokatut
     Home/End), eikä välilehti vaihdu eikä oletusta peruta.
*/
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Pieni vale-DOM, joka riittää selectModulen oikealle koodille.
function makeDom(moduleKeys) {
  const dom = { buttons: [], panels: null, document: null };
  const buttons = moduleKeys.map((key) => ({
    tagName: 'BUTTON',
    dataset: { key },
    attrs: {},
    classList: { toggle() {} },
    setAttribute(name, value) { this.attrs[name] = value; },
    focus() {
      dom.document.activeElement = this;
    },
  }));
  const tabs = { contains: (el) => buttons.includes(el) };
  const panels = {
    attrs: {},
    children: [],
    setAttribute(name, value) { this.attrs[name] = value; },
    replaceChildren(...kids) { this.children = kids; },
    appendChild(kid) { this.children.push(kid); },
  };
  dom.buttons = buttons;
  dom.panels = panels;
  dom.document = {
    activeElement: null,
    getElementById: (id) => (id === 'tabs' ? tabs : id === 'panels' ? panels : null),
    querySelectorAll: (sel) => (sel === '#tabs button' ? buttons : []),
  };
  return dom;
}

function setup(moduleKeys) {
  const dom = makeDom(moduleKeys);
  const context = vm.createContext({
    console,
    document: dom.document,
    localStorage: { setItem() {} },
  });
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nthis.PM = PM;', context);
  const pm = context.PM;
  context.I18N = { lang: 'fi', apply() {} };
  pm.state = { modules: moduleKeys.map((key) => ({ key, title: { fi: key }, blurb: { fi: '' } })) };
  pm.modules = new Map(moduleKeys.map((key) => [key, { render(root) { root.rendered = key; } }]));
  pm.el = (tag, attrs, children) => ({ tag, attrs, children });
  pm.active = moduleKeys[0];
  return { pm, dom };
}

const keyEvent = (value, extras = {}) => ({
  key: value,
  target: { tagName: 'BUTTON', isContentEditable: false },
  preventDefault() { this.prevented = true; },
  ...extras,
});

// 1) Ctrl+2 välilehdestä: valinta, tabindex, paneeli JA kohdistus seuraavat.
{
  const { pm, dom } = setup(['a', 'b', 'c']);
  dom.buttons[0].focus(); // kohdistus ensimmäisessä välilehdessä
  const event = keyEvent('2', { ctrlKey: true, target: dom.buttons[0] });
  pm.handleShortcut(event);
  assert.equal(pm.active, 'b');
  assert.equal(dom.buttons[1].attrs.tabindex, '0');
  assert.equal(dom.buttons[0].attrs.tabindex, '-1');
  assert.equal(dom.document.activeElement, dom.buttons[1], 'kohdistus siirtyy valittuun välilehteen');
  assert.equal(dom.panels.attrs['aria-labelledby'], 'tab-b');
  assert.equal(dom.panels.children.length, 1, 'paneeli piirretään uudelleen');
}

// 2) Ctrl+2 muualta (ei välilehtiraidasta): valinta vaihtuu, kohdistus pysyy.
{
  const { pm, dom } = setup(['a', 'b', 'c']);
  const outside = { tagName: 'DIV', isContentEditable: false };
  dom.document.activeElement = outside;
  pm.handleShortcut(keyEvent('2', { ctrlKey: true, target: outside }));
  assert.equal(pm.active, 'b');
  assert.equal(dom.document.activeElement, outside, 'kohdistus ei lähde lomakkeesta');
}

// 3) Nuolinavigointi radassa: ArrowRight valitsee ja kohdistaa seuraavan.
{
  const { pm, dom } = setup(['a', 'b', 'c']);
  const event = keyEvent('ArrowRight');
  pm.handleTabKeydown(event);
  assert.equal(pm.active, 'b');
  assert.equal(event.prevented, true);
  assert.equal(dom.document.activeElement, dom.buttons[1]);
  const home = keyEvent('Home');
  pm.handleTabKeydown(home);
  assert.equal(pm.active, 'a');
  assert.equal(dom.document.activeElement, dom.buttons[0]);
}

// 4) Selaimen omat yhdistelmät jäävät rauhaan: Alt+Vasen, Ctrl+Oikea,
//    Shift+Home eivät vaihda välilehteä eivätkä peru oletusta.
{
  const { pm, dom } = setup(['a', 'b', 'c']);
  for (const event of [
    keyEvent('ArrowLeft', { altKey: true }),
    keyEvent('ArrowRight', { altKey: true }),
    keyEvent('ArrowRight', { ctrlKey: true }),
    keyEvent('ArrowLeft', { metaKey: true }),
    keyEvent('Home', { shiftKey: true }),
    keyEvent('End', { altKey: true }),
  ]) {
    pm.handleTabKeydown(event);
    assert.equal(pm.active, 'a', `${event.key} muokkaimella ei saa vaihtaa välilehteä`);
    assert.equal(event.prevented, undefined, `${event.key} muokkaimella ei saa perua oletusta`);
  }
  assert.equal(dom.document.activeElement, null, 'kohdistus jää selaimen haltuun');
}

console.log('OK tab keyboard: shortcut focus, roving tabindex, panel sync, browser shortcuts preserved');
