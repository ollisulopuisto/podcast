'use strict';

/* Synkkapaneelin aikajanan puhtaat funktiot (asettelu, siirron nimike, rivin
   tila). Omassa tiedostossaan, jotta testi lataa ne sellaisenaan eikä
   leikkaa app.js:ää merkkijonojen välistä. Käyttää vain globaalia LANG
   (i18n.js); app.js kutsuu näitä renderSyncTimeline():stä. */
/* Aikajananäkymä: jokainen tiedosto on palkki vertailukameran palkin alla.
   Palkin paikka on siirto, joten pariutus näkyy ilman lukuja. Asettelu on
   erillinen puhdas funktio, jotta se voidaan testata ilman selainta. */
const SYNC_GOOD_CORRELATION = 0.4;
const SYNC_MAX_SHIFT_S = 1e7;

function syncTimelineLayout(items) {
  const clean = items.map((item) => {
    const shift = Number(item.shift);
    const duration = Number(item.duration);
    return {
      ...item,
      shift: item.reference || !Number.isFinite(shift) ? 0
        : Math.max(-SYNC_MAX_SHIFT_S, Math.min(SYNC_MAX_SHIFT_S, shift)),
      duration: Number.isFinite(duration) && duration > 0 ? duration : 0,
    };
  });
  /* Akseli kattaa vain siirrot, ei tuntien pituisia tiedostoja: muuten
     muutaman sekunnin siirto ei näkyisi lainkaan. Palkit jatkuvat oikean
     reunan yli ja leikkautuvat siihen. */
  const shifts = clean.map((item) => item.shift);
  const low = Math.min(0, ...shifts);
  const high = Math.max(0, ...shifts);
  const pad = Math.max(2, 0.2 * (high - low));
  const start = low < 0 ? low - pad : 0;
  const end = high + pad;
  const span = end - start;
  return {
    zero: 100 * (0 - start) / span,
    span,
    items: clean.map((item) => {
      const left = 100 * (item.shift - start) / span;
      return {
        ...item,
        left,
        width: Math.max(0.5, Math.min(100 * item.duration / span, 100 - left)),
      };
    }),
  };
}

function syncOffsetLabel(value) {
  const text = (value < 0 ? '−' : '+') + Math.abs(value).toFixed(2);
  return (LANG === 'fi' ? text.replace('.', ',') : text) + ' s';
}

/* Käsin muokattu siirto voittaa muut tilat, ja puuttuva arviotietue (uusi
   tiedosto arvion jälkeen) on "ei arvioitu", ei "ei löytynyt": vain
   olemassa oleva tietue, jonka siirto on null, kertoo epäonnistuneesta
   hausta (Devin-arvio 2026-11-18). */
function syncRowStatus(estimate, value, resultReady, edited) {
  if (edited) return 'manual';
  if (!resultReady || !estimate) return 'none';
  if (estimate.shift_seconds === null || estimate.shift_seconds === undefined) {
    return Number(value) === 0 ? 'notFound' : 'manual';
  }
  if (Math.abs(Number(estimate.shift_seconds) - Number(value)) > 0.005) return 'manual';
  return Number(estimate.correlation) >= SYNC_GOOD_CORRELATION ? 'good' : 'check';
}
