// Stand-alone relief valve sizing page.

import { store } from './store.js';
import { post } from './api.js';
import { h, download, debounce } from './dom.js';
import { show, fmt, fromUser, unitLabel, inputValue, onUnitsChange, describeState, gaugeUnit } from './units.js';
import { stepsView } from './report.js';
import { lineChart } from './charts.js';
import { scenarioEditor, scenarioDefaults, markGoverning } from './scenarios.js';

const page = () => document.getElementById('page-relief');

const state = {
  fluid: 'saturated_steam',
  flow_kg_h: 10000,
  set_pressure_kpag: 1000,
  overpressure_basis: 'single',
  custom_overpressure_percent: 10,
  temperature_c: 300,
  water_temperature_c: 60,
  dryness: 0.95,
  back_pressure_kpag: 0,
  valve_type: 'conventional',
  rupture_disk: false,
  kd: null, kb: null, kw: null, ksh: null, kc: null,
  tag: '', service: '',
  rate_mode: 'enter', // or 'scenarios'
  scenarios: [],
  inlet_on: false, inlet: { nps: '4', schedule: '40', length: 1.0, elevation: 0, fittings: { entrance_sharp: 1 } },
  outlet_on: false, outlet: { nps: '6', schedule: '40', length: 6.0, elevation: 0, fittings: { elbow_90_lr: 1, exit: 1 } },
  outlet_to: 'atmosphere', superimposed_kpag: 0,
};
let resultTab = 'steps';
let last = null;
let form;
let out;

export function initReliefPage() {
  const root = page();
  root.innerHTML = '';
  form = h('div', { class: 'card' });
  out = h('div');
  root.append(h('div', { class: 'page-scroll' }, h('div', { class: 'page-inner' },
    h('h1', {}, 'Relief valve sizing'),
    h('p', { class: 'lead' }, 'Preliminary sizing to API 520 Part I with API 526 standard orifices, for steam and water. Work out the relieving rate from API 521 scenarios (fire, control valve failure, blocked outlet, tube rupture, ...), and check the inlet line (3 % rule), the built-up back pressure and the reaction force. Every step is shown. To size a valve from a stream in your drawing, add a relief valve on the line in the P&ID designer.'),
    h('div', { class: 'two-col' }, form, out))));
  onUnitsChange(() => { if (!page().hidden) { buildForm(); calc(); } });
  buildForm();
  calc();
}

const calc = debounce(async () => {
  const r = store.catalog.relief;
  const body = {
    fluid: state.fluid, flow_kg_h: state.flow_kg_h, set_pressure_kpag: state.set_pressure_kpag,
    overpressure_basis: state.overpressure_basis, back_pressure_kpag: state.back_pressure_kpag,
    valve_type: state.valve_type, rupture_disk: state.rupture_disk, tag: state.tag, service: state.service,
  };
  if (state.overpressure_basis === 'custom') body.custom_overpressure_percent = state.custom_overpressure_percent;
  if (state.fluid === 'superheated_steam') body.temperature_c = state.temperature_c;
  if (state.fluid === 'water') body.temperature_c = state.water_temperature_c;
  if (state.fluid === 'wet_steam') body.dryness = state.dryness;
  for (const k of ['kd', 'kb', 'kw', 'ksh', 'kc']) if (state[k] !== null) body[k] = state[k];
  if (!r) return;
  const system = state.rate_mode === 'scenarios' || state.inlet_on || state.outlet_on;
  try {
    if (system) {
      if (state.rate_mode === 'scenarios' && !state.scenarios.length) {
        last = null;
        out.innerHTML = '';
        out.append(h('div', { class: 'msg info' }, 'Add at least one relief scenario.'));
        return;
      }
      last = await post('/api/relief-system', {
        valve: body,
        scenarios: state.rate_mode === 'scenarios' ? state.scenarios : null,
        inlet: state.inlet_on ? state.inlet : null,
        outlet: state.outlet_on ? state.outlet : null,
        outlet_to: state.outlet_to,
        superimposed_kpag: state.superimposed_kpag,
      });
      last.system = true;
    } else {
      last = await post('/api/relief', body);
    }
    renderResult();
  } catch (err) {
    last = null;
    out.innerHTML = '';
    out.append(h('div', { class: 'msg err' }, err.message));
  }
}, 200);

function numField(label, kind, key, help = '', opts = {}, unitText = null) {
  const input = h('input', { type: 'text', inputmode: 'decimal', value: inputValue(kind, state[key], opts) });
  input.addEventListener('change', () => {
    const v = Number(input.value.replace(/,/g, ''));
    if (!Number.isFinite(v)) { input.classList.add('invalid'); return; }
    input.classList.remove('invalid');
    state[key] = fromUser(kind, v, opts);
    calc();
  });
  return h('div', { class: 'field' }, h('label', {}, label, help ? h('span', { class: 'help' }, help) : null),
    h('div', { class: 'ctl' }, input, h('span', { class: 'unit' }, unitText || unitLabel(kind, opts))));
}

function segField(label, options, key, after = () => {}) {
  return h('div', { class: 'field wide' }, h('label', {}, label), h('div', { class: 'seg' },
    ...Object.entries(options).map(([k, l]) => h('button', {
      type: 'button', class: state[key] === k ? 'active' : '',
      onclick: () => { state[key] = k; after(); buildForm(); calc(); },
    }, l))));
}

function optionalCoeff(label, key, def) {
  const on = state[key] !== null;
  const cb = h('input', { type: 'checkbox', checked: on });
  const input = h('input', { type: 'text', value: on ? String(state[key]) : String(def), disabled: !on, style: { width: '80px' } });
  cb.addEventListener('change', () => { state[key] = cb.checked ? Number(input.value) : null; buildForm(); calc(); });
  input.addEventListener('change', () => { const v = Number(input.value); if (Number.isFinite(v)) { state[key] = v; calc(); } });
  return h('div', { class: 'field' }, h('label', {}, cb, ' ', label), h('div', { class: 'ctl' }, input));
}

function buildForm() {
  const r = store.catalog.relief;
  form.innerHTML = '';
  appendAll(form,
    h('h2', {}, '1 · What is being relieved?'),
    segField('Fluid at the valve inlet', r.fluids, 'fluid'),
    state.fluid === 'superheated_steam' ? numField('Relieving temperature', 'temperature', 'temperature_c') : null,
    state.fluid === 'water' ? numField('Water temperature', 'temperature', 'water_temperature_c', 'If hot enough to flash, two-phase flow is used automatically.') : null,
    state.fluid === 'wet_steam' ? numField('Dryness fraction', 'fraction', 'dryness', '0 = water, 1 = dry steam') : null,
    h('h2', {}, '2 · Required relieving rate'),
    segField('Relieving rate', { enter: 'Enter the rate', scenarios: 'Work it out (API 521 scenarios)' }, 'rate_mode', () => {
      if (state.rate_mode === 'scenarios' && !state.scenarios.length) state.scenarios = [scenarioDefaults('fire')];
    }),
    state.rate_mode === 'enter'
      ? numField('Relieving rate', 'mass_flow', 'flow_kg_h_internal', 'From the governing overpressure scenario (API 521).')
      : scenarioEditor(state.scenarios, (list) => { state.scenarios = list; buildForm(); calc(); },
        { governing: last?.system ? last.governing : null, keyPrefix: 'rsc' }),
    state.rate_mode === 'scenarios' ? h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11.5px' } },
      'Each scenario sets its own relieving fluid (e.g. a fire boils water to saturated steam). The fluid above is not used.') : null,
    h('h2', {}, '3 · Pressures'),
    numField('Set pressure', 'pressure_diff', 'set_pressure_kpag', 'Pressure at which the valve starts to open.', {}, gaugeUnit()),
    state.outlet_on ? null : numField('Total back pressure', 'pressure_diff', 'back_pressure_kpag', '0 for discharge to atmosphere.', {}, gaugeUnit()),
    h('div', { class: 'field wide' }, h('label', {}, 'Allowed overpressure'), (() => {
      const sel = h('select', {}, ...Object.entries(r.overpressure).map(([k, b]) => h('option', { value: k, selected: k === state.overpressure_basis }, b.label)));
      sel.addEventListener('change', () => { state.overpressure_basis = sel.value; buildForm(); calc(); });
      return sel;
    })()),
    state.overpressure_basis === 'custom' ? numField('Custom overpressure', 'percent', 'custom_overpressure_percent') : h('div', { class: 'help', style: { color: 'var(--faint)', fontSize: '11.5px' } }, r.overpressure[state.overpressure_basis].rule),
    h('h2', {}, '4 · Valve'),
    segField('Valve type', r.valve_types, 'valve_type'),
    h('div', { class: 'field wide' }, h('label', {}, (() => {
      const cb = h('input', { type: 'checkbox', checked: state.rupture_disk });
      cb.addEventListener('change', () => { state.rupture_disk = cb.checked; calc(); });
      return cb;
    })(), ' Rupture disk installed upstream of the valve')),
    h('details', {}, h('summary', { style: { cursor: 'pointer', margin: '10px 0 4px', color: 'var(--muted)' } }, 'Advanced: correction factors'),
      optionalCoeff('Effective discharge coefficient Kd', 'kd', state.fluid === 'water' ? 0.65 : 0.975),
      state.valve_type === 'balanced' ? optionalCoeff('Back pressure factor Kb (from the manufacturer)', 'kb', 1.0) : null,
      state.valve_type === 'balanced' && state.fluid === 'water' ? optionalCoeff('Liquid back pressure factor Kw', 'kw', 1.0) : null,
      state.fluid === 'superheated_steam' ? optionalCoeff('Superheat factor KSH (from a code table)', 'ksh', 0.9) : null,
      state.rupture_disk ? optionalCoeff('Combination factor Kc', 'kc', 0.9) : null),
    h('h2', {}, '5 · Inlet and discharge piping (optional)'),
    checkField('Check the inlet line (3 % rule, API 520 Part II)', 'inlet_on'),
    state.inlet_on ? lineFields('inlet') : null,
    checkField('Calculate the built-up back pressure in the discharge line (and the reaction force)', 'outlet_on'),
    state.outlet_on ? segField('Discharges to', { atmosphere: 'Atmosphere', header: 'A header' }, 'outlet_to') : null,
    state.outlet_on && state.outlet_to === 'header'
      ? numField('Header pressure (superimposed back pressure)', 'pressure_diff', 'superimposed_kpag', '', {}, gaugeUnit()) : null,
    state.outlet_on ? lineFields('outlet') : null,
    h('h2', {}, 'Identification (optional)'),
    textField('Valve tag', 'tag'), textField('Service / scenario', 'service'));
}

// mass flow is held in kg/h on this page; the generic field works in kg/s
Object.defineProperty(state, 'flow_kg_h_internal', {
  get() { return state.flow_kg_h / 3600; },
  set(v) { state.flow_kg_h = v * 3600; },
});

function checkField(label, key) {
  const cb = h('input', { type: 'checkbox', checked: state[key], 'data-key': `rf-${key}` });
  cb.addEventListener('change', () => { state[key] = cb.checked; buildForm(); calc(); });
  return h('div', { class: 'field wide' }, h('label', {}, cb, ' ', label));
}

function lineFields(which) {
  const line = state[which];
  // numeric order ("1/2", "3/4", "1", "1-1/4", ...); Object.keys would put the whole-inch sizes first
  const nps = (k) => k.split('-').reduce((a, p) => a + (p.includes('/') ? p.split('/')[0] / p.split('/')[1] : Number(p)), 0);
  const sizes = Object.keys(store.catalog.pipe_sizes).sort((a, b) => nps(a) - nps(b));
  const sel = (opts, key) => {
    const el = h('select', { 'data-key': `rf-${which}-${key}` }, ...opts.map((o) => h('option', { value: o, selected: o === line[key] }, o)));
    el.addEventListener('change', () => { line[key] = el.value; calc(); });
    return el;
  };
  const num = (label, kind, key) => {
    const input = h('input', { type: 'text', inputmode: 'decimal', value: inputValue(kind, line[key]), 'data-key': `rf-${which}-${key}` });
    input.addEventListener('change', () => {
      const v = Number(input.value.replace(/,/g, ''));
      if (!Number.isFinite(v)) { input.classList.add('invalid'); return; }
      line[key] = fromUser(kind, v);
      calc();
    });
    return h('div', { class: 'field' }, h('label', {}, label), h('div', { class: 'ctl' }, input, h('span', { class: 'unit' }, unitLabel(kind))));
  };
  const fits = Object.entries(line.fittings).filter(([, n]) => n);
  const labels = store.catalog.fittings;
  const add = h('select', {}, h('option', { value: '' }, 'Add a fitting…'),
    ...Object.entries(labels).filter(([k]) => !line.fittings[k]).map(([k, l]) => h('option', { value: k }, l)));
  add.addEventListener('change', () => { if (add.value) { line.fittings[add.value] = 1; buildForm(); calc(); } });
  return h('div', { class: 'line-box' },
    h('div', { class: 'field' }, h('label', {}, 'Pipe size'), h('div', { class: 'ctl' }, sel(sizes, 'nps'), h('span', { class: 'unit' }, 'in'), sel(store.catalog.schedules, 'schedule'))),
    num('Length', 'length', 'length'),
    num('Rise (outlet above inlet)', 'length', 'elevation'),
    ...fits.map(([k, n]) => h('div', { class: 'field' }, h('label', {}, labels[k] || k), h('div', { class: 'ctl' }, (() => {
      const input = h('input', { type: 'text', value: String(n), style: { width: '60px' } });
      input.addEventListener('change', () => { const v = Math.max(0, Math.round(Number(input.value) || 0)); if (v) line.fittings[k] = v; else delete line.fittings[k]; buildForm(); calc(); });
      return input;
    })(), h('span', { class: 'unit' }, 'off')))),
    h('div', { class: 'field wide' }, add));
}

function appendAll(el, ...items) { el.append(...items.filter((x) => x !== null && x !== undefined && x !== false)); }

function textField(label, key) {
  const input = h('input', { type: 'text', value: state[key] });
  input.addEventListener('change', () => { state[key] = input.value; calc(); });
  return h('div', { class: 'field' }, h('label', {}, label), h('div', { class: 'ctl' }, input));
}

function renderResult() {
  out.innerHTML = '';
  if (!last) return;
  if (last.system) { renderSystem(); return; }
  const area = (mm2) => show('area', mm2, 4);
  out.append(h('div', { class: 'metrics' },
    metric('Required effective area', area(last.required_area_mm2)),
    metric('API 526 orifice', last.valves_needed > 1 ? `${last.valves_needed} × T` : last.orifice),
    metric('Rated capacity', last.rated_capacity_kg_h ? show('mass_flow', last.rated_capacity_kg_h / 3600, 4) : '—')));
  out.append(h('p', {}, h('strong', {}, describeState(last.relieving_state)),
    ` at a relieving pressure of ${show('pressure', last.relieving_pressure_kpa, 4, { abs: true })} · ${last.flow_regime} · Method: ${last.governing_method}`));
  for (const w of last.warnings) out.append(h('div', { class: 'msg warn' }, w));
  const tabs = [['steps', 'Calculation steps'], ['orifices', 'Orifice table'], ['nozzle', 'Nozzle flow'], ['download', 'Download report']];
  out.append(h('div', { class: 'sub-tabs' }, ...tabs.map(([k, l]) => h('button', {
    class: resultTab === k ? 'active' : '', onclick: () => { resultTab = k; renderResult(); },
  }, l))));
  const card = h('div', { class: 'card' });
  if (resultTab === 'steps') {
    card.append(h('div', { class: 'msg info' }, last.report.disclaimer),
      h('p', { style: { color: 'var(--muted)', fontSize: '12px' } }, 'Shown in SI units (kPa, kg/h, mm²), as in the SI form of the API 520 equations.'),
      stepsView(last.report.steps));
    if (last.report.assumptions.length) card.append(h('h2', {}, 'Assumptions and limitations'), h('ul', {}, ...last.report.assumptions.map((a) => h('li', {}, a))));
    card.append(h('h2', {}, 'References'), h('ol', {}, ...last.report.references.map((a) => h('li', {}, a))));
  } else if (resultTab === 'orifices') {
    const rows = store.catalog.orifices.map(([letter, in2]) => {
      const mm2 = in2 * 645.16;
      const cap = (state.flow_kg_h / 3600) * (mm2 / last.required_area_mm2);
      return h('tr', { style: letter === last.orifice ? { background: 'var(--accent-weak)', fontWeight: '600' } : null },
        h('td', {}, letter), h('td', { class: 'num' }, area(mm2)), h('td', { class: 'num' }, show('mass_flow', cap, 4)),
        h('td', {}, letter === last.orifice ? '◀ selected' : ''));
    });
    card.append(h('table', { class: 'mini-table' }, h('thead', {}, h('tr', {}, h('th', {}, 'Orifice'), h('th', {}, 'Effective area'), h('th', {}, 'Capacity at these conditions'), h('th', {}, ''))), h('tbody', {}, ...rows)),
      h('p', { style: { color: 'var(--muted)', fontSize: '12px' } }, 'Final selection must use the manufacturer\'s actual orifice area and certified coefficient.'));
  } else if (resultTab === 'nozzle') {
    if (last.nozzle) {
      const chart = { x: 'Pressure in the nozzle', y: 'Mass flux (kg/(s·m²))', x_kind: 'pressure', series: { 'Mass flux': last.nozzle.curve } };
      card.append(h('div', { html: lineChart(chart, { width: 640, height: 300, title: 'Ideal mass flux during isentropic expansion' }) }),
        h('p', { style: { color: 'var(--muted)', fontSize: '12px' } },
          `The flow ${last.nozzle.choked ? 'chokes' : 'does not choke'}: the throat pressure is ${show('pressure', last.nozzle.throat_pressure, 4, { abs: true })} and the mass flux ${fmt(last.nozzle.mass_flux, 4)} kg/(s·m²).`));
    } else card.append(h('p', {}, 'No nozzle flow curve for this case.'));
  } else {
    const base = `relief-sizing-${(state.tag || 'valve').replace(/[^A-Za-z0-9-]+/g, '-')}`;
    card.append(h('p', {}, 'Download the full calculation for checking, approval or your records. The HTML file opens in any browser and prints cleanly.'),
      h('div', { class: 'actions' },
        h('button', { class: 'btn primary', onclick: () => download(`${base}.html`, last.html, 'text/html') }, 'Download HTML report'),
        h('button', { class: 'btn', onclick: () => download(`${base}.md`, last.markdown, 'text/markdown') }, 'Download Markdown')));
  }
  out.append(card);
}

function metric(label, value) {
  return h('div', { class: 'metric' }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
}


function renderSystem() {
  const sys = last;
  const g = sys.relief;
  markGoverning(form, sys.governing);
  const govRow = sys.scenarios.find((r) => r.governs);
  out.append(h('div', { class: 'metrics' },
    metric('Governing scenario', sys.governing || '—'),
    metric('API 526 orifice', sys.valves_needed > 1 ? `${sys.valves_needed} × ${sys.orifice}` : (sys.orifice || '—')),
    metric('Required effective area', g ? show('area', g.required_area_mm2, 4) : '—')));
  const extra = [];
  if (govRow?.inlet) extra.push(metric('Inlet pressure loss', `${fmt(govRow.inlet.percent, 3)} % of set ${govRow.inlet.ok ? '✓' : '✗'}`));
  if (govRow?.discharge) extra.push(metric('Built-up back pressure', `${show('pressure_diff', govRow.discharge.built_up, 3)}${govRow.discharge.choked ? ' (choked exit)' : ''}`));
  if (sys.reaction) extra.push(metric('Reaction force (steady)', show('force', Math.max(sys.reaction.force_n, sys.reaction.api_force_n || 0) / 1000, 3)));
  if (extra.length) out.append(h('div', { class: 'metrics' }, ...extra));
  for (const w of sys.warnings) out.append(h('div', { class: 'msg warn' }, w));
  const rows = sys.scenarios.map((r) => h('tr', { style: r.governs ? { background: 'var(--accent-weak)', fontWeight: '600' } : null },
    h('td', {}, r.title), h('td', {}, r.applies ? r.fluid_text : '—'),
    h('td', { class: 'num' }, r.applies ? show('mass_flow', r.rate_kg_h / 3600, 4) : '—'),
    h('td', { class: 'num' }, r.area_mm2 ? show('area', r.area_mm2, 4) : (r.error || r.note || 'not needed')),
    h('td', { class: 'num' }, r.rated_kg_h ? show('mass_flow', r.rated_kg_h / 3600, 4) : '—'),
    h('td', { class: 'num' }, r.inlet ? `${fmt(r.inlet.percent, 3)} %` : '—'),
    h('td', { class: 'num' }, r.discharge ? show('pressure_diff', r.discharge.built_up, 3) : '—')));
  out.append(h('div', { class: 'card' }, h('table', { class: 'mini-table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Scenario'), h('th', {}, 'Relieving fluid'), h('th', {}, 'Rate'), h('th', {}, 'Area needed'),
      h('th', {}, 'Rated flow'), h('th', {}, 'Inlet loss'), h('th', {}, 'Built-up BP'))),
    h('tbody', {}, ...rows))));
  const tabs = [['steps', 'Calculation steps'], ['download', 'Download report']];
  if (!['steps', 'download'].includes(resultTab)) resultTab = 'steps';
  out.append(h('div', { class: 'sub-tabs' }, ...tabs.map(([k, l]) => h('button', {
    class: resultTab === k ? 'active' : '', onclick: () => { resultTab = k; renderResult(); },
  }, l))));
  const card = h('div', { class: 'card' });
  if (resultTab === 'steps') card.append(stepsView(sys.report.steps));
  else {
    const base = `relief-system-${(state.tag || 'valve').replace(/[^A-Za-z0-9-]+/g, '-')}`;
    card.append(h('div', { class: 'actions' },
      h('button', { class: 'btn primary', onclick: () => download(`${base}.html`, sys.html, 'text/html') }, 'Download HTML report'),
      h('button', { class: 'btn', onclick: () => download(`${base}.md`, sys.markdown, 'text/markdown') }, 'Download Markdown')));
  }
  out.append(card);
}
