'use strict';

/* Vaimennuspaneeli.

   Ennakko lasketaan säädintä liikuttaessa, koska häntä ja lyhin tauko ovat
   säätimiä joiden vaikutusta ei voi arvata: «0,4 vai 1,0 sekuntia» on
   vastattavissa vasta kun näkee montako jaksoa kummastakin tulee. Tason
   tarkistus jätetään ennakosta pois — se purkaisi jokaisen raidan levyltä,
   ja liukusäätimen viereen minuutin päästä ilmestyvä luku ei ole ennakko. */

(() => {
  const state = { info: null, settings: null, timer: null };

  function values(root) {
    return {
      tail: Number(root.querySelector('#si-tail').value),
      gap: Number(root.querySelector('#si-gap').value),
      rms: root.querySelector('#si-rms').checked,
      threshold: Number(root.querySelector('#si-threshold').value),
      dominance: Number(root.querySelector('#si-dominance').value),
    };
  }

  function slider(id, label, why, value, min, max, step, unit) {
    const input = PM.el('input', { type: 'range', id, min, max, step, value });
    const out = PM.el('output', { text: `${Number(value).toFixed(step < 1 ? 1 : 0)} ${unit}` });
    input.addEventListener('input', () => {
      out.textContent = `${Number(input.value).toFixed(step < 1 ? 1 : 0)} ${unit}`;
    });
    return PM.el('label', { class: 'field' }, [
      PM.el('span', { text: label }),
      PM.el('span', { class: 'slider' }, [input, out]),
      PM.el('span', { class: 'hint', text: why }),
    ]);
  }

  // `bled` on oma sarakkeensa eikä alaviite, ja se näkyy myös nollana silloin
  // kun vertailu on päällä: säädin jonka vaikutusta ei näe on säädin jota ei
  // osaa säätää, ja «ei löytynyt vuotoa» on eri tulos kuin «ei etsitty».
  function table(rows, rmsSkipped, showBled) {
    if (!rows.length) return PM.el('p', { class: 'muted small', text: PM.t('app.noWords') });
    const head = [PM.t('si.track'), PM.t('si.trackWords')];
    if (showBled) head.push(PM.t('si.bled'));
    head.push(PM.t('si.zones'), PM.t('si.audible'));
    return PM.el('div', { class: 'table-wrap' }, [
      PM.el('table', {}, [
        PM.el('thead', {}, [PM.el('tr', {}, head.map((title, i) => PM.el(
          'th', { class: i ? 'num' : '', text: title },
        )))]),
        PM.el('tbody', {}, rows.map((row) => PM.el('tr', { class: row.skipped ? 'off' : '' }, [
          PM.el('td', { text: row.name || '—' }),
          PM.el('td', { class: 'num', text: String(row.words) }),
          showBled
            ? PM.el('td', { class: 'num', text: row.skipped ? '—' : String(row.bled || 0) })
            : null,
          PM.el('td', { class: 'num', text: row.skipped ? '—' : String(row.zones) }),
          PM.el('td', {
            class: 'num',
            text: row.skipped ? PM.t('si.untouched') : `${Math.round(row.audible / 60)} min`,
          }),
        ]))),
      ]),
      rmsSkipped ? PM.el('p', { class: 'muted small', text: PM.t('si.rmsLater') }) : null,
    ]);
  }

  async function refresh(root) {
    const box = root.querySelector('#si-preview');
    if (!PM.session) { box.replaceChildren(); return; }
    try {
      const result = await PM.api('/api/silence/preview', {
        session: PM.session, settings: values(root),
      });
      const settings = values(root);
      box.replaceChildren(table(
        result.tracks, result.rmsSkipped, settings.rms && settings.dominance > 0,
      ));
    } catch (error) {
      box.replaceChildren(PM.el('p', { class: 'muted small', text: error.message }));
    }
  }

  function schedule(root) {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => refresh(root), 200);
  }

  PM.registerModule({
    key: 'silence',

    async render(root, app) {
      if (!state.info) {
        try { state.info = await app.api('/api/silence/info'); }
        catch (error) { root.appendChild(PM.el('p', { text: error.message })); return; }
      }
      const saved = state.settings || state.info.settings;

      const presetSelect = PM.el('select', { id: 'si-preset' }, [
        ...Object.keys(state.info.presets).map((name) => PM.el('option', {
          value: name, text: PM.t(`si.preset.${name}`),
        })),
        PM.el('option', { value: 'custom', text: PM.t('si.preset.custom') }),
      ]);

      root.appendChild(PM.el('h2', { text: PM.t('si.run') }));

      /* Ajastus vasemmalle, tason tarkistus oikealle. Kynnys ja erotus ovat
         tason tarkistuksen säätimiä eivätkä omiaan, joten ne ovat sen
         kanssa samassa sarakkeessa. */
      const left = PM.el('div', {}, [
        PM.el('label', { class: 'field' }, [
          PM.el('span', { text: PM.t('si.preset') }), presetSelect,
        ]),
        slider('si-tail', PM.t('si.tail'), PM.t('si.tailWhy'), saved.tail, 0, 2, 0.1, 's'),
        slider('si-gap', PM.t('si.gap'), PM.t('si.gapWhy'), saved.gap, 0, 2, 0.1, 's'),
      ]);
      const right = PM.el('div', { class: 'right' }, [
        PM.el('label', { class: 'check' }, [
          PM.el('input', { type: 'checkbox', id: 'si-rms', ...(saved.rms ? { checked: true } : {}) }),
          PM.el('span', { class: 'body' }, [
            PM.el('span', { text: PM.t('si.rms') }),
            PM.el('span', { class: 'why', text: PM.t('si.rmsWhy') }),
          ]),
        ]),
        slider('si-threshold', PM.t('si.threshold'), '', saved.threshold, -60, -10, 1, 'dB'),
        // Ylärajaksi 24: mitattu ero oman puheen ja vuodon välillä on
        // mediaanissa 12,8 dB, joten sitä leveämpi kaista ei enää erottele.
        // Nolla on «pois», ja se on kaistan alapää eikä oma valintansa.
        slider('si-dominance', PM.t('si.dominance'), PM.t('si.dominanceWhy'),
               saved.dominance, 0, 24, 1, 'dB'),
      ]);
      root.appendChild(PM.el('div', { class: 'cols' }, [left, right]));

      // Esivalinta asettaa säätimet; säätimen liikuttaminen tekee valinnasta
      // «oma». Kumpikaan suunta ei saa valehdella toisesta.
      presetSelect.addEventListener('change', () => {
        const preset = state.info.presets[presetSelect.value];
        if (!preset) return;
        for (const [id, value] of Object.entries({
          'si-tail': preset.tail, 'si-gap': preset.gap, 'si-threshold': preset.threshold,
          'si-dominance': preset.dominance,
        })) {
          const input = root.querySelector(`#${id}`);
          input.value = value;
          input.dispatchEvent(new Event('input'));
        }
        root.querySelector('#si-rms').checked = preset.rms;
        state.settings = values(root);
        schedule(root);
      });
      presetSelect.value = matchPreset(saved, state.info.presets);

      root.appendChild(PM.el('h3', { text: PM.t('si.preview') }));
      root.appendChild(PM.el('div', { id: 'si-preview' }));

      const runButton = PM.el('button', { class: 'primary', text: PM.t('si.run') });
      runButton.addEventListener('click', () => {
        state.settings = values(root);
        app.run('silence', '/api/silence/run', { settings: state.settings }, runButton);
      });
      root.appendChild(PM.el('div', { class: 'rows' }, [runButton]));

      root.addEventListener('input', (event) => {
        if (event.target.id === 'si-preset') return;
        state.settings = values(root);
        presetSelect.value = matchPreset(state.settings, state.info.presets);
        schedule(root);
      });

      refresh(root);
    },

    onSession() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#si-preview')) refresh(root);
    },

    onFinished() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#si-preview')) refresh(root);
    },
  });

  function matchPreset(settings, presets) {
    for (const [name, preset] of Object.entries(presets)) {
      const same = Math.abs(preset.tail - settings.tail) < 0.001
        && Math.abs(preset.gap - settings.gap) < 0.001
        && Math.abs(preset.threshold - settings.threshold) < 0.001
        && Math.abs(preset.dominance - settings.dominance) < 0.001
        && !!preset.rms === !!settings.rms;
      if (same) return name;
    }
    return 'custom';
  }
})();
