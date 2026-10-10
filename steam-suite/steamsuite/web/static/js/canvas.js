// The P&ID drawing: SVG rendering and all mouse/keyboard interaction.

import {
  store, on, emit, change, streams, block, node, select, toggleSelect, streamEnd, addBlock, connect,
  addProductStream, deleteStream, deleteBlocks, insertInline, addReliefValve, copySelection, paste,
  undo, redo, autosaveNow,
} from './store.js';
import { symbol, portGeometry, portSpan, anchorPoint, nodeBox } from './symbols.js';
import { show, fmt, toUser, unitLabel } from './units.js';
import { esc, toast } from './dom.js';
import { post } from './api.js';

const svg = document.getElementById('pid');
const hint = document.getElementById('canvas-hint');
const NS = 'http://www.w3.org/2000/svg';
const GRID = 10;
const STUB = 16;

export const view = { x: 40, y: 40, k: 1 };
let drag = null;
let placing = null;
let clipboard = null;
let spaceDown = false;
let g = {};

// --- setup ------------------------------------------------------------------------------------

export function initCanvas() {
  svg.innerHTML = `
    <defs>
      <pattern id="grid-s" width="10" height="10" patternUnits="userSpaceOnUse">
        <path d="M10 0 H0 V10" fill="none" stroke="#f0f3f6" stroke-width="1"/></pattern>
      <pattern id="grid-l" width="50" height="50" patternUnits="userSpaceOnUse">
        <rect width="50" height="50" fill="url(#grid-s)"/><path d="M50 0 H0 V50" fill="none" stroke="#e4e9ef" stroke-width="1"/></pattern>
      ${['steam', 'wet', 'water', 'unknown'].map((c) => `
      <marker id="arrow-${c}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" class="arrow-${c}"/></marker>`).join('')}
    </defs>
    <g id="vp">
      <rect x="-50000" y="-50000" width="100000" height="100000" fill="url(#grid-l)" data-bg="1"/>
      <g id="g-edges"></g><g id="g-links"></g><g id="g-nodes"></g><g id="g-labels"></g><g id="g-overlay"></g>
    </g>`;
  const style = document.createElementNS(NS, 'style');
  style.textContent = `.arrow-steam{fill:var(--steam)}.arrow-wet{fill:var(--wet)}.arrow-water{fill:var(--water)}.arrow-unknown{fill:#95a1ad}`;
  svg.prepend(style);
  g = {
    vp: svg.querySelector('#vp'), edges: svg.querySelector('#g-edges'), links: svg.querySelector('#g-links'),
    nodes: svg.querySelector('#g-nodes'), labels: svg.querySelector('#g-labels'), overlay: svg.querySelector('#g-overlay'),
  };
  svg.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  svg.addEventListener('wheel', onWheel, { passive: false });
  svg.addEventListener('contextmenu', (e) => e.preventDefault());
  svg.addEventListener('dblclick', onDblClick);
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('keyup', (e) => { if (e.code === 'Space') spaceDown = false; });
  const wrap = document.getElementById('canvas-wrap');
  wrap.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/steam-block')) e.preventDefault(); });
  wrap.addEventListener('drop', onDrop);
  document.addEventListener('pointerdown', (e) => {
    const menu = document.getElementById('ctxmenu');
    if (!menu.hidden && !menu.contains(e.target)) menu.hidden = true;
  });
  on((what) => { if (what.doc || what.selection || what.results || what.units || what.view) render(); });
  applyView();
}

function applyView() {
  g.vp.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  emit({ zoom: true });
}

export function toWorld(clientX, clientY) {
  const r = svg.getBoundingClientRect();
  return { x: (clientX - r.left - view.x) / view.k, y: (clientY - r.top - view.y) / view.k };
}

function snap(v) { return Math.round(v / GRID) * GRID; }

function showHint(text) {
  hint.textContent = text || '';
  hint.classList.toggle('show', !!text);
}

// --- geometry -------------------------------------------------------------------------------------

function streamPhaseClass(name) {
  const st = store.results?.streams?.[name];
  if (!st || !st.known) return 'unknown';
  if (st.phase === 'two-phase') return 'wet';
  if (st.phase === 'vapour' || st.phase === 'saturated vapour' || st.phase === 'supercritical') return 'steam';
  return 'water';
}

// rotate a canonical (source points +x) frame into the world
const ROT = {
  '1,0': [1, 0, 0, 1], '-1,0': [-1, 0, 0, -1], '0,1': [0, -1, 1, 0], '0,-1': [0, 1, -1, 0],
};
function toCanon(m, x, y) { return [m[0] * x + m[2] * y, m[1] * x + m[3] * y]; }
function fromCanon(m, x, y) { return [m[0] * x + m[1] * y, m[2] * x + m[3] * y]; }

/**
 * Orthogonal route from port a (with outward direction) to port b (outward direction,
 * or free end without direction). `mid` {axis: 'x'|'y', v} moves the middle segment.
 */
export function route(a, b, mid) {
  const key = `${a.dx},${a.dy}`;
  const m = ROT[key] || ROT['1,0'];
  const [ax, ay] = toCanon(m, a.x, a.y);
  const [bx, by] = toCanon(m, b.x, b.y);
  let bd = null;
  if (b.dx !== undefined) bd = toCanon(m, b.dx, b.dy).map(Math.round);
  // which world axis a canonical x / y line corresponds to
  const cxAxis = Math.abs(fromCanon(m, 1, 0)[0]) > 0.5 ? 'x' : 'y';
  const cyAxis = cxAxis === 'x' ? 'y' : 'x';
  const canonMid = (axis) => {
    if (!mid || mid.axis !== axis) return null;
    const p = axis === 'x' ? toCanon(m, mid.v, 0) : toCanon(m, 0, mid.v);
    return { cx: p[0], cy: p[1] };
  };
  const p1 = [ax + STUB, ay];
  const q0 = [bx, by];
  const q1 = bd ? [bx + bd[0] * STUB, by + bd[1] * STUB] : q0;
  const pts = [[ax, ay], p1];
  const midX = () => { const c = canonMid(cxAxis); return c ? (cxAxis === 'x' ? c.cx : c.cx) : null; };
  const midY = () => { const c = canonMid(cyAxis); return c ? c.cy : null; };
  const zX = (mx) => { pts.push([mx, p1[1]], [mx, q1[1]]); };
  const zY = (my) => { pts.push([p1[0], my], [q1[0], my]); };
  if (!bd) {
    const mx = midX() ?? (q0[0] > p1[0] ? (p1[0] + q0[0]) / 2 : p1[0]);
    zX(mx);
  } else if (bd[0] === -1) { // target faces back towards the source: natural forward flow
    if (q1[0] >= p1[0]) zX(midX() ?? (p1[0] + q1[0]) / 2);
    else zY(midY() ?? (Math.abs(p1[1] - q1[1]) > 40 ? (p1[1] + q1[1]) / 2 : Math.max(p1[1], q1[1]) + 60));
  } else if (bd[0] === 1) {
    zX(midX() ?? Math.max(p1[0], q1[0]));
  } else { // target faces up or down
    const ok = q1[0] >= p1[0] && ((bd[1] === -1 && q1[1] >= p1[1]) || (bd[1] === 1 && q1[1] <= p1[1]));
    if (ok && midX() === null) pts.push([q1[0], p1[1]]);
    else zX(midX() ?? (q1[0] >= p1[0] ? (p1[0] + q1[0]) / 2 : p1[0]));
  }
  pts.push(q1);
  if (bd) pts.push(q0);
  const world = pts.map(([x, y]) => fromCanon(m, x, y));
  return simplify(world);
}

function simplify(pts) {
  const out = [];
  for (const p of pts) {
    const last = out[out.length - 1];
    if (last && Math.abs(last[0] - p[0]) < 0.01 && Math.abs(last[1] - p[1]) < 0.01) continue;
    out.push(p);
  }
  // drop collinear middle points
  for (let i = out.length - 2; i >= 1; i--) {
    const [a, b, c] = [out[i - 1], out[i], out[i + 1]];
    if ((Math.abs(a[0] - b[0]) < 0.01 && Math.abs(b[0] - c[0]) < 0.01) || (Math.abs(a[1] - b[1]) < 0.01 && Math.abs(b[1] - c[1]) < 0.01)) out.splice(i, 1);
  }
  return out;
}

function defaultEnd(a) { return { x: a.x + a.dx * 80, y: a.y + a.dy * 80 }; }

/** Route points of every stream (world coordinates). */
export function streamGeometry() {
  const out = {};
  const all = streams();
  for (const [name, s] of Object.entries(all)) {
    if (!s.src) continue;
    const a = streamEnd(name, 'src');
    if (!a) continue;
    const lay = store.doc.layout.streams[name] || {};
    let b;
    if (s.dst) b = streamEnd(name, 'dst');
    if (!b) b = lay.end || defaultEnd(a);
    out[name] = { pts: route(a, b, lay.mid), product: !s.dst, end: s.dst ? null : b };
  }
  return out;
}

function labelPoint(pts) {
  let best = 0;
  let bi = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const L = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    if (L > best + 0.5) { best = L; bi = i; }
  }
  const [a, b] = [pts[bi], pts[bi + 1]];
  return { x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2, horizontal: Math.abs(a[1] - b[1]) < 0.5 };
}

// --- rendering -------------------------------------------------------------------------------------

function subtitle(b) {
  const r = store.results?.blocks?.[b.name];
  const res = Object.fromEntries((r?.results || []).map((x) => [x.key, x]));
  const p = b.params || {};
  const val = (k) => (res[k] ? show(res[k].kind, res[k].value, 3) : null);
  switch (b.type) {
    case 'pipe': {
      const size = p.size_mode === 'Inside diameter' ? `ID ${fmt(toUser('diameter', p.diameter), 3)} ${unitLabel('diameter')}` : `${p.nps}" Sch ${p.schedule}`;
      const len = `${fmt(toUser('length', p.length), 3)} ${unitLabel('length')}`;
      return [`${size} · ${len}`, res.dP ? `ΔP ${val('dP')}` : null];
    }
    case 'valve': return [res.cv ? `Cv ${fmt(res.cv.value, 3)}${res.opening ? ` · ${fmt(res.opening.value, 2)}% open` : ''}` : null];
    case 'relief_valve': return [res.orifice ? `${p.tag || ''} · orifice ${res.orifice.value}` : p.tag || ''];
    case 'heat_exchanger': return [val('duty')];
    case 'pump': case 'compressor': return [val('power')];
    case 'turbine': return [val('electric')];
    case 'boiler': return [val('steam')];
    case 'header': return [show('pressure', p.pressure, 3)];
    case 'steam_user': return [val('duty')];
    case 'feed': return [res.flow ? `${val('flow')} · ${val('temperature')}` : null];
    case 'deaerator': case 'flash': return [show('pressure', p.pressure, 3)];
    case 'adjust': return [p.var_block ? `varies ${p.var_block}` : 'not set up'];
    default: return [];
  }
}

function asList(v) { return v === undefined || v === null || v === '' ? [] : Array.isArray(v) ? v : [v]; }

function nodeSVG(b) {
  const n = node(b.name);
  if (!n) return '';
  const sym = symbol(b.type);
  const t = store.types[b.type];
  const sel = store.selection.nodes.has(b.name);
  const r = store.results?.blocks?.[b.name];
  const status = r?.error ? 'error' : r?.warnings?.length ? 'warn' : '';
  const tr = `translate(${n.x},${n.y}) rotate(${n.rot || 0}) scale(${n.flip ? -1 : 1},1) translate(${-sym.w / 2},${-sym.h / 2})`;
  let s = `<g class="node ${sel ? 'selected' : ''} ${status}" data-node="${esc(b.name)}">`;
  s += `<g transform="${tr}"><rect class="hit" x="-7" y="-7" width="${sym.w + 14}" height="${sym.h + 14}" rx="6"/>`;
  s += `<g class="body">${sym.draw()}</g></g>`;
  // nozzles
  for (const [side, defs] of [['in', t?.inlets || []], ['out', t?.outlets || []]]) {
    for (const pd of defs) {
      const conn = asList((side === 'in' ? b.inlets : b.outlets)[pd.key]);
      const span = portSpan(b.type, pd.key, n);
      const attrs = `data-port="${pd.key}" data-side="${side}" data-block="${esc(b.name)}"`;
      if (span) {
        s += `<line class="port-span ${side}" ${attrs} x1="${span[0][0]}" y1="${span[0][1]}" x2="${span[1][0]}" y2="${span[1][1]}"><title>${esc(pd.label)}</title></line>`;
      } else {
        const geo = portGeometry(b.type, pd.key, n);
        if (geo) s += `<circle class="port ${side} ${conn.length ? 'connected' : ''}" ${attrs} cx="${geo.x}" cy="${geo.y}" r="5"><title>${esc(pd.label)}</title></circle>`;
      }
    }
  }
  const box = nodeBox(b.type, n);
  s += `<text class="node-label" x="${n.x}" y="${box.y1 + 15}">${esc(b.name)}</text>`;
  const subs = subtitle(b).filter(Boolean);
  subs.forEach((line, i) => { s += `<text class="node-sub" x="${n.x}" y="${box.y1 + 27 + i * 11}">${esc(line)}</text>`; });
  if (status) {
    s += `<circle class="badge-${status === 'error' ? 'err' : 'warn'}" cx="${box.x1 + 2}" cy="${box.y0 - 2}" r="7"/>`;
    s += `<text class="badge-text" x="${box.x1 + 2}" y="${box.y0 + 1.5}">!</text>`;
  }
  return `${s}</g>`;
}

function streamData(name) {
  const st = store.results?.streams?.[name];
  if (!st || !st.known) return null;
  return `${show('mass_flow', st.m, 3)} · ${show('pressure', st.P, 3)} · ${show('temperature', st.T, 3)}`;
}

let geometryCache = {};

function segmentsByLength(pts) {
  const segs = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const [a, b] = [pts[i], pts[i + 1]];
    segs.push({ a, b, L: Math.hypot(b[0] - a[0], b[1] - a[1]), horizontal: Math.abs(a[1] - b[1]) < 0.5 });
  }
  return segs.sort((x, y) => y.L - x.L);
}

function overlaps(r, list) {
  return list.some((o) => r.x < o.x1 && r.x + r.w > o.x0 && r.y < o.y1 && r.y + r.h > o.y0);
}

/** Label position: the user's offset if set, else the first spot along the line that avoids clutter. */
function placeLabel(name, gm, w, hgt, occupied) {
  const segs = segmentsByLength(gm.pts);
  const off = store.doc.layout.streams[name]?.label;
  const first = segs[0];
  const mid = (sg) => ({ x: (sg.a[0] + sg.b[0]) / 2, y: (sg.a[1] + sg.b[1]) / 2 });
  const base = (sg, shift = 0, side = 0, gap = 5) => {
    const m = mid(sg);
    if (sg.horizontal) return { x: m.x - w / 2 + shift, y: side ? m.y + gap : m.y - hgt - gap };
    return { x: side ? m.x - w - gap - 1 : m.x + gap + 1, y: m.y - hgt / 2 + shift };
  };
  if (off) {
    const p = base(first);
    return { x: p.x + off.dx, y: p.y + off.dy };
  }
  const candidates = [];
  for (const gap of [5, 36]) {
    for (const sg of segs) {
      if (sg.L < 12) continue;
      const span = Math.max(0, (sg.L - (sg.horizontal ? w : hgt)) / 2);
      for (const side of [0, 1]) {
        for (const f of [0, -0.5, 0.5, -1, 1]) candidates.push(base(sg, f * span, side, gap));
      }
    }
  }
  for (const c of candidates) {
    if (!overlaps({ x: c.x, y: c.y, w, h: hgt }, occupied)) return c;
  }
  return base(first);
}

export function render() {
  if (!g.nodes) return;
  const geo = streamGeometry();
  geometryCache = geo;
  // areas taken by equipment (symbol plus its name and subtitle)
  const occupied = [];
  for (const b of store.doc.blocks) {
    const n = node(b.name);
    if (!n) continue;
    const box = nodeBox(b.type, n);
    const tw = Math.max(box.w, b.name.length * 6.5);
    occupied.push({ x0: n.x - tw / 2 - 2, x1: n.x + tw / 2 + 2, y0: box.y0 - 2, y1: box.y1 + 30 });
  }
  // pipes
  let edges = '';
  let labels = '';
  const order = Object.keys(geo).sort((a, b) => (store.doc.layout.streams[b]?.label ? 1 : 0) - (store.doc.layout.streams[a]?.label ? 1 : 0));
  for (const name of order) {
    const gm = geo[name];
    const d = `M${gm.pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L')}`;
    const cls = streamPhaseClass(name);
    const sel = store.selection.streams.has(name);
    edges += `<path class="edge-hit" data-stream="${esc(name)}" d="${d}"/>`;
    edges += `<path class="edge ${cls} ${sel ? 'selected' : ''}" d="${d}" marker-end="url(#arrow-${cls})" pointer-events="none"/>`;
    if (gm.product) edges += `<circle class="end-handle" data-stream-end="${esc(name)}" cx="${gm.end.x}" cy="${gm.end.y}" r="4.5"><title>Drag to move the end of the line</title></circle>`;
    const data = store.showData ? streamData(name) : null;
    const w = Math.max(name.length * 6.6 + 10, data ? data.length * 5.5 + 10 : 0);
    const hgt = data ? 28 : 16;
    const pos = placeLabel(name, gm, w, hgt, occupied);
    occupied.push({ x0: pos.x - 3, x1: pos.x + w + 3, y0: pos.y - 2, y1: pos.y + hgt + 2 });
    gm.labelAt = { x: pos.x + w / 2, y: pos.y + hgt / 2 };
    labels += `<g class="stream-label ${sel ? 'selected' : ''}" data-stream="${esc(name)}" transform="translate(${pos.x.toFixed(1)},${pos.y.toFixed(1)})">
      <rect width="${w.toFixed(1)}" height="${hgt}" rx="3"/>
      <text class="name" x="5" y="11.5">${esc(name)}</text>${data ? `<text class="data" x="5" y="23.5">${esc(data)}</text>` : ''}</g>`;
  }
  g.edges.innerHTML = edges;
  g.labels.innerHTML = labels;
  g.nodes.innerHTML = store.doc.blocks.map(nodeSVG).join('');
  // dashed information links (relief valves to streams, Adjust to the units it uses)
  let links = '';
  for (const b of store.doc.blocks) {
    const n = node(b.name);
    if (!n) continue;
    const [ax, ay] = anchorPoint(b.type, n);
    const targets = [];
    if (b.type === 'relief_valve' && b.params.stream && geo[b.params.stream]) targets.push(geo[b.params.stream].labelAt || labelPoint(geo[b.params.stream].pts));
    if (b.type === 'adjust') {
      for (const key of ['var_block', 'target_block']) {
        const tn = b.params[key] && node(b.params[key]);
        if (tn && (key === 'var_block' || b.params.target_type === 'Equipment result')) targets.push({ x: tn.x, y: tn.y });
      }
      if (b.params.target_type === 'Stream property' && geo[b.params.target_stream]) targets.push(geo[b.params.target_stream].labelAt || labelPoint(geo[b.params.target_stream].pts));
    }
    for (const t of targets) links += `<path class="link" d="M${ax},${ay} L${t.x},${t.y}"/>`;
  }
  g.links.innerHTML = links;
  emit({ rendered: true });
}

// --- interaction -------------------------------------------------------------------------------------

function hitInfo(target) {
  const el = target.closest('[data-port],[data-stream-end],[data-stream],[data-node]');
  if (!el) return { kind: 'bg' };
  if (el.dataset.port) return { kind: 'port', block: el.dataset.block, port: el.dataset.port, side: el.dataset.side, el };
  if (el.dataset.streamEnd) return { kind: 'end', stream: el.dataset.streamEnd };
  if (el.dataset.stream) return { kind: 'stream', stream: el.dataset.stream, isPath: el.tagName === 'path' };
  if (el.dataset.node) return { kind: 'node', block: el.dataset.node };
  return { kind: 'bg' };
}

function onPointerDown(e) {
  svg.focus({ preventScroll: true });
  document.getElementById('ctxmenu').hidden = true;
  const w = toWorld(e.clientX, e.clientY);
  if (e.button === 1 || (e.button === 0 && spaceDown)) {
    drag = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
    svg.classList.add('panning');
    e.preventDefault();
    return;
  }
  const hit = hitInfo(e.target);
  if (e.button === 2) {
    drag = { kind: 'rpan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, hit, moved: false };
    return;
  }
  if (e.button !== 0) return;
  if (placing && hit.kind !== 'port') {
    const type = placing;
    stopPlacing();
    let created = null;
    change((d) => { created = addBlock(d, type, w.x, w.y).name; });
    select([created]);
    return;
  }
  const before = JSON.stringify(store.doc);
  if (hit.kind === 'port') {
    drag = { kind: 'connect', from: hit, start: w, before };
    svg.classList.add('connecting');
    showHint(hit.side === 'out' ? 'Release on an inlet nozzle to connect — or on empty space for a stream leaving the system'
      : 'Release on an outlet nozzle to connect — or on empty space to create a water/steam supply');
    highlightTargets(hit);
  } else if (hit.kind === 'end') {
    drag = { kind: 'end', stream: hit.stream, before };
  } else if (hit.kind === 'stream') {
    if (e.shiftKey) toggleSelect('stream', hit.stream);
    else if (!store.selection.streams.has(hit.stream)) select([], [hit.stream]);
    let off = store.doc.layout.streams[hit.stream]?.label;
    if (!off && !hit.isPath) {
      // start from where the label is drawn now (it may have been moved to avoid clutter)
      const el = e.target.closest('.stream-label');
      const m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(el?.getAttribute('transform') || '');
      const gm = geometryCache[hit.stream];
      if (m && gm) {
        const segs = segmentsByLength(gm.pts);
        const sg = segs[0];
        const rect = el.querySelector('rect');
        const lw = +rect.getAttribute('width');
        const lh = +rect.getAttribute('height');
        const mx = (sg.a[0] + sg.b[0]) / 2;
        const my = (sg.a[1] + sg.b[1]) / 2;
        const bx = sg.horizontal ? mx - lw / 2 : mx + 6;
        const by = sg.horizontal ? my - lh - 5 : my - lh / 2;
        off = { dx: +m[1] - bx, dy: +m[2] - by };
      }
    }
    off = off || { dx: 0, dy: 0 };
    drag = hit.isPath ? { kind: 'mid', stream: hit.stream, start: w, before, moved: false }
      : { kind: 'label', stream: hit.stream, start: w, orig: { ...off }, before, moved: false };
  } else if (hit.kind === 'node') {
    if (e.shiftKey) toggleSelect('node', hit.block);
    else if (!store.selection.nodes.has(hit.block)) select([hit.block]);
    const orig = {};
    for (const n of store.selection.nodes) orig[n] = { ...node(n) };
    const lay = store.doc.layout.streams;
    const ends = {};
    for (const [sn, s] of Object.entries(streams())) {
      if (s.src && !s.dst && store.selection.nodes.has(s.src.block) && lay[sn]?.end) ends[sn] = { ...lay[sn].end };
    }
    drag = { kind: 'move', start: w, orig, ends, before, moved: false };
  } else {
    if (!e.shiftKey) select();
    drag = { kind: 'band', start: w, additive: e.shiftKey };
  }
}

function highlightTargets(from) {
  const want = from.side === 'out' ? 'in' : 'out';
  svg.querySelectorAll(`[data-port][data-side="${want}"]`).forEach((el) => {
    if (el.dataset.block !== from.block) el.style.opacity = '1';
  });
}

function clearTargets() {
  svg.querySelectorAll('[data-port]').forEach((el) => { el.style.opacity = ''; el.classList.remove('target'); });
}

function portUnder(e, from) {
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (!el) return null;
  const p = el.closest('[data-port]');
  if (!p || p.dataset.block === from.block || p.dataset.side === from.side) return null;
  return { block: p.dataset.block, port: p.dataset.port, side: p.dataset.side, el: p };
}

function onPointerMove(e) {
  if (!drag) return;
  const w = toWorld(e.clientX, e.clientY);
  switch (drag.kind) {
    case 'pan':
    case 'rpan': {
      const dx = e.clientX - drag.sx;
      const dy = e.clientY - drag.sy;
      if (drag.kind === 'rpan' && !drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      svg.classList.add('panning');
      view.x = drag.vx + dx;
      view.y = drag.vy + dy;
      applyView();
      break;
    }
    case 'move': {
      const dx = w.x - drag.start.x;
      const dy = w.y - drag.start.y;
      if (!drag.moved && Math.hypot(dx, dy) < 2 / view.k) return;
      drag.moved = true;
      for (const [n, o] of Object.entries(drag.orig)) {
        store.doc.layout.nodes[n] = { ...o, x: snap(o.x + dx), y: snap(o.y + dy) };
      }
      for (const [sn, end] of Object.entries(drag.ends)) {
        store.doc.layout.streams[sn] = { ...store.doc.layout.streams[sn], end: { x: snap(end.x + dx), y: snap(end.y + dy) } };
      }
      requestRender();
      break;
    }
    case 'end': {
      store.doc.layout.streams[drag.stream] = { ...store.doc.layout.streams[drag.stream], end: { x: snap(w.x), y: snap(w.y) } };
      drag.moved = true;
      requestRender();
      break;
    }
    case 'label': {
      const dx = w.x - drag.start.x;
      const dy = w.y - drag.start.y;
      if (!drag.moved && Math.hypot(dx, dy) < 3 / view.k) return;
      drag.moved = true;
      store.doc.layout.streams[drag.stream] = {
        ...store.doc.layout.streams[drag.stream], label: { dx: Math.round(drag.orig.dx + dx), dy: Math.round(drag.orig.dy + dy) },
      };
      requestRender();
      break;
    }
    case 'mid': {
      const gm = geometryCache[drag.stream];
      if (!gm || gm.pts.length < 4) return;
      if (!drag.moved && Math.hypot(w.x - drag.start.x, w.y - drag.start.y) < 3 / view.k) return;
      if (!drag.seg) {
        // pick the nearest interior segment
        let best = Infinity;
        for (let i = 1; i < gm.pts.length - 2; i++) {
          const [a, b] = [gm.pts[i], gm.pts[i + 1]];
          const d = distToSeg(drag.start, a, b);
          if (d < best) { best = d; drag.seg = { vertical: Math.abs(a[0] - b[0]) < 0.5 }; }
        }
        if (!drag.seg) return;
      }
      drag.moved = true;
      const mid = drag.seg.vertical ? { axis: 'x', v: snap(w.x) } : { axis: 'y', v: snap(w.y) };
      store.doc.layout.streams[drag.stream] = { ...store.doc.layout.streams[drag.stream], mid };
      requestRender();
      break;
    }
    case 'connect': {
      clearTargets();
      highlightTargets(drag.from);
      const tgt = portUnder(e, drag.from);
      if (tgt) tgt.el.classList.add('target');
      const a = drag.from.el;
      const ax = +(a.getAttribute('cx') ?? (+a.getAttribute('x1') + +a.getAttribute('x2')) / 2);
      const ay = +(a.getAttribute('cy') ?? (+a.getAttribute('y1') + +a.getAttribute('y2')) / 2);
      g.overlay.innerHTML = `<path class="temp-wire" d="M${ax},${ay} L${w.x},${w.y}"/>`;
      break;
    }
    case 'band': {
      const x = Math.min(drag.start.x, w.x);
      const y = Math.min(drag.start.y, w.y);
      drag.rect = { x0: x, y0: y, x1: Math.max(drag.start.x, w.x), y1: Math.max(drag.start.y, w.y) };
      g.overlay.innerHTML = `<rect class="rubber" x="${x}" y="${y}" width="${drag.rect.x1 - x}" height="${drag.rect.y1 - y}"/>`;
      break;
    }
    default:
  }
}

function distToSeg(p, a, b) {
  const [x1, y1] = a;
  const [x2, y2] = b;
  const L = (x2 - x1) ** 2 + (y2 - y1) ** 2;
  let t = L ? ((p.x - x1) * (x2 - x1) + (p.y - y1) * (y2 - y1)) / L : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (x1 + t * (x2 - x1)), p.y - (y1 + t * (y2 - y1)));
}

let renderPending = false;
function requestRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => { renderPending = false; render(); });
}

function commitDrag(before) {
  const after = JSON.stringify(store.doc);
  if (after !== before) {
    store.undo.push(before);
    store.redo = [];
    autosaveNow();
    emit({ doc: true, solve: false });
  }
}

function onPointerUp(e) {
  if (!drag) return;
  const d = drag;
  drag = null;
  svg.classList.remove('panning', 'connecting');
  g.overlay.innerHTML = '';
  showHint(placing ? `Click on the drawing to place the ${store.types[placing].label.toLowerCase()} (Esc to cancel)` : '');
  const w = toWorld(e.clientX, e.clientY);
  switch (d.kind) {
    case 'rpan':
      if (!d.moved) openContextMenu(e.clientX, e.clientY, d.hit, w);
      break;
    case 'move':
    case 'end':
    case 'mid':
    case 'label':
      if (d.moved) commitDrag(d.before);
      break;
    case 'connect': {
      clearTargets();
      const tgt = portUnder(e, d.from);
      if (tgt) {
        const [src, dst] = d.from.side === 'out' ? [d.from, tgt] : [tgt, d.from];
        let res = null;
        change((doc) => { res = connect(doc, src, dst); });
        if (res?.error) toast(res.error, 'err');
        else if (res?.name) select([], [res.name]);
      } else if (Math.hypot(w.x - d.start.x, w.y - d.start.y) > 12) {
        if (d.from.side === 'out') {
          let res = null;
          change((doc) => { res = addProductStream(doc, d.from, snap(w.x), snap(w.y)); });
          if (res?.error) toast(res.error, 'err');
          else if (res?.name) select([], [res.name]);
        } else {
          // dragging out of an inlet creates a water/steam supply feeding it
          let made = null;
          let res = null;
          change((doc) => {
            const feed = addBlock(doc, 'feed', w.x - 30, w.y);
            made = feed.name;
            res = connect(doc, { block: feed.name, port: 'out' }, d.from);
          });
          if (res?.error) toast(res.error, 'err');
          else select([made]);
        }
      }
      break;
    }
    case 'band': {
      if (!d.rect) break;
      const inside = store.doc.blocks.filter((b) => {
        const n = node(b.name);
        return n && n.x >= d.rect.x0 && n.x <= d.rect.x1 && n.y >= d.rect.y0 && n.y <= d.rect.y1;
      }).map((b) => b.name);
      select(inside, [], d.additive);
      break;
    }
    default:
  }
}

function onWheel(e) {
  e.preventDefault();
  const r = svg.getBoundingClientRect();
  const px = e.clientX - r.left;
  const py = e.clientY - r.top;
  if (e.ctrlKey || e.metaKey || !e.shiftKey) {
    const k = Math.min(3, Math.max(0.2, view.k * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015))));
    view.x = px - ((px - view.x) * k) / view.k;
    view.y = py - ((py - view.y) * k) / view.k;
    view.k = k;
  } else {
    view.x -= e.deltaX || e.deltaY;
  }
  applyView();
}

function onDblClick(e) {
  const hit = hitInfo(e.target);
  if (hit.kind === 'node' || hit.kind === 'stream') emit({ focusInspector: true });
}

function onDrop(e) {
  const type = e.dataTransfer.getData('text/steam-block');
  if (!type || !store.types[type]) return;
  e.preventDefault();
  const w = toWorld(e.clientX, e.clientY);
  let created = null;
  change((d) => { created = addBlock(d, type, w.x, w.y).name; });
  select([created]);
  svg.focus({ preventScroll: true });
}

export function startPlacing(type) {
  placing = type;
  document.querySelectorAll('.palette-item').forEach((el) => el.classList.toggle('placing', el.dataset.type === type));
  showHint(`Click on the drawing to place the ${store.types[type].label.toLowerCase()} (Esc to cancel)`);
}

function stopPlacing() {
  placing = null;
  document.querySelectorAll('.palette-item').forEach((el) => el.classList.remove('placing'));
  showHint('');
}

// --- commands ---------------------------------------------------------------------------------------

export function deleteSelection() {
  const nodes = [...store.selection.nodes];
  const strm = [...store.selection.streams];
  if (!nodes.length && !strm.length) return;
  change((d) => {
    for (const s of strm) deleteStream(d, s);
    if (nodes.length) deleteBlocks(d, nodes);
  });
  select();
}

export function rotateSelection(deg = 90) {
  const nodes = [...store.selection.nodes];
  if (!nodes.length) return;
  change((d) => { for (const n of nodes) d.layout.nodes[n].rot = (((d.layout.nodes[n].rot || 0) + deg) % 360 + 360) % 360; }, { solve: false });
}

export function flipSelection() {
  const nodes = [...store.selection.nodes];
  if (!nodes.length) return;
  change((d) => { for (const n of nodes) d.layout.nodes[n].flip = !d.layout.nodes[n].flip; }, { solve: false });
}

export function copy() {
  clipboard = copySelection();
  if (clipboard) toast(`Copied ${clipboard.blocks.length} unit(s)`);
}

export function pasteClipboard() {
  if (!clipboard) return;
  let names = [];
  change((d) => { names = paste(d, clipboard); });
  select(names);
}

export function duplicate() {
  copy();
  pasteClipboard();
}

export function fitView(margin = 60) {
  const r = svg.getBoundingClientRect();
  const pts = [];
  for (const b of store.doc.blocks) {
    const n = node(b.name);
    if (!n) continue;
    const box = nodeBox(b.type, n);
    pts.push([box.x0, box.y0], [box.x1, box.y1 + 30]);
  }
  for (const gm of Object.values(geometryCache)) for (const p of gm.pts) pts.push(p);
  if (!pts.length || !r.width) { view.x = 40; view.y = 40; view.k = 1; applyView(); return; }
  const x0 = Math.min(...pts.map((p) => p[0])) - margin;
  const y0 = Math.min(...pts.map((p) => p[1])) - margin;
  const x1 = Math.max(...pts.map((p) => p[0])) + margin;
  const y1 = Math.max(...pts.map((p) => p[1])) + margin;
  const k = Math.min(1.4, Math.max(0.2, Math.min(r.width / (x1 - x0), (r.height - 26) / (y1 - y0))));
  view.k = k;
  view.x = (r.width - (x1 - x0) * k) / 2 - x0 * k;
  view.y = (r.height - 26 - (y1 - y0) * k) / 2 - y0 * k;
  applyView();
}

export function zoom(factor) {
  const r = svg.getBoundingClientRect();
  const px = r.width / 2;
  const py = r.height / 2;
  const k = Math.min(3, Math.max(0.2, view.k * factor));
  view.x = px - ((px - view.x) * k) / view.k;
  view.y = py - ((py - view.y) * k) / view.k;
  view.k = k;
  applyView();
}

export async function autoArrange() {
  try {
    const lay = await post('/api/layout', store.doc);
    change((d) => {
      for (const [n, p] of Object.entries(lay.nodes)) d.layout.nodes[n] = { ...p, rot: d.layout.nodes[n]?.rot || 0, flip: d.layout.nodes[n]?.flip || false };
      for (const s of Object.values(d.layout.streams)) delete s.mid;
    }, { solve: false });
    setTimeout(fitView, 30);
  } catch (err) { toast(err.message, 'err'); }
}

export function exportSVG() {
  const geo = streamGeometry();
  const pts = [];
  for (const b of store.doc.blocks) {
    const box = nodeBox(b.type, node(b.name));
    pts.push([box.x0, box.y0], [box.x1, box.y1 + 34]);
  }
  for (const gm of Object.values(geo)) for (const p of gm.pts) pts.push(p);
  if (!pts.length) return null;
  const pad = 40;
  const x0 = Math.min(...pts.map((p) => p[0])) - pad;
  const y0 = Math.min(...pts.map((p) => p[1])) - pad;
  const x1 = Math.max(...pts.map((p) => p[0])) + pad;
  const y1 = Math.max(...pts.map((p) => p[1])) + pad;
  const css = `.sym{fill:#fff;stroke:#33404d;stroke-width:1.6}.sym-fill{fill:#dfe7f1;stroke:#33404d;stroke-width:1.6}
    .sym-thin{fill:none;stroke:#6f7d8b;stroke-width:1}.flame{fill:none;stroke:#e0562c;stroke-width:1.6}
    .hit,.port,.port-span,.end-handle,.edge-hit,.badge-err,.badge-warn,.badge-text{display:none}
    .node-label{font:600 11.5px sans-serif;fill:#1f2a36;text-anchor:middle}.node-sub{font:10px sans-serif;fill:#5c6976;text-anchor:middle}
    .edge{fill:none;stroke-width:2}.edge.steam{stroke:#cf3e4f}.edge.wet{stroke:#8a55c4}.edge.water{stroke:#2c6cb3}.edge.unknown{stroke:#95a1ad}
    .link{fill:none;stroke:#7d8a97;stroke-width:1.2;stroke-dasharray:5 4}
    .stream-label rect{fill:#fff;stroke:#c3ccd6}.stream-label text{font:10.5px sans-serif;fill:#24303c}.stream-label .name{font-weight:650}
    .stream-label .data{font-size:10px;fill:#4d5a67}.arrow-steam{fill:#cf3e4f}.arrow-wet{fill:#8a55c4}.arrow-water{fill:#2c6cb3}.arrow-unknown{fill:#95a1ad}`;
  const defs = svg.querySelector('defs').outerHTML.replace(/<pattern[\s\S]*?<\/pattern>/g, '');
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x0} ${y0} ${x1 - x0} ${y1 - y0}" width="${x1 - x0}" height="${y1 - y0}">
<style>${css}</style>${defs}<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="#fff"/>
<text x="${x0 + 16}" y="${y0 + 22}" style="font:600 14px sans-serif;fill:#1c2631">${esc(store.doc.name)}</text>
${g.edges.innerHTML}${g.links.innerHTML}${g.nodes.innerHTML}${g.labels.innerHTML}</svg>`;
}

// --- keyboard ----------------------------------------------------------------------------------------

function typingInField(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

function onKeyDown(e) {
  if (document.getElementById('page-designer').hidden) return;
  if (document.querySelector('.modal-backdrop')) return;
  if (typingInField(e)) return;
  const mod = e.ctrlKey || e.metaKey;
  if (e.code === 'Space') { spaceDown = true; return; }
  if (e.key === 'Escape') {
    stopPlacing();
    if (drag) { drag = null; g.overlay.innerHTML = ''; clearTargets(); svg.classList.remove('connecting'); }
    select();
    document.getElementById('ctxmenu').hidden = true;
    return;
  }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelection(); return; }
  if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
  if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
  if (mod && e.key.toLowerCase() === 'c') { e.preventDefault(); copy(); return; }
  if (mod && e.key.toLowerCase() === 'v') { e.preventDefault(); pasteClipboard(); return; }
  if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicate(); return; }
  if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); select(store.doc.blocks.map((b) => b.name), Object.keys(streams())); return; }
  if (mod) return;
  if (e.key === 'r' || e.key === 'R') { rotateSelection(e.shiftKey ? -90 : 90); return; }
  if (e.key === 'f' || e.key === 'F') { flipSelection(); return; }
  if (e.key === '+' || e.key === '=') { zoom(1.2); return; }
  if (e.key === '-') { zoom(1 / 1.2); return; }
  if (e.key === '0') { fitView(); return; }
  const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (arrows[e.key] && store.selection.nodes.size) {
    e.preventDefault();
    const [dx, dy] = arrows[e.key].map((v) => v * (e.shiftKey ? 50 : GRID));
    change((d) => { for (const n of store.selection.nodes) { d.layout.nodes[n].x += dx; d.layout.nodes[n].y += dy; } }, { solve: false });
  }
}

// --- context menu ---------------------------------------------------------------------------------------

function openContextMenu(cx, cy, hit, w) {
  const menu = document.getElementById('ctxmenu');
  const items = [];
  const add = (label, fn, key = '') => items.push({ label, fn, key });
  if (hit.kind === 'node') {
    if (!store.selection.nodes.has(hit.block)) select([hit.block]);
    const b = block(hit.block);
    add('Properties', () => emit({ focusInspector: true }), 'Double-click');
    add('Rotate 90°', () => rotateSelection(90), 'R');
    add('Flip horizontally', flipSelection, 'F');
    add('Duplicate', duplicate, 'Ctrl+D');
    add('Copy', copy, 'Ctrl+C');
    if (b && store.types[b.type].outlets.length) {
      add('---');
      add('Add a relief valve on the outlet', () => {
        const out = Object.values(b.outlets).flat()[0];
        if (!out) { toast('Connect an outlet first.', 'err'); return; }
        let made;
        change((d) => { made = addReliefValve(d, out, node(b.name).x + 70, node(b.name).y - 90).name; });
        select([made]);
      });
    }
    add('---');
    add('Delete', deleteSelection, 'Del');
  } else if (hit.kind === 'stream' || hit.kind === 'end') {
    const name = hit.stream;
    select([], [name]);
    add('Insert pipe segment (pressure drop)', () => insertOnStream(name, 'pipe'));
    add('Insert valve', () => insertOnStream(name, 'valve'));
    add('Insert heater / cooler', () => insertOnStream(name, 'heater'));
    add('Insert pump', () => insertOnStream(name, 'pump'));
    add('Add relief valve (PSV) on this line', () => {
      const lp = labelPoint(geometryCache[name].pts);
      let made;
      change((d) => { made = addReliefValve(d, name, snap(lp.x + 30), snap(lp.y - 80)).name; });
      select([made]);
    });
    add('---');
    add('Straighten line', () => change((d) => { if (d.layout.streams[name]) delete d.layout.streams[name].mid; }, { solve: false }));
    add('Reset label position', () => change((d) => { if (d.layout.streams[name]) delete d.layout.streams[name].label; }, { solve: false }));
    add('Delete stream', deleteSelection, 'Del');
  } else {
    if (clipboard) add('Paste', () => {
      let names = [];
      const cx0 = clipboard.blocks.length ? clipboard.nodes[clipboard.blocks[0].name] : { x: 0, y: 0 };
      change((d) => { names = paste(d, clipboard, snap(w.x - cx0.x), snap(w.y - cx0.y)); });
      select(names);
    }, 'Ctrl+V');
    add('Fit drawing to window', () => fitView(), '0');
    add('Tidy layout automatically', autoArrange);
    add('Select all', () => select(store.doc.blocks.map((b) => b.name), Object.keys(streams())), 'Ctrl+A');
  }
  menu.innerHTML = '';
  for (const it of items) {
    if (it.label === '---') { menu.append(document.createElement('hr')); continue; }
    const btn = document.createElement('button');
    btn.innerHTML = `<span>${esc(it.label)}</span><span class="k">${esc(it.key)}</span>`;
    btn.addEventListener('click', () => { menu.hidden = true; it.fn(); });
    menu.append(btn);
  }
  menu.hidden = false;
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  menu.style.left = `${Math.min(cx, window.innerWidth - mw - 6)}px`;
  menu.style.top = `${Math.min(cy, window.innerHeight - mh - 6)}px`;
}

export function insertOnStream(name, type) {
  let res = null;
  change((d) => { res = insertInline(d, name, type); });
  if (res?.error) toast(res.error, 'err');
  else if (res?.block) select([res.block]);
}

export function addReliefOnStream(name) {
  const gm = geometryCache[name];
  if (!gm) return;
  const lp = labelPoint(gm.pts);
  let made;
  change((d) => { made = addReliefValve(d, name, snap(lp.x + 30), snap(lp.y - 80)).name; });
  select([made]);
}
