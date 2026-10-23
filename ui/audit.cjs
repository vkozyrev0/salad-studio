// Checks that every template handler and binding names something real on the page or control.
const fs = require('fs');
const path = require('path');

function walk(dir, out = []) {
  for (const f of fs.readdirSync(dir)) {
    const p = path.join(dir, f);
    if (fs.statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const sources = walk('src/app').filter((f) => f.endsWith('.ts'));
const bySelector = {};
const outputs = {};
const inputs = {};
for (const file of sources) {
  const src = fs.readFileSync(file, 'utf8');
  const cls = (src.match(/export class (\w+)/) || [])[1];
  const selector = (src.match(/selector:\s*'([\w-]+)'/) || [])[1];
  if (selector && cls) bySelector[selector] = cls;
  if (!cls) continue;
  outputs[cls] = [...src.matchAll(/readonly\s+(\w+)\s*=\s*output</g)].map((m) => m[1]);
  // A signal input can be written `readonly x = input<...>(...)` or as a getter;
  // both are what a parent binds to.
  inputs[cls] = [...src.matchAll(/readonly\s+(\w+)\s*=\s*input[<(]/g)].map((m) => m[1]);
}
const KEY_MODIFIERS = /^key(down|up|press)(\.(enter|space|escape|tab|arrowup|arrowdown))*$/;
const DOM_EVENTS = new Set([
  'click', 'change', 'input', 'submit', 'dblclick', 'focus', 'blur', 'keydown', 'keyup', 'keypress',
  'mouseenter', 'pointerdown', 'pointerup', 'pointermove', 'pointercancel', 'pointerleave', 'scroll', 'wheel',
]);
const CONTROL_INPUTS = new Set([
  'rows', 'columns', 'field', 'selected', 'order', 'value', 'options', 'w', 'kind', 'label', 'mono',
  'readonly', 'inputMode', 'placeholder', 'hint', 'graph', 'id', 'type', 'enter', 'aria', 'attr',
  'class', 'style', 'disabled', 'title', 'textContent',
]);

let problems = 0;
for (const file of sources) {
  const src = fs.readFileSync(file, 'utf8');
  const cls = (src.match(/export class (\w+)/) || [])[1];
  if (!cls || !src.includes('template: `')) continue;
  for (const [, tag, body] of src.matchAll(/<([\w-]+)((?:[^>"']|"[^"]*"|'[^']*')*)>/g)) {
    if (tag.startsWith('ng-')) continue;
    const owner = bySelector[tag];
    for (const [, event, handler] of body.matchAll(/\(([\w.]+)(?:\.[\w.]+)?\)="([^"]*)"/g)) {
      if (owner) {
        if (!(outputs[owner] || []).includes(event)) {
          console.log(`${file}: <${tag}> (${event}) is not an output of ${owner}`);
          problems++;
        }
      } else if (!DOM_EVENTS.has(event) && !KEY_MODIFIERS.test(event) && tag !== 'ag-grid-angular') {
        console.log(`${file}: <${tag}> (${event}) is not a DOM event`);
        problems++;
      }
      for (const call of handler.matchAll(/(?<![.\w])([A-Za-z_]\w*)\s*\(/g)) {
        const fn = call[1];
        const declared = new RegExp(String.raw`(protected|private|public)\s+${fn}\b`).test(src);
        if (!declared && !['checked', 'envName', 'envValue'].includes(fn)) {
          console.log(`${file}: (${event}) calls undeclared ${fn}()`);
          problems++;
        }
      }
    }
    if (!owner) continue;
    for (const [, binding] of body.matchAll(/\[([\w.]+)\]="/g)) {
      if (binding.includes('.')) continue;
      if ((inputs[owner] || []).includes(binding) || CONTROL_INPUTS.has(binding)) continue;
      console.log(`${file}: <${tag}> [${binding}] is not a declared input of ${owner}`);
      problems++;
    }
  }
}
console.log(problems ? `${problems} problem(s)` : 'clean: every handler and binding resolves');
process.exit(problems ? 1 : 0);
