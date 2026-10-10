// Unit conversions. Internal (server) units: kPa(a), °C, kg/s, kJ/kg, kJ/(kg·K), kW,
// kg/m³, m, mm, m³/h, m/s, mm², kW/K. The user picks a preset; values are converted
// for display and converted back when edited.

export const P_ATM = 101.325;

const PF = { kPa: 1, bar: 100, MPa: 1000, psi: 6.894757293168361 };

function splitP(u) {
  if (u === 'psig') return ['psi', true];
  if (u === 'psia') return ['psi', false];
  if (u.endsWith('(g)')) return [u.slice(0, -3), true];
  if (u.endsWith('(a)')) return [u.slice(0, -3), false];
  return [u, false];
}

// factor = internal units per display unit
const F = {
  mass_flow: { 't/h': 1 / 3.6, 'kg/h': 1 / 3600, 'kg/s': 1, 'lb/h': 0.45359237 / 3600 },
  power: { kW: 1, MW: 1000, hp: 0.745699872, 'Btu/h': 0.00029307107 },
  enthalpy: { 'kJ/kg': 1, 'Btu/lb': 2.326 },
  entropy: { 'kJ/(kg·K)': 1, 'Btu/(lb·°F)': 4.1868 },
  density: { 'kg/m³': 1, 'lb/ft³': 16.018463 },
  length: { m: 1, ft: 0.3048 },
  diameter: { mm: 1, in: 25.4 },
  head: { m: 1, ft: 0.3048 },
  volume_flow: { 'm³/h': 1, gpm: 0.2271247 },
  velocity: { 'm/s': 1, 'ft/s': 0.3048 },
  area: { 'mm²': 1, 'cm²': 100, 'in²': 645.16 },
  ua: { 'kW/K': 1, 'Btu/(h·°F)': 0.00052752793 },
};

export const PRESETS = {
  metric: {
    label: 'Metric (bar g, °C, t/h)', pressure: 'bar(g)', temperature: '°C', mass_flow: 't/h', power: 'kW',
    enthalpy: 'kJ/kg', entropy: 'kJ/(kg·K)', density: 'kg/m³', length: 'm', diameter: 'mm', head: 'm',
    volume_flow: 'm³/h', velocity: 'm/s', area: 'mm²', ua: 'kW/K',
  },
  metric_abs: {
    label: 'Metric absolute (bar a, °C, t/h)', pressure: 'bar(a)', temperature: '°C', mass_flow: 't/h', power: 'kW',
    enthalpy: 'kJ/kg', entropy: 'kJ/(kg·K)', density: 'kg/m³', length: 'm', diameter: 'mm', head: 'm',
    volume_flow: 'm³/h', velocity: 'm/s', area: 'mm²', ua: 'kW/K',
  },
  si: {
    label: 'SI (kPa a, °C, kg/s)', pressure: 'kPa(a)', temperature: '°C', mass_flow: 'kg/s', power: 'kW',
    enthalpy: 'kJ/kg', entropy: 'kJ/(kg·K)', density: 'kg/m³', length: 'm', diameter: 'mm', head: 'm',
    volume_flow: 'm³/h', velocity: 'm/s', area: 'mm²', ua: 'kW/K',
  },
  us: {
    label: 'US customary (psig, °F, lb/h)', pressure: 'psig', temperature: '°F', mass_flow: 'lb/h', power: 'Btu/h',
    enthalpy: 'Btu/lb', entropy: 'Btu/(lb·°F)', density: 'lb/ft³', length: 'ft', diameter: 'in', head: 'ft',
    volume_flow: 'gpm', velocity: 'ft/s', area: 'in²', ua: 'Btu/(h·°F)',
  },
};

let current = { ...PRESETS.metric, key: 'metric' };
const listeners = new Set();

export function setPreset(key) {
  current = { ...(PRESETS[key] || PRESETS.metric), key: PRESETS[key] ? key : 'metric' };
  try { localStorage.setItem('steamsuite.units', current.key); } catch (e) { /* ignore */ }
  listeners.forEach((fn) => fn(current));
}
export function units() { return current; }
export function onUnitsChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function initUnits() {
  let key = 'metric';
  try { key = localStorage.getItem('steamsuite.units') || 'metric'; } catch (e) { /* ignore */ }
  current = { ...(PRESETS[key] || PRESETS.metric), key: PRESETS[key] ? key : 'metric' };
}

export function gaugeUnit(u = current.pressure) {
  const [base] = splitP(u);
  return base === 'psi' ? 'psig' : `${base}(g)`;
}
export function absUnit(u = current.pressure) {
  const [base] = splitP(u);
  return base === 'psi' ? 'psia' : `${base}(a)`;
}
export function diffUnit(u = current.pressure) { return splitP(u)[0]; }

function tToUser(v, u) { return u === '°F' ? v * 9 / 5 + 32 : u === 'K' ? v + 273.15 : v; }
function tFromUser(v, u) { return u === '°F' ? (v - 32) * 5 / 9 : u === 'K' ? v - 273.15 : v; }

/** Unit label shown for a kind of quantity. */
export function unitLabel(kind, opts = {}) {
  const u = current;
  switch (kind) {
    case 'pressure': return opts.gauge ? gaugeUnit() : opts.abs ? absUnit() : u.pressure;
    case 'pressure_diff': return diffUnit();
    case 'temperature': return u.temperature;
    case 'temperature_diff': return u.temperature === '°F' ? '°F' : u.temperature === 'K' ? 'K' : '°C';
    case 'percent': return '%';
    case 'roughness': return u.diameter;
    case 'htc': return 'W/(m²·K)';
    case 'conductivity': return 'W/(m·K)';
    default: return u[kind] || '';
  }
}

/** Internal value -> display value. */
export function toUser(kind, v, opts = {}) {
  if (v === null || v === undefined || typeof v !== 'number' || !isFinite(v)) return v;
  const u = current;
  switch (kind) {
    case 'pressure': {
      const unit = opts.gauge ? gaugeUnit() : opts.abs ? absUnit() : u.pressure;
      const [base, gauge] = splitP(unit);
      return (gauge ? v - P_ATM : v) / PF[base];
    }
    case 'pressure_diff': return v / PF[diffUnit()];
    case 'temperature': return tToUser(v, u.temperature);
    case 'temperature_diff': return u.temperature === '°F' ? v * 1.8 : v;
    case 'roughness': return v / F.diameter[u.diameter];
    default:
      if (F[kind]) return v / F[kind][u[kind]];
      return v;
  }
}

/** Display value -> internal value. */
export function fromUser(kind, v, opts = {}) {
  if (v === null || v === undefined || typeof v !== 'number' || !isFinite(v)) return v;
  const u = current;
  switch (kind) {
    case 'pressure': {
      const unit = opts.gauge ? gaugeUnit() : opts.abs ? absUnit() : u.pressure;
      const [base, gauge] = splitP(unit);
      return v * PF[base] + (gauge ? P_ATM : 0);
    }
    case 'pressure_diff': return v * PF[diffUnit()];
    case 'temperature': return tFromUser(v, u.temperature);
    case 'temperature_diff': return u.temperature === '°F' ? v / 1.8 : v;
    case 'roughness': return v * F.diameter[u.diameter];
    default:
      if (F[kind]) return v * F[kind][u[kind]];
      return v;
  }
}

/** Format a number to about `sig` significant figures (no scientific notation for everyday sizes). */
export function fmt(v, sig = 4) {
  if (v === null || v === undefined || (typeof v === 'number' && !isFinite(v))) return '—';
  if (typeof v !== 'number') return String(v);
  if (v === 0) return '0';
  const mag = Math.floor(Math.log10(Math.abs(v)));
  if (mag >= 9 || mag <= -5) return v.toExponential(sig - 1);
  const decimals = Math.max(0, sig - 1 - mag);
  return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Display string "value unit" for an internal value of a kind. */
export function show(kind, v, sig = 4, opts = {}) {
  if (kind === 'text') return String(v);
  if (v === null || v === undefined) return '—';
  const lab = unitLabel(kind, opts);
  const val = fmt(toUser(kind, v, opts), sig);
  return lab ? `${val} ${lab}` : val;
}

/** Number shown in an input box (more digits, no thousands separators). */
export function inputValue(kind, v, opts = {}) {
  const x = toUser(kind, v, opts);
  if (typeof x !== 'number' || !isFinite(x)) return '';
  return String(parseFloat(x.toPrecision(7)));
}

/** Plain-language description of a state (from the server's state dict), in the user's units. */
export function describeState(st) {
  if (!st || !st.known && st.known !== undefined) return '—';
  const dt = (v) => `${fmt(toUser('temperature_diff', v), 3)} ${unitLabel('temperature_diff')}`;
  switch (st.phase) {
    case 'liquid':
      if (st.P >= 22064) return 'Compressed water (above critical pressure)';
      if (st.subcooling === null || st.subcooling === undefined) return 'Water';
      if (st.subcooling < 0.05) return 'Saturated water (at boiling point)';
      return `Subcooled water (${dt(st.subcooling)} below boiling)`;
    case 'saturated liquid': return 'Saturated water (at boiling point)';
    case 'two-phase': return `Wet steam (dryness ${st.x < 0.01 || st.x > 0.99 ? st.x.toFixed(4) : st.x.toFixed(3)})`;
    case 'saturated vapour': return 'Dry saturated steam';
    case 'vapour':
      if (st.superheat === null || st.superheat === undefined) return 'Steam';
      if (st.superheat < 0.05) return 'Dry saturated steam';
      return `Superheated steam (${dt(st.superheat)} superheat)`;
    case 'supercritical': return 'Supercritical fluid';
    default: return st.phase || '—';
  }
}

export const NUMERIC_KINDS = new Set(['pressure', 'pressure_diff', 'temperature', 'temperature_diff', 'mass_flow',
  'power', 'percent', 'fraction', 'number', 'length', 'diameter', 'roughness', 'head', 'volume_flow', 'ua', 'htc',
  'conductivity', 'velocity', 'area', 'enthalpy', 'entropy', 'density']);
