// Editor for a list of API 521 relief scenarios, shared by the relief valve in the designer
// and the stand-alone relief sizing page.

import { store } from './store.js';
import { h, toast } from './dom.js';
import { fromUser, inputValue, unitLabel, NUMERIC_KINDS } from './units.js';

export function scenarioDefaults(type) {
  const t = store.catalog.scenarios[type];
  const v = { type, enabled: true };
  for (const p of t.params) v[p.key] = JSON.parse(JSON.stringify(p.default));
  return v;
}

function field(label, control, unit = '', help = '') {
  return h('div', { class: 'field' },
    h('label', {}, label, help ? h('span', { class: 'help' }, help) : null),
    h('div', { class: 'ctl' }, control, unit ? h('span', { class: 'unit' }, unit) : null));
}

function selectInput(options, value, onCommit, key, labels = null) {
  const sel = h('select', { 'data-key': key });
  for (const o of options) sel.append(h('option', { value: o, selected: o === value }, labels ? labels(o) : o));
  sel.addEventListener('change', () => onCommit(sel.value));
  return sel;
}

function numberInput(kind, value, onCommit, key) {
  const input = h('input', { type: 'text', inputmode: 'decimal', value: inputValue(kind, value), 'data-key': key });
  input.addEventListener('change', () => {
    const v = Number(input.value.trim().replace(/,/g, ''));
    if (!Number.isFinite(v)) { input.classList.add('invalid'); toast('Enter a number.', 'err'); return; }
    input.classList.remove('invalid');
    onCommit(fromUser(kind, v));
  });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  return input;
}

const GOVERNS = ' — this one governs the valve size.';

/** Re-mark the governing scenario's card after a new result, without rebuilding the editor. */
export function markGoverning(root, governing) {
  for (const card of root.querySelectorAll('.scenario-card')) {
    const on = Boolean(governing) && governing.startsWith(card.dataset.label);
    card.classList.toggle('governs', on);
    const note = card.querySelector('.sc-gov');
    if (note) note.textContent = on ? GOVERNS : '';
  }
}

// settings that stay editable when a scenario takes its values from equipment on the drawing
const KEEP_WITH_BLOCK = new Set(['name', 'credit', 'bypass_open', 'bypass_cv', 'source']);

/**
 * list: the scenarios; setList(newList) stores a changed list.
 * opts.blocks(types) -> names of equipment on the drawing of those types (omit on the stand-alone page);
 * opts.governing: title of the governing scenario (highlights its card); opts.keyPrefix for input keys.
 */
export function scenarioEditor(list, setList, opts = {}) {
  const cat = store.catalog.scenarios || {};
  const prefix = opts.keyPrefix || 'sc';
  const update = (i, key, value) => setList(list.map((sc, j) => (j === i ? { ...sc, [key]: value } : sc)));
  const cards = list.map((sc, i) => {
    const t = cat[sc.type];
    if (!t) return h('div', { class: 'msg err' }, `Unknown scenario type ${sc.type}`);
    const typeSel = selectInput(Object.keys(cat), sc.type, (v) => setList(list.map((x, j) => (j === i ? scenarioDefaults(v) : x))),
      `${prefix}-${i}-type`, (o) => cat[o]?.label || o);
    const fromBlock = opts.blocks && t.block_param && sc[t.block_param];
    const fields = [];
    for (const q of t.params) {
      if (q.kind === 'block_choice' && !opts.blocks) continue;
      if (q.show_if) {
        const ctrl = sc[q.show_if[0]] ?? t.params.find((z) => z.key === q.show_if[0])?.default;
        if (!q.show_if[1].includes(ctrl)) continue;
      }
      if (fromBlock && q.key !== t.block_param && !KEEP_WITH_BLOCK.has(q.key)) continue;
      const key = `${prefix}-${i}-${q.key}`;
      const val = sc[q.key] ?? q.default;
      const set = (v) => update(i, q.key, v);
      if (q.kind === 'choice') fields.push(field(q.label, selectInput(q.choices, val, set, key), '', q.help));
      else if (q.kind === 'text') {
        const input = h('input', { type: 'text', value: val ?? '', 'data-key': key });
        input.addEventListener('change', () => set(input.value));
        fields.push(field(q.label, input, '', q.help));
      } else if (q.kind === 'block_choice') {
        const names = ['', ...opts.blocks(t.block_types || [])];
        fields.push(field(q.label, selectInput(names, val || '', set, key, (o) => o || '(enter the values)'), '', q.help));
      } else {
        const kind = NUMERIC_KINDS.has(q.kind) ? q.kind : 'number';
        fields.push(field(q.label, numberInput(kind, Number(val) || 0, set, key), unitLabel(kind), q.help));
      }
    }
    const governs = opts.governing && opts.governing.startsWith(t.label);
    return h('div', { class: `scenario-card ${sc.enabled === false ? 'off' : ''} ${governs ? 'governs' : ''}`, 'data-label': t.label },
      h('div', { class: 'sc-head' }, typeSel,
        h('label', { class: 'sc-on', title: 'Include this scenario' }, h('input', {
          type: 'checkbox', checked: sc.enabled !== false, 'data-key': `${prefix}-${i}-on`,
          onchange: (e) => update(i, 'enabled', e.target.checked),
        }), ' on'),
        h('button', { class: 'btn small ghost', title: 'Remove this scenario', onclick: () => setList(list.filter((_, j) => j !== i)) }, '✕')),
      h('div', { class: 'sc-desc' }, t.description, h('span', { class: 'sc-gov' }, governs ? GOVERNS : '')),
      fromBlock ? h('div', { class: 'sc-desc' }, `Values are taken from ${fromBlock} on the drawing when solving.`) : null,
      ...fields);
  });
  const add = h('select', { 'data-key': `${prefix}-add` }, h('option', { value: '' }, 'Add a relief scenario…'),
    ...Object.entries(cat).map(([k, t]) => h('option', { value: k }, t.label)));
  add.addEventListener('change', () => { if (add.value) setList([...list, scenarioDefaults(add.value)]); });
  return h('div', { class: 'scenarios' }, ...cards, h('div', { class: 'field wide' }, add),
    list.length ? null : h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11px' } },
      'Add each way the equipment could be overpressured (API 521). Every scenario is sized; the one needing the largest orifice governs.'));
}
