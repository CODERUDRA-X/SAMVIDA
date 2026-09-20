const base = (import.meta.env.VITE_API_BASE || "/api").replace(/\/+$/, "");

async function handle(res) {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch { /* keep the default */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${base}/health`).then(handle),

  upload(file) {
    const body = new FormData();
    body.append("file", file);
    return fetch(`${base}/contracts`, { method: "POST", body }).then(handle);
  },

  run: (docId) => fetch(`${base}/runs/${docId}`).then(handle),

  decide: (docId, findingId, choice) =>
    fetch(`${base}/runs/${docId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ finding_id: findingId, choice })
    }).then(handle),

  ask: (docId, question) =>
    fetch(`${base}/contracts/${docId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question })
    }).then(handle)
};
