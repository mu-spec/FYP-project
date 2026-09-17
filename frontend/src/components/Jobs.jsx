/**
 * Milestone 8B.1 — Real Job Opportunities page.
 *
 * Shows real external job postings (Remote OK + Arbeitnow) through the
 * server-cached /api/jobs endpoint. External descriptions are rendered as
 * PLAIN TEXT (never raw HTML), every card names its source and links to the
 * original listing, and "Analyze with JobGuard" feeds the description into
 * the EXISTING one-click analysis pipeline.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getJobs, getJobPreferences, saveJobPreferences } from '../api.js'
import Icon from './Icon.jsx'

const SOURCE_LABELS = { remoteok: 'Remote OK', arbeitnow: 'Arbeitnow', jobicy: 'Jobicy', adzuna: 'Adzuna', upwork: 'Upwork', jobguard: 'JobGuard' }

function formatDate(iso) {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function snippet(text) {
  if (!text) return null
  return text.length > 220 ? `${text.slice(0, 220).trimEnd()}…` : text
}

function alertsSummary(prefs) {
  if (!prefs) return null
  const parts = []
  if (prefs.keywords) parts.push(prefs.keywords)
  if (prefs.remote_only) parts.push('Remote')
  if (prefs.location) parts.push(prefs.location)
  if (prefs.source && prefs.source !== 'any') parts.push(SOURCE_LABELS[prefs.source] || prefs.source)
  return parts.length ? `Alerts: ${parts.join(' · ')}` : null
}

export default function Jobs({ onAnalyzeJob, backendUp, focusJob, onClearFocus }) {
  const [filters, setFilters] = useState({ q: '', location: '', source: '', remote: false })
  const [applied, setApplied] = useState(filters)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [analyzingId, setAnalyzingId] = useState(null)
  const [analysisNote, setAnalysisNote] = useState('')
  // Milestone 8B.2 — job preferences + notification hand-off
  const [prefs, setPrefs] = useState(null)
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [prefsDraft, setPrefsDraft] = useState({ keywords: '', location: '', remote_only: false, source: 'any' })
  const [prefsSaving, setPrefsSaving] = useState(false)
  const [prefsError, setPrefsError] = useState('')
  const [detailJob, setDetailJob] = useState(null)
  const debounceRef = useRef(null)
  const requestRef = useRef(0)

  // Any filter change — typed, pasted, cleared via the native ✕, selected or
  // toggled — is debounced briefly before it hits the API. 350 ms keeps
  // typing responsive without firing a request per keystroke.
  useEffect(() => {
    debounceRef.current = setTimeout(() => setApplied(filters), 350)
    return () => clearTimeout(debounceRef.current)
  }, [filters])

  const load = useCallback(async (params, page = 1) => {
    const requestId = ++requestRef.current
    setLoading(true)
    setError('')
    try {
      const result = await getJobs({ ...params, page })
      if (requestId !== requestRef.current) return // a newer request superseded this one
      setData(result)
    } catch (err) {
      if (requestId !== requestRef.current) return
      setData(null)
      setError(err.message || 'Could not load jobs right now. Please try again.')
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(applied, 1)
  }, [applied, load])

  // Milestone 8B.2 — load the saved preferences once for the summary chip.
  useEffect(() => {
    getJobPreferences()
      .then((res) => {
        setPrefs(res.preferences)
        if (res.preferences) {
          setPrefsDraft({
            keywords: res.preferences.keywords || '',
            location: res.preferences.location || '',
            remote_only: !!res.preferences.remote_only,
            source: res.preferences.source || 'any',
          })
        }
      })
      .catch(() => {/* the page itself still works without preferences */})
  }, [])

  // A notification's "View Job" hands over a job — open its detail view.
  useEffect(() => {
    if (focusJob) {
      setDetailJob(focusJob)
      onClearFocus?.()
    }
  }, [focusJob, onClearFocus])

  const openPrefs = () => {
    setPrefsError('')
    setPrefsOpen(true)
  }
  const savePrefs = async (event) => {
    event.preventDefault()
    setPrefsSaving(true)
    setPrefsError('')
    try {
      const res = await saveJobPreferences(prefsDraft)
      setPrefs(res.preferences)
      setPrefsOpen(false)
      // let the navbar bell refresh its unread badge right away
      window.dispatchEvent(new Event('jobguard:prefs-saved'))
    } catch (err) {
      setPrefsError(err.message || 'Could not save your preferences.')
    } finally {
      setPrefsSaving(false)
    }
  }

  // Debounce handled above; every control just updates the filter state.
  const setFilter = (key) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setFilters((f) => ({ ...f, [key]: value }))
  }

  const jobs = data?.jobs ?? []
  const cache = data?.cache
  const degraded = cache && Object.values(cache.providers || {}).some((p) => p.ok === false)

  return (
    <main className="page-shell jobs-page">
      <section className="page-intro jobs-intro-row">
        <div>
          <p className="eyebrow"><span className="eyebrow-line" /> REAL JOB DISCOVERY</p>
          <h1>Real Job Opportunities</h1>
          <p className="page-subtitle">Browse current jobs from trusted external sources.</p>
          {prefs && alertsSummary(prefs) && (
            <p className="jobs-alerts-summary" title="Your saved job preferences">
              {alertsSummary(prefs)}
            </p>
          )}
        </div>
        <button type="button" className="jobs-prefs-btn" onClick={openPrefs}>
          <Icon name="bell" size={15} strokeWidth={2} /> Job Preferences
        </button>
      </section>

      <section className="jobs-toolbar card-surface" aria-label="Job filters">
        <div className="jobs-toolbar-fields">
          <div className="jobs-field jobs-field-search">
            <label htmlFor="jobs-q">Search jobs</label>
            <input
              id="jobs-q"
              type="search"
              placeholder="Title, company, skill…"
              value={filters.q}
              onChange={setFilter('q')}
            />
          </div>
          <div className="jobs-field">
            <label htmlFor="jobs-location">Location</label>
            <input
              id="jobs-location"
              type="text"
              placeholder="City or region"
              value={filters.location}
              onChange={setFilter('location')}
            />
          </div>
          <div className="jobs-field">
            <label htmlFor="jobs-source">Source</label>
            <select id="jobs-source" value={filters.source} onChange={setFilter('source')}>
              <option value="">All sources</option>
              <option value="jobicy">Jobicy</option>
              <option value="adzuna">Adzuna</option>
              <option value="upwork">Upwork</option>
              <option value="jobguard">JobGuard</option>
              <option value="remoteok">Remote OK</option>
              <option value="arbeitnow">Arbeitnow</option>
            </select>
          </div>
          <div className="jobs-field jobs-field-remote">
            <label htmlFor="jobs-remote">Remote only</label>
            <label className="jobs-remote-toggle">
              <input id="jobs-remote" type="checkbox" checked={filters.remote} onChange={setFilter('remote')} />
              <span>Remote positions only</span>
            </label>
          </div>
        </div>
        {cache && (
          <div className="jobs-cache-meta">
            {degraded && (
              <span className="jobs-cache-note jobs-cache-warn">
                One source is temporarily unavailable — showing the rest.
              </span>
            )}
            {cache.stale && (
              <span className="jobs-cache-note jobs-cache-warn">
                Live sources unreachable — showing recently cached jobs.
              </span>
            )}
            <span className="jobs-cache-updated">
              {Object.entries(cache.providers || {}).map(([name, info]) => (
                <span key={name} className="jobs-source-meta">
                  <span className={`jobs-dot ${info.ok === false ? 'jobs-dot-off' : 'jobs-dot-on'}`} />
                  {SOURCE_LABELS[name] || name}: {info.jobs} jobs
                </span>
              ))}
              {cache.last_refresh_at && (
                <> · updated {formatDate(cache.last_refresh_at) || 'recently'}</>
              )}
            </span>
          </div>
        )}
      </section>

      {loading && (
        <section className="jobs-state card-surface" role="status" aria-live="polite">
          <p>Loading jobs…</p>
        </section>
      )}

      {!loading && error && (
        <section className="jobs-state card-surface" role="alert">
          <p>{error}</p>
          <button type="button" className="btn-primary jobs-retry" onClick={() => load(applied, data?.page || 1)}>
            Try again
          </button>
        </section>
      )}

      {!loading && !error && analysisNote && (
        <section className="jobs-state card-surface jobs-analysis-note" role="status">
          <p>{analysisNote}</p>
        </section>
      )}

      {!loading && !error && jobs.length === 0 && (
        <section className="jobs-state card-surface">
          <h2>No jobs match your filters</h2>
          <p>Try a different search term, clear the location, or include all sources.</p>
        </section>
      )}

      {!loading && !error && jobs.length > 0 && (
        <>
          <section className="jobs-grid">
            {jobs.map((job) => (
              <article key={`${job.source}:${job.source_job_id}`} className="job-card card-surface">
                <div className="job-card-top">
                  <span className={`job-source-badge job-source-${job.source}`}>
                    Source: {SOURCE_LABELS[job.source] || job.source}
                  </span>
                  {job.remote && <span className="job-remote-chip">Remote</span>}
                </div>
                <h2 className="job-title">{job.title}</h2>
                <p className="job-company">{job.company || 'Company not listed'}</p>
                <ul className="job-meta">
                  {job.location && <li>📍 {job.location}</li>}
                  {job.job_type && <li>🕒 {job.job_type}</li>}
                  {job.salary && <li>💰 {job.salary}</li>}
                  {formatDate(job.published_at) && <li>📅 {formatDate(job.published_at)}</li>}
                </ul>
                {job.source === 'jobguard' && (
                  <p className="job-guard-note">
                    <Icon name="shield" size={13} strokeWidth={2} /> Screened by JobGuard
                    — automated risk screening, not a company verification.
                  </p>
                )}
                {job.description && <p className="job-snippet">{snippet(job.description)}</p>}
                <div className="job-actions">
                  {job.job_url && job.job_url.startsWith('http') && (
                    <a
                      className="job-link"
                      href={job.job_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View Original Job <Icon name="arrow" size={14} />
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn-primary job-analyze"
                    disabled={analyzingId !== null || backendUp === false}
                    onClick={async () => {
                      const key = `${job.source}:${job.source_job_id}`
                      setAnalyzingId(key)
                      setAnalysisNote('')
                      try {
                        // Pipeline signature is (jobText, title) — the SAME
                        // one-click path as the Home page.
                        const ok = await onAnalyzeJob(job.description || job.title, job.title)
                        if (ok === false) {
                          setAnalysisNote(
                            `JobGuard couldn't analyze "${job.title}" — the listing text is too short. Open the original job and analyze its full description from the Analyze page.`
                          )
                        }
                      } finally {
                        setAnalyzingId(null)
                      }
                    }}
                  >
                    {analyzingId === `${job.source}:${job.source_job_id}` ? 'Analyzing…' : 'Analyze with JobGuard'}
                  </button>
                </div>
              </article>
            ))}
          </section>

          <nav className="jobs-pagination" aria-label="Jobs pages">
            <button
              type="button"
              disabled={(data?.page || 1) <= 1 || loading}
              onClick={() => load(applied, (data?.page || 1) - 1)}
            >
              ← Previous
            </button>
            <span>Page {data?.page} of {data?.pages}</span>
            <button
              type="button"
              disabled={(data?.page || 1) >= (data?.pages || 1) || loading}
              onClick={() => load(applied, (data?.page || 1) + 1)}
            >
              Next →
            </button>
          </nav>
        </>
      )}

      {/* Milestone 8B.2 — Job Preferences modal (compact, on demand) */}
      {prefsOpen && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setPrefsOpen(false)
          }}
        >
          <form className="modal-card card-surface" role="dialog" aria-modal="true" aria-label="Job Preferences" onSubmit={savePrefs}>
            <div className="modal-head">
              <h2>Job Preferences</h2>
              <button type="button" className="modal-close" aria-label="Close preferences" onClick={() => setPrefsOpen(false)}>
                <Icon name="close" size={16} strokeWidth={2} />
              </button>
            </div>
            <p className="modal-sub">Tell JobGuard what to alert you about. Matching runs on cached external jobs only.</p>
            <div className="jobs-field">
              <label htmlFor="prefs-keywords">Keywords / Job Title</label>
              <input
                id="prefs-keywords"
                type="text"
                placeholder="e.g. Software Engineer"
                value={prefsDraft.keywords}
                onChange={(e) => setPrefsDraft((d) => ({ ...d, keywords: e.target.value }))}
              />
            </div>
            <div className="jobs-field">
              <label htmlFor="prefs-location">Preferred Location</label>
              <input
                id="prefs-location"
                type="text"
                placeholder="e.g. Lahore"
                value={prefsDraft.location}
                onChange={(e) => setPrefsDraft((d) => ({ ...d, location: e.target.value }))}
              />
            </div>
            <div className="jobs-field">
              <label htmlFor="prefs-source">Preferred Source</label>
              <select
                id="prefs-source"
                value={prefsDraft.source}
                onChange={(e) => setPrefsDraft((d) => ({ ...d, source: e.target.value }))}
              >
                <option value="any">Any</option>
                <option value="remoteok">Remote OK</option>
                <option value="arbeitnow">Arbeitnow</option>
              </select>
            </div>
            <label className="jobs-remote-toggle" htmlFor="prefs-remote">
              <input
                id="prefs-remote"
                type="checkbox"
                checked={prefsDraft.remote_only}
                onChange={(e) => setPrefsDraft((d) => ({ ...d, remote_only: e.target.checked }))}
              />
              <span>Remote Only</span>
            </label>
            {prefsError && <p className="prefs-error" role="alert">{prefsError}</p>}
            <div className="modal-actions">
              <button type="button" className="modal-cancel" onClick={() => setPrefsOpen(false)}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={prefsSaving}>
                {prefsSaving ? 'Saving…' : 'Save Preferences'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Milestone 8B.2 — job detail (also the View Job target from the bell) */}
      {detailJob && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setDetailJob(null)
          }}
        >
          <div className="modal-card card-surface job-detail" role="dialog" aria-modal="true" aria-label="Job details">
            <div className="modal-head">
              <span className={`job-source-badge job-source-${detailJob.source}`}>
                Source: {SOURCE_LABELS[detailJob.source] || detailJob.source}
              </span>
              <button type="button" className="modal-close" aria-label="Close job details" onClick={() => setDetailJob(null)}>
                <Icon name="close" size={16} strokeWidth={2} />
              </button>
            </div>
            <h2 className="job-title">{detailJob.title}</h2>
            <p className="job-company">{detailJob.company || 'Company not listed'}</p>
            <ul className="job-meta">
              <li>{detailJob.remote ? 'Remote' : (detailJob.location || 'On-site')}</li>
              {detailJob.job_type && <li>🕒 {detailJob.job_type}</li>}
              {detailJob.salary && <li>💰 {detailJob.salary}</li>}
              {formatDate(detailJob.published_at) && <li>📅 {formatDate(detailJob.published_at)}</li>}
            </ul>
            {detailJob.description && <p className="job-detail-desc">{detailJob.description}</p>}
            <div className="modal-actions job-actions">
              {detailJob.job_url && detailJob.job_url.startsWith('http') && (
                <a className="job-link" href={detailJob.job_url} target="_blank" rel="noopener noreferrer">
                  View Original Job <Icon name="arrow" size={14} />
                </a>
              )}
              <button
                type="button"
                className="btn-primary job-analyze"
                disabled={analyzingId !== null || backendUp === false}
                onClick={async () => {
                  setAnalyzingId('detail')
                  try {
                    await onAnalyzeJob(detailJob.description || detailJob.title, detailJob.title)
                    setDetailJob(null)
                  } finally {
                    setAnalyzingId(null)
                  }
                }}
              >
                {analyzingId === 'detail' ? 'Analyzing…' : 'Analyze with JobGuard'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
