'use strict';
/* Näppäimet eivät saa viedä tekstikenttien omia komentoja tai käynnistää ajoa. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({ console, localStorage: { setItem() {} } });
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nthis.PM = PM;', context);
const pm = context.PM;
const calls = [];
pm.state = { modules: [{ key: 'a' }, { key: 'b' }] };
pm.selectModule = key => calls.push(key);
pm.showShortcuts = () => calls.push('help');
pm.pick = () => calls.push('pick');
const key = (value, extras = {}) => ({key:value, target:{tagName:'DIV',isContentEditable:false}, preventDefault(){this.prevented=true}, ...extras});
assert.ok(pm.shortcuts().length >= 4);
let event = key('2', {metaKey:true});pm.handleShortcut(event);assert.deepEqual(calls,['b']);assert.equal(event.prevented,true);
event = key('2', {metaKey:true,target:{tagName:'INPUT'}});pm.handleShortcut(event);assert.deepEqual(calls,['b']);assert.equal(event.prevented,undefined);
event = key('?',{target:{tagName:'TEXTAREA'}});pm.handleShortcut(event);assert.deepEqual(calls,['b']);
event = key('?');pm.handleShortcut(event);assert.equal(calls.at(-1),'help');
event = key('F1');pm.handleShortcut(event);assert.equal(calls.at(-1),'help');
event = key('o',{ctrlKey:true});pm.handleShortcut(event);assert.equal(calls.at(-1),'pick');
for(const event of [key('1',{ctrlKey:true,altKey:true}),key('Enter',{metaKey:true}),key('1',{metaKey:true,repeat:true}),key('1',{metaKey:true,isComposing:true}),key('5',{metaKey:true})]) {const before=calls.length;pm.handleShortcut(event);assert.equal(calls.length,before);assert.equal(event.prevented,undefined)}
// Help's modal state must block every app command, including the picker.
context.document = { getElementById: () => ({ open: true }) };
for (const event of [key('F1'), key('o', {ctrlKey:true}), key('1', {metaKey:true})]) {
  const before = calls.length; pm.handleShortcut(event);
  assert.equal(calls.length, before); assert.equal(event.prevented, undefined);
}
context.document = { getElementById: () => ({ open: false }) };
for (const event of [key('F1', {defaultPrevented:true}), key('1', {metaKey:true,target:{tagName:'SELECT'}}), key('?', {target:{tagName:'DIV',isContentEditable:true}})]) {
  const before = calls.length; pm.handleShortcut(event);
  assert.equal(calls.length, before); assert.equal(event.prevented, undefined);
}
// Registry stays bounded and chooses the active language's actual tab titles.
context.I18N = {lang:'en'};
pm.state.modules = Array.from({length:12}, (_,i) => ({key:`tab-${i}`, title:{fi:`Työkalu ${i}`,en:`Tool ${i}`}}));
let registry = pm.shortcuts();
assert.equal(registry.length, 11); // two common commands plus nine numbered tabs
assert.equal(registry[2].label, 'Tool 0');
assert.equal(registry.at(-1).key, '⌘ / Ctrl + 9');
event = key('9',{ctrlKey:true});pm.handleShortcut(event);assert.equal(calls.at(-1),'tab-8');
context.I18N.lang = 'fi';
assert.equal(pm.shortcuts()[2].label, 'Työkalu 0');
console.log('OK keyboard shortcuts: text/native keys, help, module bounds, composition, repeats, no Run binding');
