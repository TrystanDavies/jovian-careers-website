// Thin wrappers around the server's JSON API.

async function handle(res) {
  if (res.ok) {
    const type = res.headers.get('content-type') || '';
    return type.includes('application/json') ? res.json() : res.text();
  }
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
  } catch (e) { /* not JSON */ }
  throw new Error(detail);
}

export async function get(path) {
  return handle(await fetch(path));
}

export async function post(path, body) {
  return handle(await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
}
