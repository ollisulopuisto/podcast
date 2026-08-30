'use strict';

/* Käsikirjoituspaneeli. Litterointi on jo istunnossa; tämä näyttää sen
   luettavana ja kirjoittaa markdownin istunnon viereen. Ennakko on vain
   XML:n lukeminen, joten se ei maksa mitään eikä koske ääntä. */

(() => {
  async function refresh(root) {
    const box = root.querySelector('#sc-preview');
    if (!PM.session) { box.replaceChildren(); return; }
    try {
      const result = await PM.api('/api/script/preview', { session: PM.session });
      if (!result.markdown) {
        box.replaceChildren(PM.el('p', { class: 'muted small', text: PM.t('app.noWords') }));
        return;
      }
      const pre = PM.el('pre', { class: 'script' });
      pre.textContent = result.markdown;
      box.replaceChildren(pre);
    } catch (error) {
      box.replaceChildren(PM.el('p', { class: 'muted small', text: error.message }));
    }
  }

  PM.registerModule({
    key: 'script',

    async render(root, app) {
      root.appendChild(PM.el('p', { class: 'muted small', text: PM.t('sc.about') }));
      root.appendChild(PM.el('h3', { text: PM.t('sc.preview') }));
      root.appendChild(PM.el('div', { id: 'sc-preview' }));

      const runButton = PM.el('button', { class: 'primary', text: PM.t('sc.run') });
      runButton.addEventListener('click', () => {
        app.run('script', '/api/script/run', {}, runButton);
      });
      root.appendChild(PM.el('div', { class: 'rows' }, [runButton]));

      refresh(root);
    },

    onSession() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#sc-preview')) refresh(root);
    },

    onFinished() {
      const root = document.querySelector('#panels .panel');
      if (root && root.querySelector('#sc-preview')) refresh(root);
    },
  });
})();
