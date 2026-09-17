/**
 * API client for the Flask backend (Phase 2).
 * All endpoints are prefixed with /api and proxied by Vite in dev.
 */

const BASE = '/api'

// Milestone 8A.2 — session-bound CSRF token. Kept in module memory only
// (never localStorage); issued by the server inside the session and echoed
// back in the X-CSRF-Token header on state-changing calls.
let csrfToken = null

function authedOptions(options = {}) {
  if (!csrfToken) return options
  return {
    ...options,
    headers: { ...(options.headers || {}), 'X-CSRF-Token': csrfToken },
  }
}

async function handle(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // A 401 from a protected API means the session ended (expired, server
    // restart, logout elsewhere). Let the central auth state react.
    if (res.status === 401) {
      csrfToken = null
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    const err = new Error(data.error || `Request failed (${res.status})`)
    // Mark validation rejections so the UI can show a dedicated
    // "Invalid Job Description" state instead of a generic error.
    err.invalid = !!data.invalid_input
    throw err
  }
  return data
}

export async function checkHealth() {
  const res = await fetch(`${BASE}/health`)
  return handle(res)
}

export async function analyzeJob(jobText, title = '') {
  const res = await fetch(`${BASE}/predict`, authedOptions({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_text: jobText, title }),
  }))
  return handle(res)
}

export async function analyzeJobUrl(url, title = '') {
  const res = await fetch(`${BASE}/predict-url`, authedOptions({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, title }),
  }))
  return handle(res)
}

export async function getHistory(limit = 50) {
  const res = await fetch(`${BASE}/history?limit=${limit}`)
  return handle(res)
}

export async function clearHistory() {
  const res = await fetch(`${BASE}/history`, authedOptions({ method: 'DELETE' }))
  return handle(res)
}

// ---------------------------------------------------------------------------
// Milestone 8A.1 — authentication helpers (single shared fetch layer).
// All calls are same-origin (Vite proxies /api to Flask); "include" keeps the
// session-cookie handling explicit and ready for a split deployment.
// ---------------------------------------------------------------------------

// Fired whenever a protected API answers 401 so the central auth state can
// drop the user and the app can fall back to the authentication screen.
export const UNAUTHORIZED_EVENT = 'jobguard:unauthorized'

async function handleAuth(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`)
    err.field = data.field
    err.fieldErrors = data.field_errors || {}
    err.status = res.status
    throw err
  }
  return data
}

export async function getCurrentUser() {
  // The startup session check must never throw for the UI gate.
  const res = await fetch(`${BASE}/auth/me`, { credentials: 'include' })
  const data = await res.json().catch(() => ({ authenticated: false }))
  csrfToken = (data && data.authenticated && data.csrf_token) || null
  return data
}

export async function signUp(name, email, password, confirm) {
  const res = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ name, email, password, confirm }),
  })
  const data = await handleAuth(res)
  csrfToken = data.csrf_token || null
  return data
}

export async function signIn(email, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  })
  const data = await handleAuth(res)
  csrfToken = data.csrf_token || null
  return data
}

export async function signOut() {
  const res = await fetch(`${BASE}/auth/logout`, authedOptions({
    method: 'POST',
    credentials: 'include',
  }))
  csrfToken = null
  return res.json().catch(() => ({}))
}
