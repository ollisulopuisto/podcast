'use strict';
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('class SessionHistory {');
const end = source.indexOf('const sessionHistories', start);
const History = vm.runInNewContext(source.slice(start, end) + '\nSessionHistory');
const history = new History({ tracks: {}, globals: { min_shot: 0 }, audio: {} });
for (let i = 1; i <= 1000; i++) history.commit({ tracks: {}, globals: { min_shot: i }, audio: {} });
for (let i = 999; i >= 0; i--) { history.undo(); assert.equal(JSON.parse(history.nodes[history.head].value).globals.min_shot, i); }
for (let i = 1; i <= 1000; i++) { history.redo(); assert.equal(JSON.parse(history.nodes[history.head].value).globals.min_shot, i); }
const original = history.head;
history.undo(); history.commit({ tracks: { mic: { speaker: 'Branch' } }, globals: {}, audio: { enabled: true } });
const branch = history.head;
assert.equal(history.tips().length, 2);
history.goto(original); assert.equal(JSON.parse(history.nodes[history.head].value).globals.min_shot, 1000);
history.undo(); history.redo(); assert.equal(history.head, original);
history.goto(branch); assert.equal(JSON.parse(history.nodes[history.head].value).tracks.mic.speaker, 'Branch');
const size = history.nodes.length;
history.commit(JSON.parse(history.nodes[history.head].value)); assert.equal(history.nodes.length, size);
history.goto(-1); assert.equal(history.head, branch);
console.log('1000 edits, full undo/redo, alternate branch selection, snapshots and no-op checks passed');
