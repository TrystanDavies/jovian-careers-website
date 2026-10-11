// The properties panel on the right: settings, results and calculation steps of the
// selected unit or stream, or a summary of the flowsheet.

import { store, on, change, block, streams, select, renameBlock, renameStream } from './store.js';
import { h, toast } from './dom.js';
import { show, fmt, toUser, fromUser, unitLabel, inputValue, describeState, NUMERIC_KINDS } from './units.js';
import { stepsView } from './report.js';
import { lineChart } from './charts.js';
import { scenarioEditor } from './scenarios.js';
import {
  insertOnStream, addReliefOnStream, deleteSelection, rotateSelection, flipSelection, duplicate,
} from './canvas.js';

const root = document.getElementById('inspector');
let tab = 'design';
let lastTarget = '';

export function initInspector() {
  on((what) => {
    if (what.selection || what.doc || what.results || what.units || what.solving !== undefined) render();
    if (what.focusInspector) { tab = 'design'; render(); root.scrollTop = 0; }
  });
  render();
}

function render() {
  const active = document.activeElement;
  const focusKey = active && root.contains(active) ? active.dataset.key : null;
  const scroll = root.scrollTop;
  const nodes = [...store.selection.nodes];
  const strm = [...store.selection.streams];
  const target = nodes.length === 1 && !strm.length ? `n:${nodes[0]}` : strm.length === 1 && !nodes.length ? `s:${strm[0]}` : nodes.length + strm.length ? 'multi' : 'doc';
  if (target !== lastTarget) { tab = 'design'; lastTarget = target; }
  root.innerHTML = '';
  if (target.startsWith('n:')) root.append(...blockPanel(nodes[0]));
  else if (target.startsWith('s:')) root.append(...streamPanel(strm[0]));
  else if (target === 'multi') root.append(...multiPanel(nodes, strm));
  else root.append(...docPanel());
  if (target === lastTarget) root.scrollTop = scroll;
  if (focusKey) {
    const el = root.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
    if (el) el.focus();
  }
}

// --- helpers ------------------------------------------------------------------------------------

function header(kind, nameValue, onRename, desc, tabs) {
  const input = h('input', { type: 'text', value: nameValue, 'data-key': '__name', 'aria-label': 'Name' });
  input.addEventListener('change', () => onRename(input.value.trim()));
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  const head = h('div', { class: 'insp-head' },
    h('div', { class: 'kind' }, kind),
    h('div', { class: 'title' }, input),
    desc ? h('div', { class: 'desc' }, desc) : null);
  if (tabs) {
    head.append(h('div', { class: 'insp-tabs' }, ...tabs.map(([key, label]) => h('button', {
      class: tab === key ? 'active' : '', onclick: () => { tab = key; render(); },
    }, label))));
  }
  return head;
}

function numberInput(kind, value, onCommit, key, opts = {}) {
  const input = h('input', { type: 'text', inputmode: 'decimal', value: inputValue(kind, value, opts), 'data-key': key });
  const commit = () => {
    const txt = input.value.trim().replace(/,/g, '');
    if (txt === '' && opts.allowEmpty) { onCommit(null); return; }
    const v = Number(txt);
    if (!Number.isFinite(v)) { input.classList.add('invalid'); toast('Enter a number.', 'err'); return; }
    input.classList.remove('invalid');
    const internal = fromUser(kind, v, opts);
    if (Math.abs(internal - value) < 1e-12 * Math.max(1, Math.abs(value))) return;
    onCommit(internal);
  };
  input.addEventListener('change', commit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  return input;
}

function field(label, control, unit = '', help = '') {
  return h('div', { class: 'field' },
    h('label', {}, label, help ? h('span', { class: 'help' }, help) : null),
    h('div', { class: 'ctl' }, control, unit ? h('span', { class: 'unit' }, unit) : null));
}

function selectInput(options, value, onCommit, key, labels = null) {
  const sel = h('select', { 'data-key': key });
  const opts = options.includes(value) || value === undefined ? options : [value, ...options];
  for (const o of opts) sel.append(h('option', { value: o, selected: o === value }, labels ? labels(o) : o || '(none)'));
  sel.addEventListener('change', () => onCommit(sel.value));
  return sel;
}

function segmented(options, value, onCommit, key) {
  return h('div', { class: 'seg', 'data-key': key }, ...options.map((o) => h('button', {
    class: o === value ? 'active' : '', type: 'button', onclick: () => { if (o !== value) onCommit(o); },
  }, o)));
}

function setParam(name, key, value) {
  change((d) => { d.blocks.find((b) => b.name === name).params[key] = value; });
}

function msg(kind, text) { return h('div', { class: `msg ${kind}` }, text); }

function resultMap(name) {
  const r = store.results?.blocks?.[name];
  return Object.fromEntries((r?.results || []).map((x) => [x.key, x]));
}

function paramKind(blockName, key) {
  const b = block(blockName);
  if (!b) return 'number';
  const p = store.types[b.type].params.find((x) => x.key === key);
  return p ? p.kind : 'number';
}

// --- unit (block) panel -------------------------------------------------------------------------

function blockPanel(name) {
  const b = block(name);
  const t = store.types[b.type];
  const r = store.results?.blocks?.[name];
  const nSteps = r?.steps?.length || 0;
  const tabs = [['design', 'Design'], ['results', 'Results'], ['calc', `Calculation${nSteps ? ` (${nSteps})` : ''}`]];
  const head = header(t.label, name, (nn) => {
    if (!nn || nn === name) return;
    let err = null;
    change((d) => { err = renameBlock(d, name, nn); });
    if (err) toast(err, 'err');
    else select([nn]);
  }, t.description, tabs);
  const body = h('div', { class: 'insp-body' });
  if (r?.error) body.append(msg('err', r.error));
  else if (r?.warnings?.length && tab !== 'results') body.append(msg('warn', `${r.warnings.length} warning(s) — see Results.`));
  if (tab === 'design') body.append(...designTab(b, t));
  else if (tab === 'results') body.append(...resultsTab(b, r));
  else body.append(...calcTab(r));
  return [head, body];
}

function designTab(b, t) {
  const out = [];
  // connections
  if (t.inlets.length || t.outlets.length) {
    out.push(h('div', { class: 'group-title' }, 'Connections'));
    const list = h('div', { class: 'conn-list' });
    for (const [side, defs] of [['inlets', t.inlets], ['outlets', t.outlets]]) {
      for (const pd of defs) {
        const v = b[side][pd.key];
        const names = v === undefined || v === '' ? [] : Array.isArray(v) ? v : [v];
        list.append(h('span', { class: 'k' }, `${pd.label}${pd.optional ? ' (optional)' : ''}`),
          h('span', {}, ...(names.length ? names.map((n) => h('span', { class: 'chip', onclick: () => select([], [n]) }, n))
            : [h('span', { class: 'chip none' }, side === 'inlets' ? 'not connected' : 'none')])));
      }
    }
    out.push(list);
    if (Object.values(b.inlets).flat().length === 0 && t.inlets.length) {
      out.push(msg('info', 'Draw a line from an outlet nozzle to this unit\'s inlet nozzle, or drag out of the inlet nozzle to create a water/steam supply.'));
    }
  }
  // inlet connection type (vessels): throttled or open, used in pressure–flow mode
  const openPorts = t.inlets.filter((p) => p.open_option);
  if (openPorts.length) out.push(...inletSpecs(b, openPorts));
  // outlet flow specifications (splitter, header)
  const specPort = t.outlets.find((p) => p.with_specs);
  if (specPort) out.push(...outletSpecs(b, specPort));
  // settings
  let group = null;
  for (const p of t.params) {
    if (p.show_if) {
      const [ctrl, allowed] = p.show_if;
      if (!allowed.includes(b.params[ctrl])) continue;
    }
    const g = p.group || 'Settings';
    if (g !== group) { out.push(h('div', { class: 'group-title' }, g)); group = g; }
    out.push(paramEditor(b, p));
  }
  out.push(h('div', { class: 'actions' },
    h('button', { class: 'btn small', onclick: () => rotateSelection(90) }, '⟳ Rotate'),
    h('button', { class: 'btn small', onclick: flipSelection }, '⇋ Flip'),
    h('button', { class: 'btn small', onclick: duplicate }, '⧉ Duplicate'),
    h('button', { class: 'btn small danger', onclick: deleteSelection }, '✕ Delete')));
  return out;
}

function outletSpecs(b, port) {
  const names = [].concat(b.outlets[port.key] || []);
  const specs = b.params.outlet_specs || {};
  const rows = names.map((n) => {
    const sp = specs[n] || { mode: 'Remainder', value: 0 };
    const mode = selectInput(store.catalog.flow_modes, sp.mode, (v) => change((d) => {
      const bb = d.blocks.find((x) => x.name === b.name);
      bb.params.outlet_specs ||= {};
      bb.params.outlet_specs[n] = { mode: v, value: v === 'Fraction' ? 50 : v === 'Flow' ? 1 : 0 };
    }), `spec-mode-${n}`);
    let valueCell = h('span', { class: 'unit' }, '—');
    if (sp.mode === 'Flow' || sp.mode === 'Fraction') {
      const kind = sp.mode === 'Flow' ? 'mass_flow' : 'percent';
      valueCell = h('span', { class: 'ctl' }, numberInput(kind, sp.value, (v) => change((d) => {
        d.blocks.find((x) => x.name === b.name).params.outlet_specs[n].value = v;
      }), `spec-val-${n}`), h('span', { class: 'unit' }, unitLabel(kind)));
    }
    return h('tr', {}, h('td', {}, h('span', { class: 'chip', onclick: () => select([], [n]) }, n)), h('td', {}, mode), h('td', {}, valueCell));
  });
  return [
    h('div', { class: 'group-title' }, 'Outlet flows'),
    names.length ? h('table', { class: 'mini-table' }, h('thead', {}, h('tr', {}, h('th', {}, 'Stream'), h('th', {}, 'Flow'), h('th', {}, 'Value'))), h('tbody', {}, ...rows))
      : msg('info', 'Draw lines from the outlet nozzle to add outlets.'),
    h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11px', margin: '4px 0' } },
      'Flow: fixed · Fraction: % of the total · As required: whatever the connected unit needs · Remainder: what is left · '
      + 'Pressure-driven: found from the hydraulics (pressure–flow mode).'),
  ];
}

function inletSpecs(b, ports) {
  const names = ports.flatMap((pd) => [].concat(b.inlets[pd.key] || []));
  if (!names.length) return [];
  const specs = b.params.inlet_specs || {};
  const pf = store.doc.solver_mode === 'pressure_flow';
  const rows = names.map((n) => h('tr', {},
    h('td', {}, h('span', { class: 'chip', onclick: () => select([], [n]) }, n)),
    h('td', {}, segmented(store.catalog.inlet_modes || ['Throttled', 'Open'], specs[n] || 'Throttled', (v) => change((d) => {
      const bb = d.blocks.find((x) => x.name === b.name);
      bb.params.inlet_specs = { ...(bb.params.inlet_specs || {}), [n]: v };
    }), `inlet-mode-${n}`))));
  return [
    h('div', { class: 'group-title' }, 'Inlet connections'),
    h('table', { class: 'mini-table' }, h('thead', {}, h('tr', {}, h('th', {}, 'Stream'), h('th', {}, 'Connection'))), h('tbody', {}, ...rows)),
    h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11px', margin: '4px 0' } },
      'Throttled: a control valve or trap drops the line to the vessel pressure. Open: the line discharges straight in, so it '
      + 'arrives at the vessel pressure — in pressure–flow mode this sets the back pressure (or the flow) upstream.'
      + (pf ? '' : ' Used in pressure–flow mode.')),
  ];
}

// --- relief scenarios -----------------------------------------------------------------------------

function scenariosEditor(b, p) {
  return scenarioEditor(b.params[p.key] || [], (list) => change((d) => {
    d.blocks.find((x) => x.name === b.name).params[p.key] = list;
  }), {
    blocks: (types) => store.doc.blocks.filter((x) => types.includes(x.type)).map((x) => x.name),
    governing: resultMap(b.name).governing?.value,
  });
}

const DYNAMIC = new Set(['inlet_choice', 'stream_choice', 'block_choice', 'param_choice', 'result_choice']);

function paramEditor(b, p) {
  const val = b.params[p.key];
  const key = `p-${p.key}`;
  const set = (v) => setParam(b.name, p.key, v);
  if (p.kind === 'choice') {
    const short = p.choices.length <= 3 && p.choices.every((c) => c.length <= 16);
    const ctl = short ? segmented(p.choices, val, set, key) : selectInput(p.choices, val, set, key);
    return short ? h('div', { class: 'field wide' }, h('label', {}, p.label), ctl) : field(p.label, ctl, '', p.help);
  }
  if (p.kind === 'text') {
    const input = h('input', { type: 'text', value: val ?? '', 'data-key': key });
    input.addEventListener('change', () => set(input.value));
    return field(p.label, input, '', p.help);
  }
  if (DYNAMIC.has(p.kind)) return field(p.label, dynamicSelect(b, p, val, set, key), '', p.help);
  if (p.kind === 'fittings') return fittingsEditor(b, p);
  if (p.kind === 'scenarios') return scenariosEditor(b, p);
  if (p.kind === 'target_value' || p.kind === 'adjust_bound') {
    let kind = 'number';
    if (p.kind === 'target_value') {
      if (b.params.target_type === 'Stream property') kind = store.catalog.stream_properties[b.params.target_property] || 'number';
      else kind = resultMap(b.params.target_block)[b.params.target_result]?.kind || 'number';
    } else kind = paramKind(b.params.var_block, b.params.var_param);
    if (!NUMERIC_KINDS.has(kind)) kind = 'number';
    return field(p.label, numberInput(kind, val, set, key), unitLabel(kind), p.help);
  }
  // plain number
  const kind = NUMERIC_KINDS.has(p.kind) ? p.kind : 'number';
  const commit = (v) => {
    if (p.min !== null && p.min !== undefined && v < p.min - 1e-12) { toast(`${p.label} must be at least ${show(kind, p.min)}.`, 'err'); render(); return; }
    if (p.max !== null && p.max !== undefined && v > p.max + 1e-12) { toast(`${p.label} must be at most ${show(kind, p.max)}.`, 'err'); render(); return; }
    set(v);
  };
  return field(p.label, numberInput(kind, val, commit, key), unitLabel(kind), p.help);
}

function dynamicSelect(b, p, val, set, key) {
  let options = [];
  let labels = null;
  if (p.kind === 'inlet_choice') {
    options = [].concat(b.inlets[p.inlet_port] || []);
  } else if (p.kind === 'stream_choice') {
    options = Object.keys(streams()).sort((a, c) => a.localeCompare(c, undefined, { numeric: true }));
  } else if (p.kind === 'block_choice') {
    options = store.doc.blocks.filter((x) => x.name !== b.name && !['adjust', 'relief_valve', 'specification'].includes(x.type)).map((x) => x.name);
  } else if (p.kind === 'param_choice') {
    const other = block(b.params[p.depends_on]);
    if (other) {
      const defs = store.types[other.type].params.filter((x) => NUMERIC_KINDS.has(x.kind));
      options = defs.map((x) => x.key);
      const map = Object.fromEntries(defs.map((x) => [x.key, x.label]));
      labels = (o) => map[o] || o || '(none)';
    }
  } else if (p.kind === 'result_choice') {
    const res = store.results?.blocks?.[b.params[p.depends_on]]?.results || [];
    const nums = res.filter((x) => typeof x.value === 'number');
    options = nums.map((x) => x.key);
    const map = Object.fromEntries(nums.map((x) => [x.key, x.label]));
    labels = (o) => map[o] || o || '(none)';
  }
  options = ['', ...options.filter((o) => o)];
  return selectInput(options, val || '', set, key, labels || ((o) => o || '(none)'));
}

function fittingsEditor(b, p) {
  const fits = { ...(b.params[p.key] || {}) };
  const labels = store.catalog.fittings;
  const rows = Object.entries(fits).filter(([, n]) => n).map(([k, n]) => h('tr', {},
    h('td', {}, labels[k] || k),
    h('td', { style: { width: '70px' } }, numberInput('number', n, (v) => change((d) => {
      const bb = d.blocks.find((x) => x.name === b.name);
      bb.params[p.key] = { ...(bb.params[p.key] || {}), [k]: Math.max(0, Math.round(v)) };
    }), `fit-${k}`)),
    h('td', { style: { width: '26px' } }, h('button', { class: 'btn small ghost', title: 'Remove', onclick: () => change((d) => {
      const bb = d.blocks.find((x) => x.name === b.name);
      const f = { ...(bb.params[p.key] || {}) };
      delete f[k];
      bb.params[p.key] = f;
    }) }, '✕'))));
  const add = h('select', { 'data-key': 'fit-add' }, h('option', { value: '' }, 'Add a fitting or valve…'),
    ...Object.entries(labels).filter(([k]) => !fits[k]).map(([k, l]) => h('option', { value: k }, l)));
  add.addEventListener('change', () => {
    if (!add.value) return;
    const k = add.value;
    change((d) => {
      const bb = d.blocks.find((x) => x.name === b.name);
      bb.params[p.key] = { ...(bb.params[p.key] || {}), [k]: 1 };
    });
  });
  return h('div', {},
    rows.length ? h('table', { class: 'mini-table' }, h('thead', {}, h('tr', {}, h('th', {}, 'Fitting'), h('th', {}, 'Number'), h('th', {}, ''))), h('tbody', {}, ...rows)) : null,
    h('div', { class: 'field wide' }, add));
}

function resultsTab(b, r) {
  const out = [];
  if (!r) { out.push(msg('info', store.solving ? 'Calculating…' : 'No results yet.')); return out; }
  for (const w of r.warnings || []) out.push(msg('warn', w));
  if (r.results?.length) {
    out.push(h('table', { class: 'kv' }, h('tbody', {}, ...r.results.map((x) => h('tr', {},
      h('td', {}, x.label), h('td', {}, show(x.kind, x.value, 5)))))));
  } else if (!r.error) out.push(msg('info', 'This unit has no results.'));
  for (const [title, chart] of Object.entries(r.charts || {})) {
    out.push(h('div', { class: 'group-title' }, title));
    const div = h('div', { html: lineChart(chart, { width: 340, height: 200 }) });
    out.push(div);
  }
  return out;
}

function calcTab(r) {
  if (!r?.steps?.length) return [msg('info', 'Solve the flowsheet to see the calculation steps.')];
  return [h('div', { class: 'desc', style: { color: 'var(--muted)', fontSize: '12px' } }, 'Equations are shown in SI units: kPa(a), °C, kg/s, kJ/kg, kW.'), stepsView(r.steps)];
}

// --- stream panel ----------------------------------------------------------------------------------

function streamPanel(name) {
  const s = streams()[name];
  const st = store.results?.streams?.[name];
  const head = header('Stream', name, (nn) => {
    if (!nn || nn === name) return;
    let err = null;
    change((d) => { err = renameStream(d, name, nn); });
    if (err) toast(err, 'err');
    else select([], [nn]);
  }, null, null);
  const body = h('div', { class: 'insp-body' });
  body.append(h('div', { class: 'conn-list' },
    h('span', { class: 'k' }, 'From'), h('span', {}, s?.src ? h('span', { class: 'chip', onclick: () => select([s.src.block]) }, s.src.block) : '—'),
    h('span', { class: 'k' }, 'To'), h('span', {}, s?.dst ? h('span', { class: 'chip', onclick: () => select([s.dst.block]) }, s.dst.block) : h('span', { class: 'chip none' }, 'leaves the system'))));
  if (st && st.known) {
    const rows = [
      ['Mass flow', show('mass_flow', st.m, 5)],
      ['Pressure', show('pressure', st.P, 5)],
      ['Temperature', show('temperature', st.T, 5)],
      ['Condition', describeState(st)],
      ['Dryness fraction', st.x === null || st.x === undefined ? '—' : fmt(st.x, 4)],
      ['Specific enthalpy', show('enthalpy', st.h, 5)],
      ['Specific entropy', show('entropy', st.s, 5)],
      ['Density', show('density', st.rho, 5)],
      ['Volumetric flow', show('volume_flow', (st.m / st.rho) * 3600, 4)],
    ];
    if (st.T_sat !== null && st.T_sat !== undefined) rows.push(['Boiling point at this pressure', show('temperature', st.T_sat, 5)]);
    if (st.mu) rows.push(['Viscosity', `${fmt(st.mu * 1000, 4)} cP`]);
    body.append(h('div', { class: 'group-title' }, 'Conditions'),
      h('table', { class: 'kv' }, h('tbody', {}, ...rows.map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v))))));
  } else {
    body.append(msg('info', store.solving ? 'Calculating…' : 'Not calculated yet.'));
  }
  if (s?.src && block(s.src.block)?.type === 'feed') {
    body.append(msg('info', `The conditions of this stream are set by the supply ${s.src.block}.`));
  }
  body.append(h('div', { class: 'group-title' }, 'Add to this line'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn small', onclick: () => insertOnStream(name, 'pipe') }, '＋ Pipe segment'),
      h('button', { class: 'btn small', onclick: () => insertOnStream(name, 'valve') }, '＋ Valve'),
      h('button', { class: 'btn small', onclick: () => insertOnStream(name, 'heater') }, '＋ Heater/cooler'),
      h('button', { class: 'btn small', onclick: () => insertOnStream(name, 'check_valve') }, '＋ Check valve'),
      h('button', { class: 'btn small', onclick: () => addReliefOnStream(name) }, '＋ Relief valve')),
    h('div', { class: 'actions' }, h('button', { class: 'btn small danger', onclick: deleteSelection }, '✕ Delete stream')));
  return [head, body];
}

function multiPanel(nodes, strm) {
  const head = h('div', { class: 'insp-head' }, h('div', { class: 'kind' }, 'Selection'),
    h('div', { class: 'title' }, h('strong', {}, `${nodes.length} unit(s), ${strm.length} stream(s)`)));
  const body = h('div', { class: 'insp-body' },
    h('div', { class: 'actions' },
      h('button', { class: 'btn small', onclick: () => rotateSelection(90) }, '⟳ Rotate'),
      h('button', { class: 'btn small', onclick: flipSelection }, '⇋ Flip'),
      h('button', { class: 'btn small', onclick: duplicate }, '⧉ Duplicate'),
      h('button', { class: 'btn small danger', onclick: deleteSelection }, '✕ Delete')));
  return [head, body];
}

// --- flowsheet panel -------------------------------------------------------------------------------

function docPanel() {
  const d = store.doc;
  const head = header('Flowsheet', d.name, (nn) => { if (nn) change((doc) => { doc.name = nn; }, { solve: false }); }, null, null);
  const body = h('div', { class: 'insp-body' });
  const desc = h('textarea', { rows: 3, style: { width: '100%' }, 'data-key': '__desc', placeholder: 'Description' }, d.description || '');
  desc.addEventListener('change', () => change((doc) => { doc.description = desc.value; }, { solve: false }));
  body.append(desc);
  const res = store.results;
  if (!d.blocks.length) {
    body.append(gettingStarted());
    return [head, body];
  }
  if (res?.summary && Object.keys(res.summary).length) {
    const s = res.summary;
    const kpis = [
      ['Steam generated', s.steam_generated, 'mass_flow'], ['Fuel input', s.fuel, 'power'],
      ['Heat to process', s.process_heat, 'power'], ['Power generated', s.turbine_electric, 'power'],
      ['Pump power', s.pump_electric, 'power'], ['Water/steam supplied', s.supply_flow, 'mass_flow'],
    ].filter(([, v]) => v && Math.abs(v) > 1e-9);
    if (s.cycle_efficiency) kpis.push(['Cycle efficiency', s.cycle_efficiency * 100, 'percent']);
    body.append(h('div', { class: 'group-title' }, 'Key figures'),
      h('div', { class: 'kpis' }, ...kpis.map(([l, v, k]) => h('div', { class: 'kpi' }, h('div', { class: 'l' }, l), h('div', { class: 'v' }, show(k, v, 4))))));
  }
  const pf = d.solver_mode === 'pressure_flow';
  body.append(h('div', { class: 'group-title' }, 'Solver'),
    h('div', { class: 'field wide' }, segmented(['Sequential', 'Pressure–flow'], pf ? 'Pressure–flow' : 'Sequential',
      (v) => change((doc) => { doc.solver_mode = v === 'Pressure–flow' ? 'pressure_flow' : 'sequential'; }), 'doc-solver')),
    h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11px', margin: '2px 0 6px' } }, pf
      ? 'Flows and pressures are solved together from pipes, valves, pump curves and fixed pressures: parallel branches share flow, pumps run on their curves, back pressures are found. Supplies set to "As required" deliver whatever the pressures drive.'
      : 'Flows come from your specifications and from what equipment asks for; pressures are worked out downstream. Switch to pressure–flow to have the hydraulics set the flows.'));
  if (pf && res?.network?.equations) {
    const n = res.network;
    body.append(h('table', { class: 'kv' }, h('tbody', {},
      h('tr', {}, h('td', {}, 'Equations / unknowns'), h('td', {}, `${n.equations} / ${n.unknowns}`)),
      h('tr', {}, h('td', {}, 'Newton iterations'), h('td', {}, String(n.newton_iterations))),
      h('tr', {}, h('td', {}, 'Solution time'), h('td', {}, `${n.time_s} s`)),
      ...(n.notes || []).map((t) => h('tr', {}, h('td', {}, 'Note'), h('td', {}, t))))));
  }
  if (res?.balance && Object.keys(res.balance).length) {
    const b = res.balance;
    body.append(h('div', { class: 'group-title' }, 'Overall balance'), h('table', { class: 'kv' }, h('tbody', {},
      h('tr', {}, h('td', {}, 'Mass in / out'), h('td', {}, `${show('mass_flow', b.mass_in, 5)} / ${show('mass_flow', b.mass_out, 5)}`)),
      h('tr', {}, h('td', {}, 'Mass balance error'), h('td', {}, `${(b.mass_error || 0).toExponential(1)} kg/s`)),
      h('tr', {}, h('td', {}, 'Heat added (net)'), h('td', {}, show('power', b.heat_in, 5))),
      h('tr', {}, h('td', {}, 'Work added (net)'), h('td', {}, show('power', b.work_in, 5))),
      h('tr', {}, h('td', {}, 'Energy balance error'), h('td', {}, `${(b.energy_error || 0).toExponential(1)} kW`)))));
  }
  const errs = res?.structure_error ? [res.structure_error] : res?.errors || [];
  if (errs.length || res?.warnings?.length) {
    body.append(h('div', { class: 'group-title' }, 'Messages'));
    for (const e of errs) body.append(clickableMsg('err', e));
    for (const w of res?.warnings || []) body.append(clickableMsg('warn', w));
  } else if (res && !res.structure_error) {
    body.append(msg('ok', 'Everything balances and there are no warnings.'));
  }
  body.append(h('div', { class: 'group-title' }, 'Tips'), tips());
  return [head, body];
}

function clickableMsg(kind, text) {
  const m = msg(kind, text);
  const name = text.split(':')[0];
  if (block(name)) { m.style.cursor = 'pointer'; m.title = 'Show this unit'; m.addEventListener('click', () => select([name])); }
  return m;
}

function gettingStarted() {
  return h('div', { class: 'empty-state' },
    h('h3', {}, 'Draw your system'),
    h('ol', {},
      h('li', {}, 'Drag equipment from the palette on the left onto the drawing (or click an item, then click the drawing).'),
      h('li', {}, 'Connect it: drag from an outlet nozzle (filled dot) to an inlet nozzle (open dot). Drag out of an inlet into empty space to add a water/steam supply.'),
      h('li', {}, 'Click any unit or line to set it up here. Right-click a line to insert a pipe segment, valve or relief valve.'),
      h('li', {}, 'The heat and mass balance is recalculated automatically after every change.')),
    h('p', {}, 'Or open one of the examples from the toolbar.'));
}

function tips() {
  return h('div', { class: 'empty-state', style: { fontSize: '12px' } },
    h('div', {}, h('span', { class: 'kbd' }, 'Del'), ' delete · ', h('span', { class: 'kbd' }, 'R'), ' rotate · ', h('span', { class: 'kbd' }, 'F'), ' flip · ',
      h('span', { class: 'kbd' }, 'Ctrl+Z'), ' undo · ', h('span', { class: 'kbd' }, 'Ctrl+D'), ' duplicate'),
    h('div', { style: { marginTop: '4px' } }, 'Wheel to zoom, drag with the right or middle mouse button to pan, drag on empty space to select several units. Right-click for more.'));
}
