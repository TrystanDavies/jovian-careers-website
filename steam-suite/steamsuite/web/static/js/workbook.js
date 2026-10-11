// The workbook under the drawing: tables of streams, equipment, piping and relief valves.

import { store, on, streams, select, change } from './store.js';
import { h, toast, download } from './dom.js';
import { post } from './api.js';
import { show, fmt, toUser, unitLabel, describeState } from './units.js';

const wb = document.getElementById('workbook');
const head = document.getElementById('workbook-head');
const body = document.getElementById('workbook-body');
let tab = 'streams';

const TABS = [
  ['streams', 'Streams'],
  ['equipment', 'Equipment'],
  ['piping', 'Piping and valves'],
  ['relief', 'Relief valves'],
  ['compare', 'Compare'],
  ['messages', 'Messages'],
];
let comparison = null; // last /api/compare result

export function initWorkbook() {
  on((what) => { if (what.doc || what.results || what.units || what.selection) render(); });
  // resize by dragging the top edge
  const handle = document.getElementById('workbook-resize');
  handle.addEventListener('pointerdown', (e) => {
    const startY = e.clientY;
    const startH = wb.getBoundingClientRect().height;
    wb.classList.remove('collapsed');
    const move = (ev) => { wb.style.height = `${Math.min(window.innerHeight * 0.7, Math.max(80, startH - (ev.clientY - startY)))}px`; };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
  render();
}

function counts() {
  const res = store.results;
  const blocks = store.doc.blocks;
  return {
    streams: Object.keys(streams()).length,
    equipment: blocks.filter((b) => !['relief_valve', 'adjust'].includes(b.type)).length,
    piping: blocks.filter((b) => ['pipe', 'valve', 'check_valve'].includes(b.type)).length,
    relief: blocks.filter((b) => b.type === 'relief_valve').length,
    compare: comparison ? comparison.rows.length : 0,
    messages: (res?.errors?.length || 0) + (res?.warnings?.length || 0) + (res?.structure_error ? 1 : 0),
  };
}

function render() {
  const c = counts();
  head.innerHTML = '';
  for (const [key, label] of TABS) {
    head.append(h('button', {
      class: `tab ${tab === key ? 'active' : ''}`,
      onclick: () => { tab = key; wb.classList.remove('collapsed'); render(); },
    }, label, h('span', { class: 'count' }, c[key])));
  }
  head.append(h('span', { style: { flex: 1 } }));
  head.append(h('button', {
    class: 'btn small ghost', title: 'Show or hide the workbook',
    onclick: () => { wb.classList.toggle('collapsed'); },
  }, wb.classList.contains('collapsed') ? '▲' : '▼'));
  body.innerHTML = '';
  const fn = { streams: streamsTable, equipment: equipmentTable, piping: pipingTable, relief: reliefTable, compare: compareTab, messages: messagesTable }[tab];
  body.append(fn());
}

function table(cols, rows, onRow, selectedKey) {
  const t = h('table', { class: 'grid-table' },
    h('thead', {}, h('tr', {}, ...cols.map(([label, num]) => h('th', { style: num ? { textAlign: 'right' } : null }, label)))));
  const tb = h('tbody');
  for (const r of rows) {
    const tr = h('tr', { class: r.key && r.key === selectedKey ? 'sel' : '', onclick: () => onRow(r) },
      ...r.cells.map((c, i) => h('td', { class: cols[i][1] ? 'num' : '' }, c)));
    tb.append(tr);
  }
  t.append(tb);
  if (!rows.length) return h('div', { style: { padding: '10px 14px', color: 'var(--muted)' } }, 'Nothing to show yet.');
  return t;
}

const PHASE_COLOR = { steam: 'var(--steam)', wet: 'var(--wet)', water: 'var(--water)' };
function phaseKey(st) {
  if (!st || !st.known) return null;
  if (st.phase === 'two-phase') return 'wet';
  if (['vapour', 'saturated vapour', 'supercritical'].includes(st.phase)) return 'steam';
  return 'water';
}

function num(kind, v, sig = 5) { return v === null || v === undefined ? '—' : fmt(toUser(kind, v), sig); }

function streamsTable() {
  const all = streams();
  const names = Object.keys(all).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const sel = [...store.selection.streams][0];
  const rows = names.map((n) => {
    const s = all[n];
    const st = store.results?.streams?.[n];
    const ok = st && st.known;
    const pk = phaseKey(st);
    return {
      key: n,
      cells: [
        h('span', {}, pk ? h('span', { class: 'phase-dot', style: { background: PHASE_COLOR[pk] } }) : null, n),
        s.src ? s.src.block : '—', s.dst ? s.dst.block : '(leaves)',
        ok ? num('mass_flow', st.m) : '—',
        ok ? num('pressure', st.P) : '—',
        ok ? num('temperature', st.T) : '—',
        ok ? describeState(st) : '—',
        ok && st.x !== null && st.x !== undefined ? fmt(st.x, 4) : '—',
        ok ? num('enthalpy', st.h) : '—',
        ok ? num('density', st.rho, 4) : '—',
      ],
    };
  });
  return table([
    ['Stream'], ['From'], ['To'], [`Flow (${unitLabel('mass_flow')})`, 1], [`Pressure (${unitLabel('pressure')})`, 1],
    [`Temperature (${unitLabel('temperature')})`, 1], ['Condition'], ['Dryness', 1], [`Enthalpy (${unitLabel('enthalpy')})`, 1],
    [`Density (${unitLabel('density')})`, 1],
  ], rows, (r) => select([], [r.key]), sel);
}

function status(name) {
  const r = store.results?.blocks?.[name];
  if (!r) return '—';
  if (r.error) return h('span', { style: { color: 'var(--danger)' } }, 'Error');
  if (r.warnings?.length) return h('span', { style: { color: 'var(--warn)' } }, `${r.warnings.length} warning(s)`);
  return h('span', { style: { color: 'var(--ok)' } }, 'OK');
}

function res(name) {
  const r = store.results?.blocks?.[name];
  return Object.fromEntries((r?.results || []).map((x) => [x.key, x]));
}

const KEY_RESULTS = {
  feed: ['flow', 'temperature'], pump: ['power', 'dP', 'npsha'], compressor: ['power', 'T_out'], turbine: ['electric', 'condition'],
  valve: ['dP', 'cv', 'opening'], boiler: ['steam', 'duty', 'fuel'], heater: ['duty', 'T_out'], condenser: ['duty', 'cw'],
  heat_exchanger: ['duty', 'ua', 'approach'], mixer: ['flow', 'T_out'], splitter: [], header: ['flow', 'T', 'condition'],
  flash: ['flash', 'fraction'], desuperheater: ['spray', 'T_out'], deaerator: ['steam', 'out', 'T_out'],
  steam_user: ['steam', 'duty'], pipe: ['dP', 'v_out', 'q_loss'], relief_valve: ['orifice', 'area', 'governing'], adjust: ['value', 'achieved'],
  sink: ['flow', 'P'], check_valve: ['state', 'dP'], specification: ['target', 'actual'],
};

function equipmentTable() {
  const sel = [...store.selection.nodes][0];
  const rows = store.doc.blocks.map((b) => {
    const r = res(b.name);
    const summary = (KEY_RESULTS[b.type] || []).filter((k) => r[k]).map((k) => `${r[k].label}: ${show(r[k].kind, r[k].value, 4)}`).join(' · ');
    return { key: b.name, cells: [b.name, store.types[b.type]?.label || b.type, summary || '—', status(b.name)] };
  });
  return table([['Name'], ['Type'], ['Key results'], ['Status']], rows, (r) => select([r.key]), sel);
}

function pipingTable() {
  const sel = [...store.selection.nodes][0];
  const rows = [];
  for (const b of store.doc.blocks.filter((x) => x.type === 'pipe')) {
    const r = res(b.name);
    const p = b.params;
    const st = store.results?.streams?.[[].concat(b.inlets.in || [])[0]];
    rows.push({ key: b.name, cells: [
      b.name, 'Pipe',
      p.size_mode === 'Inside diameter' ? `ID ${show('diameter', p.diameter, 3)}` : `${p.nps}" Sch ${p.schedule}`,
      show('length', p.length, 4),
      st?.known ? show('mass_flow', st.m, 4) : '—',
      r.dP ? show('pressure_diff', r.dP.value, 4) : '—',
      r.dp_per_100m ? show('pressure_diff', r.dp_per_100m.value, 3) : '—',
      r.v_in ? `${num('velocity', r.v_in.value, 3)} → ${show('velocity', r.v_out.value, 3)}` : '—',
      r.q_loss ? show('power', r.q_loss.value, 3) : '—',
      status(b.name),
    ] });
  }
  for (const b of store.doc.blocks.filter((x) => x.type === 'valve' || x.type === 'check_valve')) {
    const r = res(b.name);
    const st = store.results?.streams?.[[].concat(b.inlets.in || [])[0]];
    const kind = b.type === 'check_valve' ? 'Check valve' : (b.params.mode || '').startsWith('Free') ? 'Trap / free ΔP' : 'Valve';
    rows.push({ key: b.name, cells: [
      b.name, kind, r.cv ? `Cv ${fmt(r.cv.value, 4)}` : b.type === 'check_valve' ? `Cv ${fmt(b.params.cv, 4)}` : '—',
      r.opening ? `${fmt(r.opening.value, 3)} % open` : r.state ? r.state.value : '—',
      st?.known ? show('mass_flow', st.m, 4) : '—', r.dP ? show('pressure_diff', r.dP.value, 4) : '—', '—',
      r.choked ? `choked: ${r.choked.value}` : '—', '—', status(b.name),
    ] });
  }
  return table([['Name'], ['Type'], ['Size / Cv'], ['Length / opening'], ['Flow'], ['Pressure drop', 1], ['ΔP per 100 m', 1], ['Velocity in → out'], ['Heat lost', 1], ['Status']],
    rows, (r) => select([r.key]), sel);
}

function reliefTable() {
  const sel = [...store.selection.nodes][0];
  const rows = store.doc.blocks.filter((b) => b.type === 'relief_valve').map((b) => {
    const r = res(b.name);
    return { key: b.name, cells: [
      b.params.tag || b.name, b.params.stream || '—', show('pressure', b.params.set_pressure, 4),
      r.rate ? show('mass_flow', r.rate.value, 4) : '—', r.fluid ? r.fluid.value : '—',
      r.area ? show('area', r.area.value, 4) : '—', r.orifice ? r.orifice.value : '—',
      r.rated ? show('mass_flow', r.rated.value, 4) : '—',
      r.governing ? r.governing.value : '—',
      r.inlet_loss ? h('span', { class: r.inlet_ok?.value === 'No' ? 'band-large' : '' }, `${fmt(r.inlet_loss.value, 3)} %`) : '—',
      r.built_up ? `${show('pressure_diff', r.built_up.value, 3)} (${fmt(r.built_up_pct.value, 3)} %)` : '—',
      r.reaction ? show('force', r.reaction.value, 3) : '—',
      status(b.name),
    ] };
  });
  return table([['Tag'], ['Protects stream'], ['Set pressure'], ['Relieving rate'], ['Relieving fluid'], ['Required area'], ['Orifice'], ['Rated capacity'],
    ['Governing scenario'], ['Inlet loss'], ['Built-up back pressure'], ['Reaction force'], ['Status']],
    rows, (r) => select([r.key]), sel);
}

// --- comparison with HYSYS or plant data --------------------------------------------------------------

const KIND_OF = { Temperature: 'temperature', Pressure: 'pressure', 'Mass flow': 'mass_flow', 'Dryness fraction': 'fraction',
  'Specific enthalpy': 'enthalpy', Density: 'density' };

function diffText(row) {
  const k = KIND_OF[row.property];
  if (k === 'temperature') return `${fmt(toUser('temperature_diff', row.difference), 3)} ${unitLabel('temperature_diff')}`;
  if (k === 'fraction') return fmt(row.difference, 3);
  if (k === 'pressure') return `${fmt(toUser('pressure_diff', row.difference), 3)} ${unitLabel('pressure_diff')}`;
  return `${fmt(toUser(k, row.difference), 3)} ${unitLabel(k)}`;
}

function compareTab() {
  const box = h('textarea', {
    'data-key': 'compare-text', spellcheck: 'false',
    placeholder: 'Paste reference results here: copy the HYSYS workbook (properties down the side, streams across the top), '
      + 'a spreadsheet of streams with columns such as "Temperature [C]", "Pressure [kPa]", "Mass Flow [kg/h]", '
      + 'or one value per row: Stream, Property, Value, Unit.',
  }, store.doc.reference?.text || '');
  const run = async () => {
    const text = box.value;
    change((d) => { d.reference = { text }; }, { solve: false });
    try {
      comparison = await post('/api/compare', { flowsheet: store.doc, text });
      render();
    } catch (err) { toast(err.message, 'err'); }
  };
  const csv = () => {
    if (!comparison) return;
    const lines = [['Stream', 'Property', 'Reference', 'Simulated', 'Difference', 'Relative (%)', 'Band'].join(',')];
    for (const r of comparison.rows) {
      lines.push([r.stream, r.property, r.reference, r.simulated, r.difference,
        r.relative === null || r.relative === undefined ? '' : (r.relative * 100).toFixed(3), r.band].join(','));
    }
    download('comparison.csv', lines.join('\n'), 'text/csv');
  };
  const out = [h('div', { class: 'compare-box' }, box, h('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px' } },
    h('button', { class: 'btn small primary', onclick: run }, 'Compare'),
    h('button', { class: 'btn small', onclick: csv, disabled: !comparison }, 'Download CSV')))];
  if (!comparison) {
    out.push(h('div', { style: { padding: '0 14px 10px', color: 'var(--muted)', fontSize: '12px' } },
      'Compares this flowsheet\'s results with a reference stream by stream. Bands: within 1 % (1 °C, 0.01 dryness) is good; '
      + 'within 5 % (3 °C, 0.03) worth checking; beyond that a large difference. HYSYS "ASME Steam" uses the older IFC-67 '
      + 'steam tables, which differ from IAPWS-IF97 by up to about 0.1–0.5 %.'));
    return h('div', {}, ...out);
  }
  const s = comparison.summary || {};
  out.push(h('div', { style: { padding: '0 14px 6px', fontSize: '12px' } },
    `${s.compared || 0} values compared: `, h('span', { class: 'band-good' }, `${s.good || 0} good`), ' · ',
    h('span', { class: 'band-check' }, `${s.check || 0} to check`), ' · ', h('span', { class: 'band-large' }, `${s.large || 0} large`),
    s.worst ? ` · largest: ${s.worst.stream} ${s.worst.property.toLowerCase()}` : ''));
  for (const w of comparison.warnings || []) out.push(h('div', { class: 'msg warn', style: { margin: '0 14px 6px' } }, w));
  const rows = comparison.rows.map((r) => {
    const k = KIND_OF[r.property] || 'number';
    return { key: r.stream, cells: [
      r.stream, r.property, show(k, r.reference, 5), show(k, r.simulated, 5), diffText(r),
      r.relative === null || r.relative === undefined ? '—' : `${fmt(r.relative * 100, 3)} %`,
      h('span', { class: `band-${r.band}` }, { good: 'good', check: 'check', large: 'large' }[r.band]),
    ] };
  });
  out.push(table([['Stream'], ['Property'], ['Reference', 1], ['Simulated', 1], ['Difference', 1], ['Relative', 1], ['']],
    rows, (r) => select([], [r.key])));
  return h('div', {}, ...out);
}

function messagesTable() {
  const res = store.results;
  const items = [];
  if (res?.structure_error) items.push(['Error', res.structure_error]);
  for (const e of res?.errors || []) items.push(['Error', e]);
  for (const w of res?.warnings || []) items.push(['Warning', w]);
  const rows = items.map(([k, t]) => ({ key: t.split(':')[0], cells: [h('span', { style: { color: k === 'Error' ? 'var(--danger)' : 'var(--warn)' } }, k), t] }));
  return table([['Type'], ['Message']], rows, (r) => { if (store.doc.blocks.some((b) => b.name === r.key)) select([r.key]); });
}
