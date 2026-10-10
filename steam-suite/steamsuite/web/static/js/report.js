// Render step-by-step calculations (text, equations with KaTeX, tables).

import { h } from './dom.js';

export function renderMath(el, tex) {
  if (window.katex) {
    try {
      window.katex.render(tex, el, { displayMode: true, throwOnError: false, strict: 'ignore' });
      return;
    } catch (e) { /* fall through */ }
  }
  el.textContent = tex;
}

export function stepsView(steps, start = 1) {
  const root = h('div', { class: 'steps' });
  steps.forEach((s, i) => {
    const box = h('div', { class: 'step' }, h('h5', {}, `Step ${i + start}: ${s.title}`));
    if (s.text) box.append(h('p', {}, s.text));
    for (const eq of [s.equation, s.substitution, s.result]) {
      if (!eq) continue;
      const el = h('div', { class: 'eq' });
      renderMath(el, eq);
      box.append(el);
    }
    if (s.table && s.table.length) {
      const [head, ...rows] = s.table;
      box.append(h('table', { class: 'mini-table' },
        h('thead', {}, h('tr', {}, ...head.map((c) => h('th', {}, c)))),
        h('tbody', {}, ...rows.map((r) => h('tr', {}, ...r.map((c) => h('td', {}, c)))))));
    }
    if (s.reference) box.append(h('div', { class: 'ref' }, `Reference: ${s.reference}`));
    root.append(box);
  });
  return root;
}
