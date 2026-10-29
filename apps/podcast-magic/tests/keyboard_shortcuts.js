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
console.log('OK keyboard shortcuts: text/native keys, help, module bounds, composition, repeats, no Run binding');
