// Application start-up: units, catalog, designer (palette, toolbar, canvas, inspector,
// workbook), solving, and page routing.

import { get, post } from './api.js';
import { h, toast, modal, download, debounce } from './dom.js';
import { PRESETS, initUnits, setPreset, units, onUnitsChange } from './units.js';
import { paletteIcon } from './symbols.js';
import {
  store, on, emit, setCatalog, replaceDoc, restoreAutosave, emptyDoc, undo, redo, autosaveNow, change,
} from './store.js';
import {
  initCanvas, startPlacing, fitView, zoom, autoArrange, exportSVG, deleteSelection, rotateSelection, flipSelection, view,
} from './canvas.js';
import { initInspector } from './inspector.js';
import { initWorkbook } from './workbook.js';
import { openCaseStudy } from './casestudy.js';
import { initReliefPage } from './relief.js';
import { initSteamPage } from './steam.js';

const CATEGORY_ORDER = ['Supplies', 'Pressure change', 'Heat transfer', 'Piping', 'Mixing and splitting', 'Steam system', 'Safety', 'Logical'];
let examples = [];

async function boot() {
  initUnits();
  const sel = document.getElementById('units-preset');
  for (const [key, p] of Object.entries(PRESETS)) sel.append(h('option', { value: key, selected: key === units().key }, p.label));
  sel.addEventListener('change', () => setPreset(sel.value));
  onUnitsChange(() => emit({ units: true }));
  document.getElementById('help-btn').addEventListener('click', showHelp);

  try {
    const [cat, ex] = await Promise.all([get('/api/catalog'), get('/api/examples')]);
    setCatalog(cat);
    examples = ex;
  } catch (err) {
    document.body.innerHTML = `<p style="padding:20px">Could not reach the Steam Suite server: ${err.message}</p>`;
    return;
  }
  buildPalette();
  buildToolbar();
  initCanvas();
  initInspector();
  initWorkbook();
  initStatusBar();
  on(onStoreChange);

  const saved = restoreAutosave();
  if (saved && saved.blocks?.length) {
    replaceDoc(saved, { record: false });
  } else {
    await loadExample(examples[0].key, false);
  }
  setTimeout(() => fitView(), 50);
  window.addEventListener('hashchange', route);
  route();
}

// --- palette -------------------------------------------------------------------------------------

function buildPalette() {
  const pal = document.getElementById('palette');
  pal.innerHTML = '';
  const byCat = {};
  for (const b of store.catalog.blocks) (byCat[b.category] ||= []).push(b);
  const cats = [...CATEGORY_ORDER.filter((c) => byCat[c]), ...Object.keys(byCat).filter((c) => !CATEGORY_ORDER.includes(c))];
  for (const cat of cats) {
    pal.append(h('h4', {}, cat));
    const items = h('div', { class: 'items' });
    for (const b of byCat[cat]) {
      const item = h('div', {
        class: 'palette-item', draggable: 'true', 'data-type': b.type, title: b.description, role: 'button', tabindex: '0',
      });
      item.innerHTML = paletteIcon(b.type);
      item.append(h('span', {}, b.label));
      item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/steam-block', b.type);
        e.dataTransfer.effectAllowed = 'copy';
      });
      item.addEventListener('click', () => startPlacing(b.type));
      item.addEventListener('keydown', (e) => { if (e.key === 'Enter') startPlacing(b.type); });
      items.append(item);
    }
    pal.append(items);
  }
  pal.append(h('p', { class: 'tip' }, 'Drag a symbol onto the drawing, or click it and then click where it should go.'));
}

// --- toolbar -------------------------------------------------------------------------------------------

function tbtn(label, title, onClick, opts = {}) {
  return h('button', { class: `btn small ${opts.cls || ''}`, title, onclick: onClick, id: opts.id }, label);
}

function buildToolbar() {
  const tb = document.getElementById('toolbar');
  const docName = h('span', { class: 'doc-name', id: 'doc-name' }, store.doc.name);
  const fileInput = h('input', { type: 'file', accept: '.json,application/json', hidden: true });
  fileInput.addEventListener('change', async () => {
    const f = fileInput.files[0];
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!Array.isArray(data.blocks)) throw new Error('This is not a Steam Suite flowsheet file.');
      const needLayout = data.blocks.some((b) => !data.layout?.nodes?.[b.name]);
      if (needLayout) data.layout = { ...(data.layout || {}), ...(await post('/api/layout', data)) };
      replaceDoc(data);
      setTimeout(() => fitView(), 30);
      toast(`Opened ${f.name}`);
    } catch (err) { toast(`Could not open the file: ${err.message}`, 'err'); }
    fileInput.value = '';
  });
  const exSel = h('select', { title: 'Open an example', style: { maxWidth: '200px' } },
    h('option', { value: '' }, 'Examples…'), ...examples.map((e) => h('option', { value: e.key }, e.name)));
  exSel.addEventListener('change', async () => {
    if (!exSel.value) return;
    if (store.doc.blocks.length && !confirm('Replace the current drawing with this example? (You can undo.)')) { exSel.value = ''; return; }
    await loadExample(exSel.value);
    exSel.value = '';
  });
  const reportSel = h('select', { title: 'Download a calculation report' },
    h('option', { value: '' }, 'Report…'), h('option', { value: 'html' }, 'Report (HTML, printable)'), h('option', { value: 'md' }, 'Report (Markdown)'));
  reportSel.addEventListener('change', async () => {
    const fmt = reportSel.value;
    reportSel.value = '';
    if (!fmt) return;
    try {
      const text = await fetch(`/api/report?format=${fmt}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(store.doc),
      }).then((r) => { if (!r.ok) throw new Error('The flowsheet could not be solved.'); return r.text(); });
      download(`${slug(store.doc.name)}-report.${fmt === 'md' ? 'md' : 'html'}`, text, fmt === 'md' ? 'text/markdown' : 'text/html');
    } catch (err) { toast(err.message, 'err'); }
  });
  try { store.showData = localStorage.getItem('steamsuite.showData') !== '0'; } catch (e) { /* ignore */ }
  const dataBtn = tbtn('▤ Stream data', 'Show flow, pressure and temperature on every line', () => {
    store.showData = !store.showData;
    try { localStorage.setItem('steamsuite.showData', store.showData ? '1' : '0'); } catch (e) { /* ignore */ }
    dataBtn.classList.toggle('on', store.showData);
    emit({ view: true });
  }, { cls: store.showData ? 'on' : '' });
  const modeSel = h('select', {
    id: 'solver-mode', 'data-key': 'solver-mode',
    title: 'Sequential: flows come from your specifications and from what equipment asks for. '
      + 'Pressure–flow: flows and pressures are solved together from the hydraulics (pipes, valves, pump curves), '
      + 'so parallel branches share flow and back pressures are found.',
  }, ...Object.entries(store.catalog.solver_modes || {}).map(([k, label]) => h('option', { value: k }, label)));
  modeSel.value = store.doc.solver_mode || 'sequential';
  modeSel.addEventListener('change', () => change((d) => { d.solver_mode = modeSel.value; }));
  on((what) => { if (what.doc) modeSel.value = store.doc.solver_mode || 'sequential'; });
  const autoBtn = tbtn('Auto-solve', 'Recalculate automatically after every change', () => {
    store.autoSolve = !store.autoSolve;
    autoBtn.classList.toggle('on', store.autoSolve);
    if (store.autoSolve) scheduleSolve();
  }, { cls: store.autoSolve ? 'on' : '' });

  tb.append(
    docName,
    tbtn('New', 'Start an empty drawing', () => {
      if (store.doc.blocks.length && !confirm('Start a new, empty drawing? (You can undo.)')) return;
      replaceDoc(emptyDoc());
    }),
    tbtn('Open…', 'Open a saved flowsheet (.json)', () => fileInput.click()),
    tbtn('Save', 'Download this flowsheet as a .json file', () => {
      download(`${slug(store.doc.name)}.json`, JSON.stringify(store.doc, null, 2), 'application/json');
    }),
    exSel, fileInput,
    h('span', { class: 'sep' }),
    tbtn('↶', 'Undo (Ctrl+Z)', undo, { id: 'undo-btn' }),
    tbtn('↷', 'Redo (Ctrl+Y)', redo, { id: 'redo-btn' }),
    h('span', { class: 'sep' }),
    tbtn('⟳', 'Rotate selection (R)', () => rotateSelection(90)),
    tbtn('⇋', 'Flip selection (F)', flipSelection),
    tbtn('✕', 'Delete selection (Del)', deleteSelection),
    h('span', { class: 'sep' }),
    tbtn('−', 'Zoom out', () => zoom(1 / 1.2)),
    tbtn('+', 'Zoom in', () => zoom(1.2)),
    tbtn('Fit', 'Fit the drawing to the window (0)', () => fitView()),
    tbtn('Tidy', 'Arrange the drawing automatically', autoArrange),
    dataBtn,
    h('span', { class: 'sep' }),
    tbtn('▶ Solve', 'Recalculate now', () => solveNow(), { cls: 'primary' }),
    modeSel,
    autoBtn,
    tbtn('Case study…', 'Vary one setting and see how results change', openCaseStudy),
    reportSel,
    tbtn('Export drawing', 'Download the P&ID as an SVG image', () => {
      const svgText = exportSVG();
      if (svgText) download(`${slug(store.doc.name)}.svg`, svgText, 'image/svg+xml');
    }),
  );
}

function slug(s) { return (s || 'flowsheet').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'flowsheet'; }

async function loadExample(key, record = true) {
  try {
    const data = await get(`/api/examples/${encodeURIComponent(key)}`);
    replaceDoc(data, { record });
    setTimeout(() => fitView(), 30);
  } catch (err) { toast(err.message, 'err'); }
}

// --- solving -----------------------------------------------------------------------------------------------

let solveSeq = 0;
const scheduleSolve = debounce(() => { if (store.autoSolve) solveNow(); }, 250);

function onStoreChange(what) {
  if (what.doc) {
    document.getElementById('doc-name').textContent = store.doc.name;
    document.getElementById('undo-btn').disabled = !store.undo.length;
    document.getElementById('redo-btn').disabled = !store.redo.length;
    if (what.solve) scheduleSolve();
  }
  if (what.doc || what.results || what.solving !== undefined || what.zoom) updateStatus();
}

export async function solveNow() {
  const seq = ++solveSeq;
  if (!store.doc.blocks.length) {
    store.results = null;
    emit({ results: true });
    return;
  }
  store.solving = true;
  emit({ solving: true });
  try {
    const body = { ...store.doc };
    // pressure–flow mode starts from the last solution (much faster after a small change)
    const last = store.results?.streams;
    if (store.doc.solver_mode === 'pressure_flow' && last) {
      const warm = {};
      for (const [n, st] of Object.entries(last)) if (st.known && st.P > 0) warm[n] = [st.m, st.P, st.h];
      body.warm = warm;
    }
    const res = await post('/api/solve', body);
    if (seq !== solveSeq) return; // a newer solve has started
    store.results = res;
    // Adjust (goal seek) changes settings: keep the calculated values in the document
    for (const [bn, params] of Object.entries(res.adjusted || {})) {
      const b = store.doc.blocks.find((x) => x.name === bn);
      if (b) Object.assign(b.params, params);
    }
    autosaveNow();
  } catch (err) {
    if (seq !== solveSeq) return;
    store.results = { structure_error: err.message, errors: [err.message], warnings: [], streams: {}, blocks: {} };
  }
  store.solving = false;
  emit({ results: true, solving: false });
}

// --- status bar ------------------------------------------------------------------------------------------

let statusEl;
function initStatusBar() {
  statusEl = document.getElementById('statusbar');
  updateStatus();
}

function updateStatus() {
  if (!statusEl) return;
  const r = store.results;
  let dot = '';
  let text = 'Not calculated';
  if (store.solving) { dot = 'busy'; text = 'Calculating…'; } else if (!store.doc.blocks.length) {
    text = 'Empty drawing — drag equipment from the palette';
  } else if (r?.structure_error) { dot = 'err'; text = r.structure_error; } else if (r?.errors?.length) {
    dot = 'err'; text = `${r.errors.length} error(s): ${r.errors[0]}`;
  } else if (r) {
    const warn = r.warnings?.length || 0;
    dot = warn ? 'warn' : 'ok';
    const net = r.network && r.network.mode === 'pressure_flow' ? r.network : null;
    text = net
      ? `Solved (pressure–flow: ${net.equations} equations for ${net.unknowns} unknowns, ${net.time_s} s)${warn ? ` · ${warn} warning(s)` : ''}`
      : `Solved${r.iterations ? ` in ${r.iterations} iterations` : ''}${warn ? ` · ${warn} warning(s)` : ''}`;
    if (net?.notes?.length) text += ` · ${net.notes.join(', ')}`;
    if (r.balance && Object.keys(r.balance).length) {
      text += ` · mass balance ${Math.abs(r.balance.mass_error).toExponential(0)} kg/s · energy ${Math.abs(r.balance.energy_error).toExponential(0)} kW`;
    }
  }
  const nStreams = Object.keys(r?.streams || {}).length;
  statusEl.innerHTML = '';
  statusEl.append(
    h('span', { class: 'state' }, h('span', { class: `dot ${dot}` }), h('span', { style: { maxWidth: '640px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, text)),
    h('span', { style: { flex: 1 } }),
    h('span', {}, `${store.doc.blocks.length} units · ${nStreams} streams`),
    h('span', {}, `${Math.round(view.k * 100)} %`),
    h('span', { title: 'Steam property calculations' }, store.catalog?.property_backend || ''));
}

// --- pages ----------------------------------------------------------------------------------------------------

const inited = {};
function route() {
  const page = (location.hash.replace(/^#\/?/, '') || 'designer').split('?')[0];
  const known = ['designer', 'relief', 'steam'];
  const p = known.includes(page) ? page : 'designer';
  for (const k of known) document.getElementById(`page-${k}`).hidden = k !== p;
  document.querySelectorAll('#page-tabs a').forEach((a) => a.classList.toggle('active', a.dataset.page === p));
  if (p === 'relief' && !inited.relief) { inited.relief = true; initReliefPage(); }
  if (p === 'steam' && !inited.steam) { inited.steam = true; initSteamPage(); }
  if (p === 'designer') setTimeout(() => emit({ view: true }), 0);
}

function showHelp() {
  const k = (t) => h('span', { class: 'kbd' }, t);
  modal('Using the P&ID designer', h('div', { class: 'empty-state', style: { color: 'var(--text)' } },
    h('h3', {}, 'Drawing'),
    h('ul', {},
      h('li', {}, 'Drag equipment from the palette onto the drawing, or click a palette item and then click the drawing.'),
      h('li', {}, 'Connect: drag from an outlet nozzle (filled dot) to an inlet nozzle (open dot). Nozzles show when you hover over a unit.'),
      h('li', {}, 'Drag from an outlet into empty space for a stream that leaves the system; drag from an inlet into empty space to add a water/steam supply.'),
      h('li', {}, 'Right-click a line to insert a pipe segment, valve, heater or relief valve. Drag a line\'s middle section to re-route it.'),
      h('li', {}, 'Click a unit or line to edit it in the panel on the right. The Results and Calculation tabs show every equation used.')),
    h('h3', {}, 'Keyboard and mouse'),
    h('ul', {},
      h('li', {}, k('Del'), ' delete · ', k('R'), ' rotate · ', k('Shift+R'), ' rotate back · ', k('F'), ' flip · ', k('Ctrl+D'), ' duplicate'),
      h('li', {}, k('Ctrl+C'), ' / ', k('Ctrl+V'), ' copy and paste · ', k('Ctrl+Z'), ' / ', k('Ctrl+Y'), ' undo and redo · ', k('Ctrl+A'), ' select all'),
      h('li', {}, 'Mouse wheel: zoom · right or middle drag, or ', k('Space'), '+drag: pan · ', k('0'), ' fit to window · arrow keys: nudge')),
    h('h3', {}, 'Calculations'),
    h('p', {}, 'Steady-state heat and mass balance with IAPWS-IF97 steam properties. Pipe segments calculate pressure drop (Darcy–Weisbach, Colebrook, Crane fittings, two-phase correlations, choking) and heat loss; valves calculate the Cv needed; relief valves are sized to API 520, from API 521 scenarios if you add them, with inlet-loss, back-pressure and reaction-force checks. Use Adjust to make the simulator find a setting that meets a target, and Case study to see how results vary.'),
    h('p', {}, 'Solver: Sequential uses the flows you specify (and what equipment asks for). Pressure–flow solves every flow and pressure together from the hydraulics, so parallel branches share flow, pumps run on their curves and trap back pressures are found; give a sink a pressure where the water ends up. The Compare tab in the workbook checks the results against pasted HYSYS or plant data.'),
    h('p', { style: { color: 'var(--muted)' } }, 'Results are preliminary engineering calculations: have them checked by a qualified engineer before using them for design.')),
  [{ label: 'Close', primary: true }]);
}

boot();
