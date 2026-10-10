// Case study: vary one setting over a range and record stream properties or results.

import { store } from './store.js';
import { post } from './api.js';
import { h, modal, toast, download } from './dom.js';
import { fromUser, toUser, unitLabel, inputValue, fmt, NUMERIC_KINDS } from './units.js';
import { lineChart } from './charts.js';

export function openCaseStudy() {
  const candidates = store.doc.blocks.filter((b) => !['relief_valve', 'adjust'].includes(b.type));
  if (!candidates.length) { toast('Draw a flowsheet first.', 'err'); return; }
  const streamNames = Object.keys(store.results?.streams || {}).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const props = store.catalog.stream_properties;

  const bSel = h('select', {}, ...candidates.map((b) => h('option', { value: b.name }, b.name)));
  const pSel = h('select');
  const from = h('input', { type: 'text', style: { width: '90px' } });
  const to = h('input', { type: 'text', style: { width: '90px' } });
  const steps = h('input', { type: 'text', value: '6', style: { width: '60px' } });
  const unitEl = h('span', { class: 'unit' });

  const paramDefs = (bn) => {
    const b = store.doc.blocks.find((x) => x.name === bn);
    return store.types[b.type].params.filter((p) => NUMERIC_KINDS.has(p.kind) && typeof b.params[p.key] === 'number');
  };
  const refreshParams = () => {
    const defs = paramDefs(bSel.value);
    pSel.innerHTML = '';
    for (const p of defs) pSel.append(h('option', { value: p.key }, p.label));
    refreshRange();
  };
  const refreshRange = () => {
    const def = paramDefs(bSel.value).find((p) => p.key === pSel.value);
    if (!def) return;
    const b = store.doc.blocks.find((x) => x.name === bSel.value);
    const v = b.params[def.key];
    from.value = inputValue(def.kind, v * 0.8);
    to.value = inputValue(def.kind, v * 1.2);
    unitEl.textContent = unitLabel(def.kind);
  };
  bSel.addEventListener('change', refreshParams);
  pSel.addEventListener('change', refreshRange);

  const outputs = h('div');
  const addOutput = (preset = {}) => {
    if (outputs.children.length >= 4) return;
    const typeSel = h('select', {}, h('option', {}, 'Stream property'), h('option', {}, 'Equipment result'));
    const objSel = h('select');
    const propSel = h('select');
    const refresh = () => {
      objSel.innerHTML = '';
      propSel.innerHTML = '';
      if (typeSel.value === 'Stream property') {
        for (const s of streamNames) objSel.append(h('option', { value: s }, s));
        for (const p of Object.keys(props)) propSel.append(h('option', { value: p }, p));
      } else {
        for (const b of store.doc.blocks) objSel.append(h('option', { value: b.name }, b.name));
        refreshResults();
      }
    };
    const refreshResults = () => {
      if (typeSel.value !== 'Equipment result') return;
      propSel.innerHTML = '';
      for (const r of store.results?.blocks?.[objSel.value]?.results || []) {
        if (typeof r.value === 'number') propSel.append(h('option', { value: r.key }, r.label));
      }
    };
    typeSel.addEventListener('change', refresh);
    objSel.addEventListener('change', refreshResults);
    if (preset.type) typeSel.value = preset.type;
    refresh();
    if (preset.object) objSel.value = preset.object;
    refreshResults();
    const row = h('div', { class: 'actions', style: { margin: '4px 0' } }, typeSel, objSel, propSel,
      h('button', { class: 'btn small ghost', onclick: () => row.remove() }, '✕'));
    row.read = () => ({ type: typeSel.value, object: objSel.value, property: propSel.value, label: `${objSel.value} — ${propSel.selectedOptions[0]?.textContent || ''}` });
    outputs.append(row);
  };
  refreshParams();
  addOutput({ type: 'Stream property', object: streamNames[streamNames.length - 1] });

  const resultBox = h('div');
  const content = h('div', {},
    h('div', { class: 'group-title' }, 'Vary'),
    h('div', { class: 'actions' }, bSel, pSel, 'from', from, 'to', to, unitEl, 'in', steps, 'steps'),
    h('div', { class: 'group-title' }, 'Record'),
    outputs,
    h('button', { class: 'btn small', onclick: () => addOutput() }, '＋ Add another result'),
    resultBox);

  const run = async () => {
    const def = paramDefs(bSel.value).find((p) => p.key === pSel.value);
    const outs = [...outputs.children].map((r) => r.read()).filter((o) => o.object && o.property);
    if (!def || !outs.length) { toast('Choose a setting to vary and at least one result.', 'err'); return false; }
    const a = Number(from.value);
    const b = Number(to.value);
    const n = parseInt(steps.value, 10);
    if (!Number.isFinite(a) || !Number.isFinite(b) || !(n >= 2)) { toast('Check the range and number of steps.', 'err'); return false; }
    resultBox.innerHTML = '<p>Calculating…</p>';
    try {
      const res = await post('/api/case-study', {
        flowsheet: store.doc, block: bSel.value, param: def.key, start: fromUser(def.kind, a), end: fromUser(def.kind, b),
        steps: n, outputs: outs.map(({ type, object, property }) => ({ type, object, property })),
      });
      showResults(resultBox, def, outs, res.rows, bSel.value);
    } catch (err) { resultBox.innerHTML = ''; toast(err.message, 'err'); }
    return false;
  };
  modal('Case study', content, [{ label: 'Close' }, { label: 'Run', primary: true, onClick: () => { run(); return false; } }]);
}

function outputKind(o) {
  if (o.type === 'Stream property') return store.catalog.stream_properties[o.property] || 'number';
  const r = (store.results?.blocks?.[o.object]?.results || []).find((x) => x.key === o.property);
  return r ? r.kind : 'number';
}

function showResults(box, def, outs, rows, blockName) {
  box.innerHTML = '';
  const kinds = outs.map(outputKind);
  const xLabel = `${blockName} — ${def.label} (${unitLabel(def.kind)})`;
  const head = [xLabel, ...outs.map((o, i) => `${o.label}${unitLabel(kinds[i]) ? ` (${unitLabel(kinds[i])})` : ''}`)];
  const table = h('table', { class: 'mini-table' }, h('thead', {}, h('tr', {}, ...head.map((c) => h('th', {}, c)))),
    h('tbody', {}, ...rows.map((r) => h('tr', {}, h('td', { class: 'num' }, fmt(toUser(def.kind, r.value), 5)),
      ...r.outputs.map((v, i) => h('td', { class: 'num', title: r.error || '' }, v === null ? (r.error ? 'failed' : '—') : fmt(toUser(kinds[i], v), 5)))))));
  box.append(h('div', { class: 'group-title' }, 'Results'), table);
  outs.forEach((o, i) => {
    const chart = {
      x: def.label, y: o.label, x_kind: def.kind, y_kind: kinds[i],
      series: { [o.label]: rows.filter((r) => r.outputs[i] !== null).map((r) => [r.value, r.outputs[i]]) },
    };
    box.append(h('div', { html: lineChart(chart, { width: 600, height: 240, title: o.label }) }));
  });
  const csv = [head.join(','), ...rows.map((r) => [toUser(def.kind, r.value), ...r.outputs.map((v, i) => (v === null ? '' : toUser(kinds[i], v)))].join(','))].join('\n');
  box.append(h('button', { class: 'btn small', onclick: () => download('case-study.csv', csv, 'text/csv') }, 'Download CSV'));
}
