// Small DOM helpers.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function toast(text, kind = '') {
  const root = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind}` }, text);
  root.append(el);
  setTimeout(() => el.remove(), kind === 'err' ? 6000 : 3200);
}

export function modal(title, content, buttons = []) {
  const root = document.getElementById('modal-root');
  const close = () => { backdrop.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const footer = h('footer', {}, ...buttons.map((b) => h('button', {
    class: `btn ${b.primary ? 'primary' : ''}`,
    onclick: () => { if (b.onClick) { if (b.onClick(close) !== false) close(); } else close(); },
  }, b.label)));
  const box = h('div', { class: 'modal', role: 'dialog', 'aria-label': title },
    h('header', {}, h('h3', {}, title), h('button', { class: 'btn ghost', onclick: close, 'aria-label': 'Close' }, '✕')),
    h('div', { class: 'content' }, content),
    buttons.length ? footer : null);
  const backdrop = h('div', { class: 'modal-backdrop', onclick: (e) => { if (e.target === backdrop) close(); } }, box);
  root.append(backdrop);
  document.addEventListener('keydown', onKey);
  return close;
}

export function download(filename, text, mime = 'text/plain') {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
