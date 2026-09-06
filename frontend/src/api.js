/**
 * API client for the Flask backend (Phase 2).
 * All endpoints are prefixed with /api and proxied by Vite in dev.
 */

const BASE = '/api'

async function handle(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
  return data
}

export async function checkHealth() {
  const res = await fetch(`${BASE}/health`)
  return handle(res)
}

export async function analyzeJob(jobText, title = '') {
  const res = await fetch(`${BASE}/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_text: jobText, title }),
  })
  return handle(res)
}

export async function getHistory(limit = 50) {
  const res = await fetch(`${BASE}/history?limit=${limit}`)
  return handle(res)
}

export async function clearHistory() {
  const res = await fetch(`${BASE}/history`, { method: 'DELETE' })
  return handle(res)
}
