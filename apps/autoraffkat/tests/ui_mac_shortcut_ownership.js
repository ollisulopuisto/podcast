'use strict';
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../src/autoraffkat/server/static/shortcuts.js'), 'utf8');
for (const mac of [true, false]) {
  const context = vm.createContext({ navigator: { platform: mac ? 'MacIntel' : 'Linux' } });
  vm.runInContext(source, context);
  let calls = [];
  const rows = ['open', 'export', 'undo', 'redo'].map((id) => ({ id, scope: ['page'], combos: [{ mod: true, key: {open:'o',export:'e',undo:'z',redo:'z'}[id], shift: id === 'redo' }], run: () => calls.push(id) }));
  const field = { tagName: 'INPUT', type: 'text' };
  for (const target of [{ tagName: 'DIV' }, field, { tagName: 'TEXTAREA' }, { tagName: 'DIV', isContentEditable: true }]) {
    for (const row of rows) {
      for (const ctrl of [false, true]) {
        calls = [];
        const event = { key: row.combos[0].key, metaKey: !ctrl, ctrlKey: ctrl, shiftKey: row.id === 'redo', target, prevented: false, preventDefault() { this.prevented = true; } };
        context.shortcutKeyIn(rows, event, 'page');
        const typing = context.isTypingTarget(target);
        const expected = !(mac && ctrl) && !(typing && ['undo', 'redo'].includes(row.id));
        assert.equal(event.prevented, expected, `${mac}/${ctrl}/${target.tagName}/${row.id}`);
        assert.deepEqual(calls, expected ? [row.id] : []);
      }
    }
  }
  const both = { key: 'e', ctrlKey: true, metaKey: true };
  assert.equal(context.matchesCombo({ mod: true, key: 'e' }, both), !mac);
  assert.equal(context.ariaKeys(rows[1]), mac ? 'Meta+E' : 'Meta+E Control+E');
}
console.log('Mac modifier and focused text history dispatch: pass');
