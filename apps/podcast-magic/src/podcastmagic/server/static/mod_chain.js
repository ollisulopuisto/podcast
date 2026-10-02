'use strict';

/* Ketjupaneeli: litterointi, vaimennus ja miksaus yhdellä napilla.

   Paneelilla ei ole vaiheiden omia säätimiä. Vaiheet käyttävät Litterointi-
   ja Vaimennus-välilehdillä viimeksi tallennettuja asetuksia, joten ketju
   tekee saman kuin kaksi painallusta eikä kahta eri tapaa säätää samaa
   asiaa synny. Valinnat tallentuvat: «ei aina» tarkoittaa, että viimeksi
   valittu yhdistelmä on seuraavallakin kerralla valmiina. */

(() => {
  const state = { info: null };

  function check(id, label, why, on, disabled) {
    const input = PM.el('input', {
      type: 'checkbox', id, ...(on ? { checked: true } : {}), ...(disabled ? { disabled: true } : {}),
    });
    return PM.el('label', { class: 'check' }, [
      input,
      PM.el('span', { class: 'body' }, [
        PM.el('span', { text: label }),
        PM.el('span', { class: 'why', text: why }),
      ]),
    ]);
  }

  function values(root) {
    return {
      steps: {
        transcribe: root.querySelector('#ch-transcribe').checked,
        silence: root.querySelector('#ch-silence').checked,
        mix: root.querySelector('#ch-mix').checked,
      },
      targetLufs: Number(root.querySelector('#ch-lufs').value),
    };
  }

  PM.registerModule({
    key: 'chain',

    async render(root, app) {
      if (!state.info) {
        try { state.info = await app.api('/api/chain/info'); }
        catch (error) { root.appendChild(PM.el('p', { text: error.message })); return; }
      }
      const { steps, mixer, targetLufs } = state.info;

      root.appendChild(PM.el('p', { class: 'muted small', text: PM.t('ch.about') }));
      root.appendChild(PM.el('h2', { text: PM.t('ch.steps') }));
      root.appendChild(PM.el('div', { class: 'rows' }, [
        check('ch-transcribe', PM.t('ch.transcribe'), PM.t('ch.transcribeWhy'), steps.transcribe),
        check('ch-silence', PM.t('ch.silence'), PM.t('ch.silenceWhy'), steps.silence),
        check('ch-mix', PM.t('ch.mix'),
              mixer.available ? PM.t('ch.mixWhy') : PM.t('ch.noMixer', { cmd: mixer.install }),
              steps.mix && mixer.available, !mixer.available),
      ]));

      root.appendChild(PM.el('label', { class: 'field' }, [
        PM.el('span', { text: PM.t('ch.lufs') }),
        PM.el('input', { type: 'number', id: 'ch-lufs', min: -40, max: -5, step: 0.5, value: targetLufs }),
        PM.el('span', { class: 'hint', text: PM.t('ch.lufsWhy') }),
      ]));

      const runButton = PM.el('button', { class: 'primary', text: PM.t('ch.run') });
      runButton.addEventListener('click', () => {
        const chosen = values(root);
        if (!Object.values(chosen.steps).some(Boolean)) {
          PM.banner(PM.t('ch.nothing'), true);
          return;
        }
        PM.banner('');
        state.info = { ...state.info, ...chosen };
        app.run('chain', '/api/chain/run', chosen, runButton);
      });
      root.appendChild(PM.el('div', { class: 'rows' }, [runButton]));
    },
  });
})();
