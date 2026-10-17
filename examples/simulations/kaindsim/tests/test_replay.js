// Execute the exported UI against a minimal DOM to check real event handlers.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.style = {}; this.events = {}; this.textContent = ''; this.value = '120'; this.classList = {toggle() {}}; }
  setAttribute(key, value) { this.attrs[key] = value; }
  appendChild(child) { this.children.push(child); }
  append(text) { this.textContent += text; }
  addEventListener(event, handler) { this.events[event] = handler; }
}
const elements = {};
for (const match of html.matchAll(/id="([^"]+)"/g)) elements[match[1]] = new Element();
elements.experiment.textContent = html.match(/<script id="experiment" type="application\/json">([\s\S]*?)<\/script>/)[1];
const data = JSON.parse(elements.experiment.textContent);
let nextFrame;
const context = {document: {getElementById: id => elements[id], createElement: () => new Element(), createElementNS: () => new Element()},
  Blob, URL, setInterval: callback => {nextFrame = callback; return 1;}, clearInterval: () => {nextFrame = null;}};
vm.createContext(context);
vm.runInContext(html.match(/<script>\s*([\s\S]*?)<\/script>/)[1], context);
assert.equal(elements.map.children.length, 192);
assert.equal(elements.tabs.children.length, data.runs.length);
assert.equal(elements.clock.textContent, 'H 000');
elements.time.value = 24; elements.time.oninput();
assert.equal(elements.clock.textContent, 'H 024');
assert.equal(elements.stored.textContent, data.runs[0].frames[24].stored.toLocaleString());
elements.tabs.children[1].onclick();
assert.equal(elements.policyname.textContent, 'Protect homes');
assert.equal(elements.stored.textContent, data.runs[1].frames[24].stored.toLocaleString());
elements.map.children[0].events.click();
assert.match(elements.detail.textContent, /Catchment 0, 0/);
elements.play.onclick(); assert.equal(elements.play.textContent, 'Pause');
nextFrame(); assert.equal(elements.clock.textContent, 'H 025');
elements.play.onclick(); assert.equal(elements.play.textContent, 'Play');
elements.time.value = data.steps; elements.time.oninput();
elements.play.onclick(); assert.equal(elements.clock.textContent, 'H 000');
elements.play.onclick();
assert.match(elements.download.href, /^blob:/);
console.log('Replay controls: timeline, policies, catchment inspection, play/pause and restart passed.');
