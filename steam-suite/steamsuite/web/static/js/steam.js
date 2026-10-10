// Steam tables page.

import { get, post } from './api.js';
import { h, debounce } from './dom.js';
import { show, fmt, fromUser, unitLabel, inputValue, onUnitsChange, describeState } from './units.js';
import { lineChart } from './charts.js';

const MODES = {
  PT: 'Pressure and temperature',
  Px: 'Pressure and dryness fraction',
  Tx: 'Temperature and dryness fraction',
  Ph: 'Pressure and enthalpy',
  Ps: 'Pressure and entropy',
  satP: 'Saturation at a pressure',
  satT: 'Saturation at a temperature',
};
const NEEDS = { PT: ['P', 'T'], Px: ['P', 'x'], Tx: ['T', 'x'], Ph: ['P', 'h'], Ps: ['P', 's'], satP: ['P'], satT: ['T'] };
const KIND = { P: 'pressure', T: 'temperature', x: 'fraction', h: 'enthalpy', s: 'entropy' };
const LABEL = { P: 'Pressure', T: 'Temperature', x: 'Dryness fraction (0 = water, 1 = dry steam)', h: 'Specific enthalpy', s: 'Specific entropy' };

const vals = { P: 1101.325, T: 250, x: 1, h: 2000, s: 6.5 };
let mode = 'PT';
let dome = null;
let form;
let out;

export async function initSteamPage() {
  const root = document.getElementById('page-steam');
  form = h('div', { class: 'card' });
  out = h('div');
  root.append(h('div', { class: 'page-scroll' }, h('div', { class: 'page-inner' },
    h('h1', {}, 'Steam tables'),
    h('p', { class: 'lead' }, 'Properties of water and steam from IAPWS-IF97. Choose what you know and enter the values.'),
    h('div', { class: 'two-col' }, form, out))));
  onUnitsChange(() => { buildForm(); calc(); });
  buildForm();
  try { dome = (await get('/api/dome')).points; } catch (e) { dome = []; }
  calc();
}

function buildForm() {
  form.innerHTML = '';
  form.append(h('h2', {}, 'What do you know?'), h('div', { class: 'seg', style: { marginBottom: '10px' } },
    ...Object.entries(MODES).map(([k, l]) => h('button', {
      type: 'button', class: mode === k ? 'active' : '', onclick: () => { mode = k; buildForm(); calc(); },
    }, l))));
  for (const v of NEEDS[mode]) {
    const kind = KIND[v];
    const input = h('input', { type: 'text', inputmode: 'decimal', value: inputValue(kind, vals[v]), 'aria-label': LABEL[v] });
    input.addEventListener('change', () => {
      const num = Number(input.value.replace(/,/g, ''));
      if (!Number.isFinite(num)) { input.classList.add('invalid'); return; }
      input.classList.remove('invalid');
      vals[v] = fromUser(kind, num);
      calc();
    });
    form.append(h('div', { class: 'field' }, h('label', {}, LABEL[v]), h('div', { class: 'ctl' }, input, h('span', { class: 'unit' }, unitLabel(kind)))));
  }
}

const calc = debounce(async () => {
  const body = { mode };
  for (const v of NEEDS[mode]) body[v] = vals[v];
  try {
    const res = await post('/api/properties', body);
    render(res);
  } catch (err) {
    out.innerHTML = '';
    out.append(h('div', { class: 'msg err' }, err.message));
  }
}, 150);

function rowsFor(st) {
  const rows = [
    ['Condition', describeState(st)],
    ['Pressure', `${show('pressure', st.P, 6)} (${show('pressure', st.P, 6, { abs: true })})`],
    ['Temperature', show('temperature', st.T, 6)],
    ['Specific enthalpy', show('enthalpy', st.h, 6)],
    ['Specific entropy', show('entropy', st.s, 6)],
    ['Density', show('density', st.rho, 6)],
  ];
  if (st.x !== null && st.x !== undefined) rows.push(['Dryness fraction', fmt(st.x, 6)]);
  if (st.T_sat !== null && st.T_sat !== undefined) rows.push(['Boiling point at this pressure', show('temperature', st.T_sat, 6)]);
  if (st.superheat !== null && st.superheat !== undefined) rows.push(['Superheat', show('temperature_diff', st.superheat, 4)]);
  if (st.subcooling !== null && st.subcooling !== undefined) rows.push(['Subcooling', show('temperature_diff', st.subcooling, 4)]);
  if (st.cp) rows.push(['Specific heat cp', show('entropy', st.cp, 5)]);
  if (st.mu) rows.push(['Viscosity', `${fmt(st.mu * 1000, 5)} cP`]);
  if (st.k) rows.push(['Thermal conductivity', `${fmt(st.k, 5)} W/(m·K)`]);
  if (st.w) rows.push(['Speed of sound', show('velocity', st.w, 5)]);
  return rows;
}

function tsChart(points) {
  const series = {};
  if (dome?.length) {
    series['Saturation line'] = [...dome.map((p) => [p.s_f, p.T]), ...dome.slice().reverse().map((p) => [p.s_g, p.T])];
  }
  points.forEach(([label, st]) => { series[label] = [[st.s, st.T]]; });
  return lineChart({ x: 'Specific entropy', y: 'Temperature', x_kind: 'entropy', y_kind: 'temperature', series }, { width: 520, height: 320, title: 'Temperature–entropy diagram' });
}

function render(res) {
  out.innerHTML = '';
  if (res.state) {
    const st = res.state;
    out.append(h('div', { class: 'msg ok', style: { fontSize: '14px' } }, h('strong', {}, describeState(st))),
      h('div', { class: 'metrics' },
        metric('Temperature', show('temperature', st.T, 5)), metric('Enthalpy', show('enthalpy', st.h, 5)),
        metric(st.x !== null && st.x !== undefined ? 'Dryness fraction' : 'Density', st.x !== null && st.x !== undefined ? fmt(st.x, 4) : show('density', st.rho, 5))),
      h('div', { class: 'card' }, h('table', { class: 'kv' }, h('tbody', {}, ...rowsFor(st).map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v)))))),
      h('div', { class: 'card', style: { marginTop: '12px' }, html: tsChart([['State', st]]) }));
  } else {
    const l = res.liquid;
    const v = res.vapour;
    out.append(h('div', { class: 'msg ok', style: { fontSize: '14px' } },
      `Boiling point ${show('temperature', l.T, 6)} at ${show('pressure', l.P, 6)} (${show('pressure', l.P, 6, { abs: true })})`));
    const row = (label, kind, a, b, diff = true) => h('tr', {}, h('td', {}, label), h('td', { class: 'num' }, show(kind, a, 6)),
      h('td', { class: 'num' }, show(kind, b, 6)), h('td', { class: 'num' }, diff ? show(kind, b - a, 6) : ''));
    out.append(h('div', { class: 'card' }, h('table', { class: 'mini-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Property'), h('th', {}, 'Saturated water'), h('th', {}, 'Saturated steam'), h('th', {}, 'Evaporation (latent)'))),
      h('tbody', {},
        row('Specific enthalpy', 'enthalpy', l.h, v.h), row('Specific entropy', 'entropy', l.s, v.s),
        row('Density', 'density', l.rho, v.rho, false), row('Specific heat cp', 'entropy', l.cp, v.cp, false))),
      h('p', { style: { color: 'var(--muted)', fontSize: '12px' } }, 'The latent heat of evaporation is the enthalpy difference between saturated steam and saturated water.')),
    h('div', { class: 'card', style: { marginTop: '12px' }, html: tsChart([['Saturated water', l], ['Saturated steam', v]]) }));
  }
}

function metric(label, value) {
  return h('div', { class: 'metric' }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
}
