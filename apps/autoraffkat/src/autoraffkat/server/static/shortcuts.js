'use strict';

/* Jaettu pikanäppäinkoneisto. Sekä pääsivu (app.js, rekisteri SHORTCUTS) että
   trailer-sivu (trailer.js, rekisteri TRAILER_SHORTCUTS) kuvaavat näppäimensä
   samanmuotoisina riveinä ja ajavat jokaisen painalluksen `shortcutKeyIn`:n
   kautta, joten näppäin jota ei ole rekisterissä ei tee mitään, ja rekisterissä
   oleva näkyy vihjeissä (comboText) ja avustaville ohjelmille (ariaKeys).

   Rekisteririvi: `{ id, group, label, combos, scope, control, text, run }`.
   Kentät kuten app.js:n SHORTCUTS-luettelossa; `run` saa painallustapahtuman,
   jotta esim. vaihtonäppäin voi suurentaa askelta. */

/* Mac vai ei. Näkymä vain: käsittelijä hyväksyy ⌘:n ja Ctrl:n kummassakin.
   iPad on Mac, koska sen näppäimistössä on ⌘. */
function isMacLike(nav) {
  if (!nav) return false;
  const data = nav.userAgentData && nav.userAgentData.platform;
  const said = data || nav.platform || nav.userAgent || '';
  return /mac|iphone|ipad|ipod/i.test(said);
}

function onMac() {
  return isMacLike(typeof navigator !== 'undefined' ? navigator : null);
}

const COMBO_GLYPHS = { ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→' };

/* Yksi yhdistelmä näytettävänä: «⌘E» Macissa, «Ctrl+E» muualla. */
function comboText(combo, mac) {
  let key = combo.key;
  if (COMBO_GLYPHS[key]) key = COMBO_GLYPHS[key];
  else if (key === ' ') key = T('keys.space');
  else if (key === 'Escape') key = 'Esc';
  else if (key.length === 1) key = key.toUpperCase();
  if (!combo.mod) return key;
  if (key === 'Enter') key = mac ? '↩' : 'Enter';
  if (mac) return `${combo.shift ? '⇧' : ''}⌘${key}`;
  return `Ctrl+${combo.shift ? 'Shift+' : ''}${key}`;
}

/* aria-keyshortcuts: molemmat muuntimet, koska molemmat toimivat. */
function ariaKeys(entry) {
  return (entry.combos || []).map((c) => {
    const key = c.key === ' ' ? 'Space' : (c.key.length === 1 ? c.key.toUpperCase() : c.key);
    const shift = c.shift ? 'Shift+' : '';
    return c.mod ? `Meta+${shift}${key} Control+${shift}${key}` : `${shift}${key}`;
  }).join(' ');
}

/* Täsmääkö painallus yhdistelmään. Vaihto ei ratkaise: ? vaatii sen
   useimmilla näppäimistöillä, ja vaihto+⌘E vei ennenkin. Ilman muunninta
   olevaan yhdistelmään ei kelpaa ⌘, Ctrl eikä Alt — ne ovat selaimen. */
function matchesCombo(combo, e) {
  const mod = !!(e.metaKey || e.ctrlKey);
  if (!!combo.mod !== mod) return false;
  if (!combo.mod && e.altKey) return false;
  /* Vaihto ratkaisee vain kun rivi sanoo sen: `shift: true` vaatii sen, `false` kieltää
     sen (⌘R lataa uudestaan, ⇧⌘R renderöi), ja ilman kenttää se ei ratkaise. */
  if (combo.mod && combo.shift !== undefined && !!combo.shift !== !!e.shiftKey) return false;
  return String(e.key || '').toLowerCase() === combo.key.toLowerCase();
}

/* Kirjoitetaanko kohteeseen. Siellä yksinäinen näppäin on tekstiä, ei
   komento — ? kysymykseen ei saa avata ohjetta. Valintaruutu ja liukusäädin
   eivät ota merkkejä. */
function isTypingTarget(el) {
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName.toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = String(el.type || (el.getAttribute && el.getAttribute('type')) || 'text')
    .toLowerCase();
  return !['checkbox', 'radio', 'range', 'button', 'submit', 'reset', 'color', 'file']
    .includes(type);
}

/* Rekisterin rivi tälle painallukselle tässä tilassa, tai null. */
function findShortcutIn(shortcuts, e, scope) {
  const typing = isTypingTarget(e.target);
  return (shortcuts || []).find((s) => (s.scope || []).includes(scope)
    && (s.combos || []).some((c) => matchesCombo(c, e) && (c.mod || !typing))) || null;
}

/* Kaikki näppäinkäsittely kulkee tästä. Palauttaa osuman, jotta kortin oma
   käsittelijä voi tehdä oman toimintonsa samalla tarkistuksella.
   `onSheetShortcut` (vain pääsivulla): ohjeesta suoraan toimintoon sulkee
   ohjeikkunan ensin, ettei modaali jää sen päälle. */
function shortcutKeyIn(shortcuts, e, scope, onSheetShortcut) {
  const hit = findShortcutIn(shortcuts, e, scope);
  if (!hit) return null;
  if (e.preventDefault) e.preventDefault();
  if (hit.run) {
    if (scope === 'sheet' && hit.id !== 'help' && hit.id !== 'close' && onSheetShortcut) {
      onSheetShortcut();
    }
    hit.run(e);
  }
  return hit;
}
