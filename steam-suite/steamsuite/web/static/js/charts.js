// Minimal SVG line charts (no external library).

import { esc } from './dom.js';
import { fmt, toUser, unitLabel } from './units.js';

const COLORS = ['#cf3e4f', '#2c6cb3', '#23824f', '#a8650a', '#8a55c4'];

function niceStep(range, n) {
  const raw = range / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const f = raw / mag;
  const nice = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
  return nice * mag;
}

function ticks(min, max, n = 5) {
  if (!(max > min)) { max = min + 1; }
  const step = niceStep(max - min, n);
  const t0 = Math.ceil(min / step - 1e-9) * step;
  const out = [];
  for (let t = t0; t <= max + step * 1e-9; t += step) out.push(+t.toPrecision(12));
  return out;
}

/**
 * chart = {x, y, x_kind, y_kind, series: {name: [[x, y], ...]}}; values in internal units,
 * converted to the user's units with the kinds.
 */
export function lineChart(chart, { width = 340, height = 210, title = '' } = {}) {
  const conv = (kind, v) => (kind ? toUser(kind, v) : v);
  const series = Object.entries(chart.series || {}).map(([name, pts]) => [name, pts
    .filter((p) => p[0] !== null && p[1] !== null)
    .map(([x, y]) => [conv(chart.x_kind, x), conv(chart.y_kind, y)])]);
  const all = series.flatMap(([, pts]) => pts);
  if (!all.length) return '';
  const xlab = chart.x_kind ? `${chart.x.replace(/\s*\(.*\)$/, '')} (${unitLabel(chart.x_kind)})` : chart.x;
  const ylab = chart.y_kind ? `${chart.y.replace(/\s*\(.*\)$/, '')} (${unitLabel(chart.y_kind)})` : chart.y;
  let x0 = Math.min(...all.map((p) => p[0]));
  let x1 = Math.max(...all.map((p) => p[0]));
  let y0 = Math.min(...all.map((p) => p[1]));
  let y1 = Math.max(...all.map((p) => p[1]));
  if (x1 - x0 < 1e-12) { x0 -= 1; x1 += 1; }
  if (y1 - y0 < 1e-9 * Math.max(Math.abs(y1), 1)) { const d = Math.max(Math.abs(y1) * 0.01, 1e-6); y0 -= d; y1 += d; }
  const yt = ticks(y0, y1);
  const xt = ticks(x0, x1);
  y0 = Math.min(y0, yt[0]);
  y1 = Math.max(y1, yt[yt.length - 1]);
  const m = { l: 52, r: 12, t: title ? 22 : 10, b: 34 };
  const W = width - m.l - m.r;
  const H = height - m.t - m.b;
  const sx = (v) => m.l + ((v - x0) / (x1 - x0)) * W;
  const sy = (v) => m.t + H - ((v - y0) / (y1 - y0)) * H;
  let s = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title || ylab)}">`;
  if (title) s += `<text class="title" x="${m.l}" y="14">${esc(title)}</text>`;
  for (const t of yt) {
    s += `<line class="gridline" x1="${m.l}" x2="${m.l + W}" y1="${sy(t)}" y2="${sy(t)}"/>`;
    s += `<text x="${m.l - 6}" y="${sy(t) + 3.5}" text-anchor="end">${esc(fmt(t, 4))}</text>`;
  }
  for (const t of xt) {
    if (t < x0 - 1e-9 || t > x1 + 1e-9) continue;
    s += `<line class="axis" x1="${sx(t)}" x2="${sx(t)}" y1="${m.t + H}" y2="${m.t + H + 4}"/>`;
    s += `<text x="${sx(t)}" y="${m.t + H + 15}" text-anchor="middle">${esc(fmt(t, 4))}</text>`;
  }
  s += `<line class="axis" x1="${m.l}" x2="${m.l + W}" y1="${m.t + H}" y2="${m.t + H}"/>`;
  s += `<line class="axis" x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${m.t + H}"/>`;
  s += `<text x="${m.l + W / 2}" y="${height - 4}" text-anchor="middle">${esc(xlab)}</text>`;
  s += `<text x="12" y="${m.t + H / 2}" text-anchor="middle" transform="rotate(-90 12 ${m.t + H / 2})">${esc(ylab)}</text>`;
  series.forEach(([, pts], i) => {
    const d = pts.map((p, j) => `${j ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ');
    s += `<path class="series" d="${d}" stroke="${COLORS[i % COLORS.length]}"/>`;
    if (pts.length <= 25) for (const p of pts) s += `<circle cx="${sx(p[0])}" cy="${sy(p[1])}" r="2.4" fill="${COLORS[i % COLORS.length]}"/>`;
  });
  s += '</svg>';
  const legend = series.length > 1
    ? `<div class="legend">${series.map(([n], i) => `<span><i style="background:${COLORS[i % COLORS.length]}"></i>${esc(n)}</span>`).join('')}</div>`
    : '';
  return `<div class="chart">${s}${legend}</div>`;
}
