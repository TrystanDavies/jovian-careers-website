// The document being edited (a flowsheet with its drawing layout), selection,
// solve results, undo/redo and autosave.

import { TAG_PREFIX, portGeometry, symbol } from './symbols.js';

const AUTOSAVE_KEY = 'steamsuite.designer.doc';
const listeners = new Set();

export const store = {
  catalog: null, // from /api/catalog
  types: {}, // type -> catalog entry
  doc: emptyDoc(),
  results: null, // last /api/solve payload
  solving: false,
  selection: { nodes: new Set(), streams: new Set() },
  undo: [],
  redo: [],
  showData: true,
  autoSolve: true,
};

export function emptyDoc() {
  return { name: 'New flowsheet', description: '', blocks: [], estimates: {}, layout: { nodes: {}, streams: {} } };
}

export function on(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function emit(what = {}) { listeners.forEach((fn) => fn(what)); }

export function setCatalog(cat) {
  store.catalog = cat;
  store.types = Object.fromEntries(cat.blocks.map((b) => [b.type, b]));
}

// --- document access ---------------------------------------------------------------

export function block(name) { return store.doc.blocks.find((b) => b.name === name); }
export function typeOf(name) { const b = block(name); return b && store.types[b.type]; }
export function node(name) { return store.doc.layout.nodes[name]; }

function asList(v) { return v === undefined || v === null || v === '' ? [] : Array.isArray(v) ? v : [v]; }

/** Streams derived from the blocks' ports: name -> {src: {block, port}, dst: {block, port}} */
export function streams(doc = store.doc) {
  const out = {};
  for (const b of doc.blocks) {
    for (const [port, v] of Object.entries(b.outlets || {})) {
      for (const n of asList(v)) (out[n] ||= {}).src = { block: b.name, port };
    }
  }
  for (const b of doc.blocks) {
    for (const [port, v] of Object.entries(b.inlets || {})) {
      for (const n of asList(v)) (out[n] ||= {}).dst = { block: b.name, port };
    }
  }
  return out;
}

/** Which slot of a multi-port a stream occupies, and how many slots there are. */
export function slotOf(blockName, side, port, streamName) {
  const b = block(blockName);
  const list = asList((side === 'in' ? b.inlets : b.outlets)?.[port]);
  const i = list.indexOf(streamName);
  return [Math.max(i, 0), Math.max(list.length, 1)];
}

/** World geometry of the end of a stream at a port. */
export function streamEnd(streamName, end) {
  const s = streams()[streamName];
  const e = s && (end === 'src' ? s.src : s.dst);
  if (!e) return null;
  const b = block(e.block);
  const n = node(e.block);
  if (!b || !n) return null;
  const [slot, count] = slotOf(e.block, end === 'src' ? 'out' : 'in', e.port, streamName);
  return portGeometry(b.type, e.port, n, slot, count);
}

// --- undo / redo / autosave -------------------------------------------------------------

function snapshot() { return JSON.stringify(store.doc); }

/** Change the document. fn mutates a copy; `solve` says whether the model (not just the drawing) changed. */
export function change(fn, { solve = true, record = true } = {}) {
  const before = snapshot();
  const doc = JSON.parse(before);
  fn(doc);
  const after = JSON.stringify(doc);
  if (after === before) return false;
  if (record) {
    store.undo.push(before);
    if (store.undo.length > 150) store.undo.shift();
    store.redo = [];
  }
  store.doc = doc;
  pruneSelection();
  autosave();
  emit({ doc: true, solve });
  return true;
}

export function replaceDoc(doc, { record = true } = {}) {
  if (record) {
    store.undo.push(snapshot());
    store.redo = [];
  }
  store.doc = normalise(doc);
  store.results = null;
  store.selection = { nodes: new Set(), streams: new Set() };
  autosave();
  emit({ doc: true, solve: true, replaced: true });
}

export function undo() {
  if (!store.undo.length) return;
  store.redo.push(snapshot());
  store.doc = JSON.parse(store.undo.pop());
  pruneSelection();
  autosave();
  emit({ doc: true, solve: true });
}

export function redo() {
  if (!store.redo.length) return;
  store.undo.push(snapshot());
  store.doc = JSON.parse(store.redo.pop());
  pruneSelection();
  autosave();
  emit({ doc: true, solve: true });
}

function autosave() {
  try { localStorage.setItem(AUTOSAVE_KEY, snapshot()); } catch (e) { /* storage full or unavailable */ }
}

export function autosaveNow() { autosave(); }

export function restoreAutosave() {
  try {
    const text = localStorage.getItem(AUTOSAVE_KEY);
    if (text) return normalise(JSON.parse(text));
  } catch (e) { /* ignore */ }
  return null;
}

export function normalise(doc) {
  const d = { ...emptyDoc(), ...doc };
  d.layout = { nodes: {}, streams: {}, ...(doc.layout || {}) };
  d.layout.nodes = { ...(d.layout.nodes || {}) };
  d.layout.streams = { ...(d.layout.streams || {}) };
  d.blocks = (d.blocks || []).map((b) => ({ inlets: {}, outlets: {}, params: {}, ...b }));
  let x = 140;
  for (const b of d.blocks) {
    if (!d.layout.nodes[b.name]) { d.layout.nodes[b.name] = { x, y: 120, rot: 0, flip: false }; x += 180; }
  }
  return d;
}

// --- selection ----------------------------------------------------------------------------

export function select(nodes = [], strms = [], additive = false) {
  if (!additive) store.selection = { nodes: new Set(), streams: new Set() };
  nodes.forEach((n) => store.selection.nodes.add(n));
  strms.forEach((s) => store.selection.streams.add(s));
  emit({ selection: true });
}

export function toggleSelect(kind, name) {
  const set = kind === 'node' ? store.selection.nodes : store.selection.streams;
  if (set.has(name)) set.delete(name); else set.add(name);
  emit({ selection: true });
}

function pruneSelection() {
  const names = new Set(store.doc.blocks.map((b) => b.name));
  const strm = streams();
  for (const n of [...store.selection.nodes]) if (!names.has(n)) store.selection.nodes.delete(n);
  for (const s of [...store.selection.streams]) if (!strm[s]) store.selection.streams.delete(s);
}

// --- naming ---------------------------------------------------------------------------------

export function uniqueBlockName(type, doc = store.doc) {
  const prefix = TAG_PREFIX[type] || 'U-';
  const used = new Set(doc.blocks.map((b) => b.name));
  for (let i = 101; i < 100000; i++) {
    const name = `${prefix}${i}`;
    if (!used.has(name)) return name;
  }
  return `${prefix}${Date.now()}`;
}

export function uniqueStreamName(doc = store.doc, base = 'S') {
  const used = new Set(Object.keys(streams(doc)));
  for (let i = 1; i < 100000; i++) {
    const name = `${base}${i}`;
    if (!used.has(name)) return name;
  }
  return `${base}${Date.now()}`;
}

function defaultParams(type) {
  const t = store.types[type];
  const p = {};
  for (const prm of t.params) p[prm.key] = JSON.parse(JSON.stringify(prm.default));
  return p;
}

// --- edits (each takes a document copy `d` inside change()) --------------------------------------

export function addBlock(d, type, x, y, name = null) {
  const nm = name || uniqueBlockName(type, d);
  const t = store.types[type];
  const b = { type, name: nm, inlets: {}, outlets: {}, params: defaultParams(type) };
  if (t.outlets.some((p) => p.with_specs)) b.params.outlet_specs = {};
  d.blocks.push(b);
  d.layout.nodes[nm] = { x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, rot: 0, flip: false };
  return b;
}

function portDef(d, blockName, side, port) {
  const b = d.blocks.find((x) => x.name === blockName);
  const t = store.types[b.type];
  return (side === 'in' ? t.inlets : t.outlets).find((p) => p.key === port);
}

function getList(b, side, port) { return asList((side === 'in' ? b.inlets : b.outlets)[port]); }

function setPort(b, side, port, def, names) {
  const target = side === 'in' ? b.inlets : b.outlets;
  if (def.multiple) target[port] = names;
  else if (names.length) target[port] = names[0];
  else delete target[port];
}

/**
 * Connect an outlet to an inlet. Returns an error message or the stream name.
 * If the outlet already has a stream going nowhere, that stream is reused.
 */
export function connect(d, src, dst) {
  if (src.block === dst.block) return { error: 'A unit cannot be connected to itself.' };
  const sb = d.blocks.find((b) => b.name === src.block);
  const db = d.blocks.find((b) => b.name === dst.block);
  const sdef = portDef(d, src.block, 'out', src.port);
  const ddef = portDef(d, dst.block, 'in', dst.port);
  const all = streams(d);
  const outList = getList(sb, 'out', src.port);
  const inList = getList(db, 'in', dst.port);
  if (!ddef.multiple && inList.length) return { error: `${ddef.label} of ${db.name} is already connected.` };
  let name = null;
  if (!sdef.multiple && outList.length) {
    const existing = outList[0];
    if (all[existing]?.dst) return { error: `${sdef.label} of ${sb.name} is already connected.` };
    name = existing; // reuse the dangling outlet stream
    delete d.layout.streams[name]?.end;
  } else {
    name = uniqueStreamName(d);
    setPort(sb, 'out', src.port, sdef, [...outList, name]);
    addOutletSpec(sb, sdef, name);
  }
  setPort(db, 'in', dst.port, ddef, [...inList, name]);
  return { name };
}

function addOutletSpec(b, def, name) {
  if (!def.with_specs) return;
  b.params.outlet_specs ||= {};
  const specs = b.params.outlet_specs;
  const hasRemainder = Object.values(specs).some((s) => s.mode === 'Remainder');
  specs[name] = b.type === 'splitter' && !hasRemainder ? { mode: 'Remainder', value: 0 } : { mode: 'As required', value: 0 };
}

/** New outlet stream that leaves the system (ends at x, y). */
export function addProductStream(d, src, x, y) {
  const sb = d.blocks.find((b) => b.name === src.block);
  const sdef = portDef(d, src.block, 'out', src.port);
  const outList = getList(sb, 'out', src.port);
  if (!sdef.multiple && outList.length) return { error: `${sdef.label} of ${sb.name} already has a stream.` };
  const name = uniqueStreamName(d);
  setPort(sb, 'out', src.port, sdef, [...outList, name]);
  addOutletSpec(sb, sdef, name);
  d.layout.streams[name] = { ...(d.layout.streams[name] || {}), end: { x, y } };
  return { name };
}

/** Disconnect a stream from its destination (it then leaves the system) or delete it entirely. */
export function deleteStream(d, name) {
  for (const b of d.blocks) {
    for (const side of ['inlets', 'outlets']) {
      for (const [port, v] of Object.entries(b[side])) {
        if (Array.isArray(v)) b[side][port] = v.filter((n) => n !== name);
        else if (v === name) delete b[side][port];
      }
    }
    if (b.params.outlet_specs) delete b.params.outlet_specs[name];
    for (const key of ['balancing_inlet', 'makeup_inlet', 'stream', 'target_stream']) {
      if (b.params[key] === name) b.params[key] = '';
    }
  }
  delete d.layout.streams[name];
}

export function deleteBlocks(d, names) {
  const set = new Set(names);
  const strm = streams(d);
  // streams entirely internal to deleted blocks vanish; others lose that end
  for (const [sn, s] of Object.entries(strm)) {
    const srcGone = s.src && set.has(s.src.block);
    const dstGone = s.dst && set.has(s.dst.block);
    if (srcGone && (dstGone || !s.dst)) delete d.layout.streams[sn];
    else if (srcGone && s.dst) {
      // the downstream unit keeps an inlet with no supply; remove it so the flowsheet stays valid
      deleteStream(d, sn);
    } else if (dstGone && s.src) {
      const a = streamEndOf(d, sn, 'src');
      d.layout.streams[sn] = { end: a ? { x: a.x + a.dx * 70, y: a.y + a.dy * 70 } : { x: 0, y: 0 } };
    }
  }
  d.blocks = d.blocks.filter((b) => !set.has(b.name));
  for (const n of names) delete d.layout.nodes[n];
  for (const b of d.blocks) {
    for (const key of ['var_block', 'target_block']) if (set.has(b.params[key])) b.params[key] = '';
  }
}

function streamEndOf(d, streamName, end) {
  const s = streams(d)[streamName];
  const e = s && s[end];
  if (!e) return null;
  const b = d.blocks.find((x) => x.name === e.block);
  const n = d.layout.nodes[e.block];
  if (!b || !n) return null;
  const list = asList((end === 'src' ? b.outlets : b.inlets)[e.port]);
  return portGeometry(b.type, e.port, n, Math.max(list.indexOf(streamName), 0), Math.max(list.length, 1));
}

export function renameBlock(d, oldName, newName) {
  if (!newName || oldName === newName) return null;
  if (d.blocks.some((b) => b.name === newName)) return `There is already a unit called "${newName}".`;
  const b = d.blocks.find((x) => x.name === oldName);
  b.name = newName;
  d.layout.nodes[newName] = d.layout.nodes[oldName];
  delete d.layout.nodes[oldName];
  for (const o of d.blocks) {
    for (const key of ['var_block', 'target_block']) if (o.params[key] === oldName) o.params[key] = newName;
  }
  return null;
}

export function renameStream(d, oldName, newName) {
  if (!newName || oldName === newName) return null;
  if (streams(d)[newName]) return `There is already a stream called "${newName}".`;
  for (const b of d.blocks) {
    for (const side of ['inlets', 'outlets']) {
      for (const [port, v] of Object.entries(b[side])) {
        if (Array.isArray(v)) b[side][port] = v.map((n) => (n === oldName ? newName : n));
        else if (v === oldName) b[side][port] = newName;
      }
    }
    const specs = b.params.outlet_specs;
    if (specs && specs[oldName]) { specs[newName] = specs[oldName]; delete specs[oldName]; }
    for (const key of ['balancing_inlet', 'makeup_inlet', 'stream', 'target_stream']) {
      if (b.params[key] === oldName) b.params[key] = newName;
    }
  }
  if (d.layout.streams[oldName]) { d.layout.streams[newName] = d.layout.streams[oldName]; delete d.layout.streams[oldName]; }
  if (d.estimates?.[oldName]) { d.estimates[newName] = d.estimates[oldName]; delete d.estimates[oldName]; }
  return null;
}

/** Insert a unit (e.g. a pipe or valve) part-way along a stream. */
export function insertInline(d, streamName, type) {
  const s = streams(d)[streamName];
  if (!s || !s.src) return { error: 'Stream not found.' };
  const t = store.types[type];
  const inPort = t.inlets[0].key;
  const outPort = t.outlets[0].key;
  const a = streamEndOf(d, streamName, 'src');
  const bEnd = s.dst ? streamEndOf(d, streamName, 'dst') : d.layout.streams[streamName]?.end || { x: a.x + 120, y: a.y };
  const x = (a.x + bEnd.x) / 2;
  const y = (a.y + bEnd.y) / 2;
  const blk = addBlock(d, type, x, y);
  const newName = uniqueStreamName(d);
  // the original stream now ends at the new unit; a new stream continues to the old destination
  if (s.dst) {
    const db = d.blocks.find((b) => b.name === s.dst.block);
    const ddef = portDef(d, s.dst.block, 'in', s.dst.port);
    const list = getList(db, 'in', s.dst.port).map((n) => (n === streamName ? newName : n));
    setPort(db, 'in', s.dst.port, ddef, list);
    for (const o of d.blocks) {
      for (const key of ['balancing_inlet', 'makeup_inlet']) if (o === db && o.params[key] === streamName) o.params[key] = newName;
    }
  } else {
    d.layout.streams[newName] = { end: bEnd };
    delete d.layout.streams[streamName];
  }
  blk.inlets[inPort] = streamName;
  blk.outlets[outPort] = newName;
  return { block: blk.name, stream: newName };
}

/** Add a relief valve that protects a stream, drawn just above its label. */
export function addReliefValve(d, streamName, x, y) {
  const blk = addBlock(d, 'relief_valve', x, y);
  blk.params.stream = streamName;
  blk.params.tag = blk.name;
  return blk;
}

/** Copy the selected units (and streams between them) to a clipboard object. */
export function copySelection() {
  const names = [...store.selection.nodes];
  if (!names.length) return null;
  const set = new Set(names);
  const blocks = store.doc.blocks.filter((b) => set.has(b.name)).map((b) => JSON.parse(JSON.stringify(b)));
  const strm = streams();
  const internal = new Set(Object.entries(strm).filter(([, s]) => s.src && s.dst && set.has(s.src.block) && set.has(s.dst.block)).map(([n]) => n));
  for (const b of blocks) {
    for (const side of ['inlets', 'outlets']) {
      for (const [port, v] of Object.entries(b[side])) {
        if (Array.isArray(v)) b[side][port] = v.filter((n) => internal.has(n));
        else if (!internal.has(v)) delete b[side][port];
      }
    }
    if (b.params.outlet_specs) {
      for (const k of Object.keys(b.params.outlet_specs)) if (!internal.has(k)) delete b.params.outlet_specs[k];
    }
  }
  const nodes = Object.fromEntries(names.map((n) => [n, { ...store.doc.layout.nodes[n] }]));
  return { blocks, nodes, internal: [...internal] };
}

export function paste(d, clip, dx = 40, dy = 40) {
  const nameMap = {};
  const streamMap = {};
  for (const sn of clip.internal) streamMap[sn] = null;
  const created = [];
  for (const b of clip.blocks) {
    const nb = JSON.parse(JSON.stringify(b));
    nb.name = uniqueBlockName(b.type, d);
    nameMap[b.name] = nb.name;
    d.blocks.push(nb);
    const n = clip.nodes[b.name];
    d.layout.nodes[nb.name] = { ...n, x: n.x + dx, y: n.y + dy };
    created.push(nb);
  }
  // allocate new stream names one by one so they stay unique
  const used = new Set(Object.keys(streams(d)));
  let i = 1;
  for (const sn of Object.keys(streamMap)) {
    while (used.has(`S${i}`)) i++;
    streamMap[sn] = `S${i}`;
    used.add(`S${i}`);
  }
  for (const nb of created) {
    for (const side of ['inlets', 'outlets']) {
      for (const [port, v] of Object.entries(nb[side])) {
        nb[side][port] = Array.isArray(v) ? v.map((n) => streamMap[n]) : streamMap[v];
      }
    }
    if (nb.params.outlet_specs) {
      nb.params.outlet_specs = Object.fromEntries(Object.entries(nb.params.outlet_specs).map(([k, v]) => [streamMap[k], v]));
    }
    for (const key of ['balancing_inlet', 'makeup_inlet']) if (nb.params[key]) nb.params[key] = streamMap[nb.params[key]] || '';
    for (const key of ['var_block', 'target_block']) if (nameMap[nb.params[key]]) nb.params[key] = nameMap[nb.params[key]];
  }
  return created.map((b) => b.name);
}

export function nodeTypeDims(name) {
  const b = block(name);
  return b ? symbol(b.type) : null;
}
