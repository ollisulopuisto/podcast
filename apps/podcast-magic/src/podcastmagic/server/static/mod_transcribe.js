'use strict';

/* Litterointipaneeli.

   Ennakko («mitä tehdään») on oma vaiheensa eikä vasta ajon loki. Litterointi
   kestää minuutteja per tiedosto, ja se ettei mitään tapahdu — koska kaikki
   oli jo litteroitu tai koska poolin ääniä ei löytynyt levyltä — pitää
   selvitä ennen kuin sitä ehtii odottaa. */

(() => {
  const state = { info: null, plan: null, options: null };

  function options(root) {
    return {
      backend: root.querySelector('#tr-backend').value,
      model: root.querySelector('#tr-model').value,
      language: root.querySelector('#tr-language').value.trim(),
      fillers: root.querySelector('#tr-fillers').checked,
      vad: root.querySelector('#tr-vad').checked,
      initial_prompt: root.querySelector('#tr-prompt').value,
    };
  }

  function field(label, control, hint) {
    return PM.el('label', { class: 'field' }, [
      PM.el('span', { text: label }),
      control,
      hint ? PM.el('span', { class: 'hint', text: hint }) : null,
    ]);
  }

  function check(id, label, why, checked) {
    return PM.el('label', { class: 'check' }, [
      PM.el('input', { type: 'checkbox', id, ...(checked ? { checked: true } : {}) }),
      PM.el('span', { class: 'body' }, [
        PM.el('span', { text: label }),
        PM.el('span', { class: 'why', text: why }),
      ]),
    ]);
  }

  function planTable(plan) {
    const rows = [];
    for (const item of plan.todo) rows.push([item.name, PM.t('tr.todo'), '']);
    for (const item of plan.skipped) {
      rows.push([item.name, PM.t('tr.skipped'), `${item.words || 0}`]);
    }
    for (const item of plan.missing) rows.push([item.name, PM.t('tr.missing'), '']);
    if (!rows.length) return PM.el('p', { class: 'muted small', text: PM.t('tr.nothing') });

    const body = PM.el('tbody', {}, rows.map(([name, what, words]) => PM.el(
      'tr', { class: what === PM.t('tr.todo') ? '' : 'off' }, [
        PM.el('td', { text: name }),
        PM.el('td', { text: what }),
        PM.el('td', { class: 'num', text: words }),
      ],
    )));
    return PM.el('div', { class: 'table-wrap' }, [
      PM.el('table', {}, [
        PM.el('thead', {}, [PM.el('tr', {}, [
          PM.el('th', { text: PM.t('tr.file') }),
          PM.el('th', { text: PM.t('tr.state') }),
          PM.el('th', { class: 'num', text: PM.t('si.trackWords') }),
        ])]),
        body,
      ]),
    ]);
  }

  async function refreshPlan(root) {
    const box = root.querySelector('#tr-plan');
    if (!PM.session) { box.replaceChildren(); return; }
    try {
      state.plan = await PM.api('/api/transcribe/plan', {
        session: PM.session,
        options: options(root),
        force: root.querySelector('#tr-force').checked,
      });
      box.replaceChildren(planTable(state.plan));
    } catch (error) {
      box.replaceChildren(PM.el('p', { class: 'muted small', text: error.message }));
    }
  }

  PM.registerModule({
    key: 'transcribe',

    async render(root, app) {
      if (!state.info) {
        try { state.info = await app.api('/api/transcribe/info'); }
        catch (error) { root.appendChild(PM.el('p', { text: error.message })); return; }
      }
      const saved = state.options || state.info.options;

      const backends = state.info.backends;
      const usable = backends.filter((b) => b.available);
      const backendSelect = PM.el('select', { id: 'tr-backend' }, [
        PM.el('option', { value: 'auto', text: PM.t('tr.engineAuto') }),
        ...backends.map((b) => PM.el('option', {
          value: b.key,
          text: b.available ? `${b.label} — ${b.device}` : `${b.label} — ${b.reason}`,
          ...(b.available ? {} : { disabled: true }),
        })),
      ]);
      backendSelect.value = saved.backend || 'auto';

      const modelSelect = PM.el('select', { id: 'tr-model' }, state.info.models.map(
        (m) => PM.el('option', { value: m.key, text: m.label }),
      ));
      modelSelect.value = saved.model || state.info.defaultModel;
      const modelHint = PM.el('span', { class: 'hint' });
      const showHint = () => {
        const chosen = state.info.models.find((m) => m.key === modelSelect.value);
        modelHint.textContent = chosen ? (chosen.hint[I18N.lang] || chosen.hint.fi) : '';
      };
      showHint();
      modelSelect.addEventListener('change', showHint);

      const languageInput = PM.el('input', {
        type: 'text', id: 'tr-language', value: saved.language ?? 'fi',
        placeholder: PM.t('tr.languageAuto'), spellcheck: 'false',
      });
      const promptInput = PM.el('input', {
        type: 'text', id: 'tr-prompt', value: saved.initial_prompt || '',
        placeholder: 'Hindenburg, Sulopuisto, litterointi',
      });

      root.appendChild(PM.el('h2', { text: PM.t('tr.run') }));
      if (!usable.length) {
        const hints = backends.map((b) => PM.t('tr.installHint', { cmd: b.install })).join('  ·  ');
        root.appendChild(PM.el('p', { class: 'banner error',
                                      text: `${PM.t('tr.noBackend')}\n${hints}` }));
      }
      root.appendChild(field(PM.t('tr.engine'), backendSelect));
      root.appendChild(PM.el('label', { class: 'field' }, [
        PM.el('span', { text: PM.t('tr.model') }), modelSelect, modelHint,
      ]));
      root.appendChild(field(PM.t('tr.language'), languageInput, PM.t('tr.languageAuto')));
      root.appendChild(field(PM.t('tr.prompt'), promptInput, PM.t('tr.promptWhy')));
      root.appendChild(check('tr-fillers', PM.t('tr.fillers'), PM.t('tr.fillersWhy'), saved.fillers));
      root.appendChild(check('tr-vad', PM.t('tr.vad'), PM.t('tr.vadWhy'), saved.vad));
      root.appendChild(check('tr-force', PM.t('tr.force'), PM.t('tr.forceWhy'), false));

      root.appendChild(PM.el('h3', { text: PM.t('tr.plan') }));
      root.appendChild(PM.el('div', { id: 'tr-plan' }));

      const runButton = PM.el('button', { class: 'primary', text: PM.t('tr.run') });
      runButton.addEventListener('click', () => {
        state.options = options(root);
        app.run('transcribe', '/api/transcribe/run', {
          options: state.options,
          force: root.querySelector('#tr-force').checked,
        }, runButton);
      });
      root.appendChild(PM.el('div', { class: 'rows' }, [runButton]));

      root.addEventListener('change', () => { state.options = options(root); refreshPlan(root); });
      refreshPlan(root);
    },

    onSession() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#tr-plan')) refreshPlan(root);
    },

    onFinished() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#tr-plan')) refreshPlan(root);
    },
  });
})();
