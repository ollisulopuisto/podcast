'use strict';

/* Litteroinnin siirto. Käyttäjä valitsee leikatun istunnon kuoressa ja
   kertoo tässä mistä litterointi kopioidaan. Ennakko kertoo tiedosto
   kerralla mitä tapahtuisi — mukaan lukien ne jotka eivät tapahdu, sillä
   «ei kopioitu» on juuri se tieto jonka puuttuminen teki vanhasta
   versiosta vaarallisen. */

(() => {
  const state = { timer: null, overwrite: false };

  function values(root) {
    return {
      source: root.querySelector('#mg-source').value.trim(),
      overwrite: root.querySelector('#mg-overwrite').checked,
    };
  }

  function table(report) {
    const rows = [
      ['mg.copied', report.copied],
      ['mg.overwritten', report.overwritten],
      ['mg.kept', report.kept],
      ['mg.mismatched', report.mismatched],
      ['mg.unverified', report.unverified],
      ['mg.missing', report.missing],
    ].filter(([, names]) => names.length);
    const box = PM.el('div', {}, rows.map(([key, names]) => PM.el('div', { class: 'rows' }, [
      PM.el('strong', { text: PM.t(key) }),
      PM.el('span', { text: names.join(', ') }),
    ])));
    if (report.unverified.length) {
      box.appendChild(PM.el('p', { class: 'muted small', text: PM.t('mg.unverifiedWhy') }));
    }
    return box;
  }

  async function refresh(root) {
    const box = root.querySelector('#mg-preview');
    const args = values(root);
    if (!PM.session || !args.source) { box.replaceChildren(); return; }
    try {
      const report = await PM.api('/api/merge/preview', { session: PM.session, ...args });
      box.replaceChildren(table(report));
    } catch (error) {
      box.replaceChildren(PM.el('p', { class: 'muted small', text: error.message }));
    }
  }

  function schedule(root) {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => refresh(root), 200);
  }

  PM.registerModule({
    key: 'merge',

    async render(root, app) {
      try {
        const info = await app.api('/api/merge/info');
        state.overwrite = !!info.overwrite;
      } catch { state.overwrite = false; }

      root.appendChild(PM.el('p', { class: 'muted small', text: PM.t('mg.about') }));

      root.appendChild(PM.el('label', { class: 'field wide' }, [
        PM.el('span', { text: PM.t('mg.source') }),
        PM.el('input', { type: 'text', id: 'mg-source', placeholder: PM.t('mg.sourceHint') }),
      ]));

      root.appendChild(PM.el('label', { class: 'check' }, [
        PM.el('input', {
          type: 'checkbox', id: 'mg-overwrite',
          ...(state.overwrite ? { checked: true } : {}),
        }),
        PM.el('span', { class: 'body' }, [
          PM.el('span', { text: PM.t('mg.overwrite') }),
          PM.el('span', { class: 'why', text: PM.t('mg.overwriteWhy') }),
        ]),
      ]));

      root.appendChild(PM.el('h3', { text: PM.t('mg.preview') }));
      root.appendChild(PM.el('div', { id: 'mg-preview' }));

      const runButton = PM.el('button', { class: 'primary', text: PM.t('mg.run') });
      runButton.addEventListener('click', () => {
        app.run('merge', '/api/merge/run', values(root), runButton);
      });
      root.appendChild(PM.el('div', { class: 'rows' }, [runButton]));

      root.addEventListener('input', () => schedule(root));
      refresh(root);
    },

    onSession() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#mg-preview')) refresh(root);
    },

    onFinished() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#mg-preview')) refresh(root);
    },
  });
})();
