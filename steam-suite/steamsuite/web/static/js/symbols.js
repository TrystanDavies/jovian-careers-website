// P&ID symbols. Each symbol is drawn in a local box (0..w, 0..h). Ports sit on the
// box edges: side l/r/t/b and a position t (0–1) along that side. Ports that take
// several streams have a span t0–t1; connected streams are spread along it.

const S = 'class="sym"';
const SF = 'class="sym-fill"';
const ST = 'class="sym-thin"';

export const SYMBOLS = {
  feed: {
    w: 72, h: 34,
    draw: () => `<path ${SF} d="M1 1 H55 L71 17 L55 33 H1 Z"/><path ${ST} d="M12 17 H44 M36 11 L44 17 L36 23"/>`,
    ports: { out: { side: 'r', t: 0.5 } },
  },
  pump: {
    w: 58, h: 56,
    draw: () => `<rect ${S} x="28" y="5" width="29" height="10"/><circle ${S} cx="28" cy="31" r="23"/>
      <path ${ST} d="M15 19 L44 31 L15 43"/><path ${S} d="M12 54 L44 54 L38 47 L18 47 Z"/>`,
    ports: { in: { side: 'l', t: 31 / 56 }, out: { side: 'r', t: 10 / 56 } },
  },
  compressor: {
    w: 60, h: 52,
    draw: () => `<path ${S} d="M1 1 L59 13 L59 39 L1 51 Z"/><path ${ST} d="M14 26 H46"/>`,
    ports: { in: { side: 'l', t: 0.5 }, out: { side: 'r', t: 0.5 } },
  },
  turbine: {
    w: 62, h: 54,
    draw: () => `<path ${S} d="M1 14 L61 1 L61 53 L1 40 Z"/><path ${ST} d="M61 27 H62"/>
      <text x="31" y="31" text-anchor="middle" font-size="10" fill="#6f7d8b" style="pointer-events:none">T</text>`,
    ports: { in: { side: 'l', t: 0.5 }, out: { side: 'r', t: 0.5 } },
  },
  valve: {
    w: 44, h: 42,
    draw: () => `<path ${S} d="M1 23 L1 41 L22 32 Z M43 23 L43 41 L22 32 Z"/><path ${ST} d="M22 32 V12"/>
      <path ${S} d="M9 12 A13 11 0 0 1 35 12 Z"/>`,
    ports: { in: { side: 'l', t: 32 / 42 }, out: { side: 'r', t: 32 / 42 } },
  },
  boiler: {
    w: 76, h: 96,
    draw: () => `<rect ${S} x="8" y="26" width="60" height="66" rx="3"/><rect ${SF} x="1" y="5" width="74" height="22" rx="11"/>
      <path class="flame" d="M24 86 q6 -18 12 -4 q4 -14 10 -2 q4 -10 8 2"/>
      <path ${ST} d="M68 16 H76 M38 92 V96 M1 72 H8"/>`,
    ports: { in: { side: 'l', t: 72 / 96 }, steam: { side: 'r', t: 16 / 96 }, blowdown: { side: 'b', t: 0.5 } },
  },
  heater: {
    w: 52, h: 52,
    draw: () => `<circle ${S} cx="26" cy="26" r="23"/><path ${ST} d="M1 26 H12 L17 15 L24 37 L31 15 L36 37 L40 26 H51" style="stroke:#33404d;stroke-width:1.4"/>`,
    ports: { in: { side: 'l', t: 0.5 }, out: { side: 'r', t: 0.5 } },
  },
  condenser: {
    w: 92, h: 54,
    draw: () => `<rect ${S} x="1" y="9" width="90" height="36" rx="18"/><path ${ST} d="M14 21 H78 M14 27 H78 M14 33 H78"/>
      <path ${ST} d="M46 1 V9 M46 45 V53"/>`,
    ports: { in: { side: 't', t: 0.5 }, out: { side: 'b', t: 0.5 } },
  },
  heat_exchanger: {
    w: 104, h: 54,
    draw: () => `<rect ${S} x="10" y="9" width="84" height="36" rx="5"/><rect ${SF} x="1" y="13" width="10" height="28" rx="2"/>
      <rect ${SF} x="93" y="13" width="10" height="28" rx="2"/><path ${ST} d="M11 20 H93 M11 27 H93 M11 34 H93"/>
      <path ${ST} d="M26 1 V9 M78 45 V53"/>`,
    ports: { hot_in: { side: 't', t: 0.25 }, hot_out: { side: 'b', t: 0.75 }, cold_in: { side: 'l', t: 0.5 }, cold_out: { side: 'r', t: 0.5 } },
  },
  mixer: {
    w: 36, h: 40,
    draw: () => `<path ${SF} d="M1 1 L35 20 L1 39 Z"/>`,
    ports: { in: { side: 'l', t0: 0.15, t1: 0.85 }, out: { side: 'r', t: 0.5 } },
  },
  splitter: {
    w: 36, h: 40,
    draw: () => `<path ${SF} d="M35 1 L1 20 L35 39 Z"/>`,
    ports: { in: { side: 'l', t: 0.5 }, out: { side: 'r', t0: 0.15, t1: 0.85 } },
  },
  header: {
    w: 170, h: 22,
    draw: () => `<rect ${SF} x="1" y="4" width="168" height="14" rx="7"/>`,
    ports: { in: { side: 't', t0: 0.06, t1: 0.46 }, out: { side: 'b', t0: 0.12, t1: 0.94 } },
  },
  flash: {
    w: 48, h: 92,
    draw: () => `<rect ${S} x="4" y="1" width="40" height="90" rx="20"/><path ${ST} d="M6 62 H42"/>
      <path d="M6 62 H42 V71 Q24 92 6 71 Z" fill="#dce8f6" stroke="none"/>`,
    ports: { in: { side: 'l', t: 0.42 }, vapour: { side: 't', t: 0.5 }, liquid: { side: 'b', t: 0.5 } },
  },
  desuperheater: {
    w: 72, h: 38,
    draw: () => `<rect ${S} x="1" y="17" width="70" height="16" rx="3"/><path ${ST} d="M36 1 V17"/>
      <path ${ST} d="M31 21 l-5 7 M36 21 v8 M41 21 l5 7" style="stroke:#2c6cb3"/>`,
    ports: { steam: { side: 'l', t: 25 / 38 }, water: { side: 't', t: 0.5 }, out: { side: 'r', t: 25 / 38 } },
  },
  deaerator: {
    w: 114, h: 96,
    draw: () => `<rect ${S} x="24" y="1" width="32" height="52" rx="8"/><rect ${S} x="1" y="46" width="112" height="46" rx="23"/>
      <path ${ST} d="M1 24 H24 M28 1 V1"/><path d="M4 76 H110 V80 Q57 96 4 80 Z" fill="#dce8f6" stroke="none"/>`,
    ports: { steam: { side: 'l', t: 24 / 96 }, water: { side: 't', t0: 0.24, t1: 0.4 }, vent: { side: 't', t: 0.46 }, out: { side: 'b', t: 0.6 } },
  },
  steam_user: {
    w: 74, h: 52,
    draw: () => `<rect ${S} x="1" y="1" width="72" height="50" rx="4"/>
      <path ${ST} d="M12 16 L20 36 L28 16 L36 36 L44 16 L52 36 L60 16" style="stroke:#cf3e4f;stroke-width:1.4"/>`,
    ports: { in: { side: 'l', t: 0.3 }, condensate: { side: 'b', t: 0.35 }, loss: { side: 'b', t: 0.8 } },
  },
  pipe: {
    w: 84, h: 18,
    draw: () => `<path d="M1 9 H83" style="stroke:#6c7a88;stroke-width:6;stroke-linecap:butt"/>
      <path ${S} d="M7 2 V16 M77 2 V16" style="stroke-width:2.4"/><rect class="hit" x="0" y="0" width="84" height="18"/>`,
    ports: { in: { side: 'l', t: 0.5 }, out: { side: 'r', t: 0.5 } },
  },
  relief_valve: {
    w: 42, h: 52,
    draw: () => `<path ${S} d="M12 51 L30 51 L21 32 Z"/><path ${S} d="M41 23 L41 41 L21 32 Z"/>
      <path ${ST} d="M21 32 V25 l-6 -3 l12 -4 l-12 -4 l12 -4 l-6 -3 V2" style="stroke:#33404d;stroke-width:1.3"/>
      <rect ${SF} x="15" y="0" width="12" height="4" rx="1"/>`,
    ports: {},
    anchor: { x: 21, y: 51 },
  },
  adjust: {
    w: 42, h: 42,
    draw: () => `<circle ${S} cx="21" cy="21" r="19" style="stroke-dasharray:4 2"/>
      <text x="21" y="25" text-anchor="middle" font-size="11" font-weight="700" fill="#33404d" style="pointer-events:none">ADJ</text>`,
    ports: {},
    anchor: { x: 21, y: 21 },
  },
};

const FALLBACK = { w: 60, h: 40, draw: () => `<rect ${S} x="1" y="1" width="58" height="38" rx="4"/>`, ports: {} };

export function symbol(type) { return SYMBOLS[type] || FALLBACK; }

/** Small SVG for the palette. */
export function paletteIcon(type) {
  const s = symbol(type);
  const pad = 3;
  return `<svg viewBox="${-pad} ${-pad} ${s.w + 2 * pad} ${s.h + 2 * pad}" preserveAspectRatio="xMidYMid meet">${s.draw()}</svg>`;
}

const SIDE_DIR = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] };

/** Rotate/flip a vector given in symbol-local coordinates. */
export function transformVec(dx, dy, rot = 0, flip = false) {
  let x = flip ? -dx : dx;
  let y = dy;
  const a = ((rot || 0) * Math.PI) / 180;
  const c = Math.round(Math.cos(a) * 1e6) / 1e6;
  const s = Math.round(Math.sin(a) * 1e6) / 1e6;
  return [x * c - y * s, x * s + y * c];
}

/** Local point on a side at fraction t. */
export function sidePoint(sym, side, t) {
  switch (side) {
    case 'l': return [0, t * sym.h];
    case 'r': return [sym.w, t * sym.h];
    case 't': return [t * sym.w, 0];
    default: return [t * sym.w, sym.h];
  }
}

/** World position and outward direction of a port (slot i of n for multi-ports). */
export function portGeometry(type, portKey, node, slot = 0, nSlots = 1) {
  const sym = symbol(type);
  const p = sym.ports[portKey];
  if (!p) return null;
  let t = p.t;
  if (p.t0 !== undefined) t = p.t0 + ((p.t1 - p.t0) * (slot + 0.5)) / Math.max(nSlots, 1);
  const [lx, ly] = sidePoint(sym, p.side, t);
  const [wx, wy] = transformVec(lx - sym.w / 2, ly - sym.h / 2, node.rot, node.flip);
  const [dx, dy] = transformVec(...SIDE_DIR[p.side], node.rot, node.flip);
  return { x: node.x + wx, y: node.y + wy, dx: Math.round(dx), dy: Math.round(dy) };
}

/** Both ends of a multi-port span in world coordinates (for drawing and hit-testing). */
export function portSpan(type, portKey, node) {
  const sym = symbol(type);
  const p = sym.ports[portKey];
  if (!p || p.t0 === undefined) return null;
  const pts = [p.t0, p.t1].map((t) => {
    const [lx, ly] = sidePoint(sym, p.side, t);
    const [wx, wy] = transformVec(lx - sym.w / 2, ly - sym.h / 2, node.rot, node.flip);
    return [node.x + wx, node.y + wy];
  });
  return pts;
}

/** World point of a symbol's anchor (for dashed information links). */
export function anchorPoint(type, node) {
  const sym = symbol(type);
  const a = sym.anchor || { x: sym.w / 2, y: sym.h / 2 };
  const [wx, wy] = transformVec(a.x - sym.w / 2, a.y - sym.h / 2, node.rot, node.flip);
  return [node.x + wx, node.y + wy];
}

/** Axis-aligned bounding box of a node (after rotation). */
export function nodeBox(type, node) {
  const sym = symbol(type);
  const rotated = ((node.rot || 0) / 90) % 2 === 1;
  const w = rotated ? sym.h : sym.w;
  const hgt = rotated ? sym.w : sym.h;
  return { x0: node.x - w / 2, y0: node.y - hgt / 2, x1: node.x + w / 2, y1: node.y + hgt / 2, w, h: hgt };
}

// Default tag prefixes, P&ID style
export const TAG_PREFIX = {
  feed: 'IN-', pump: 'P-', compressor: 'K-', turbine: 'T-', valve: 'V-', boiler: 'B-', heater: 'E-',
  condenser: 'C-', heat_exchanger: 'E-', mixer: 'MIX-', splitter: 'TEE-', header: 'HDR-', flash: 'V-',
  desuperheater: 'DSH-', deaerator: 'D-', steam_user: 'U-', pipe: 'L-', relief_valve: 'PSV-', adjust: 'ADJ-',
};
