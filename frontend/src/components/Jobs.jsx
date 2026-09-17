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
import { getJobs } from '../api.js'
import Icon from './Icon.jsx'

const SOURCE_LABELS = { remoteok: 'Remote OK', arbeitnow: 'Arbeitnow' }

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

export default function Jobs({ onAnalyzeJob, backendUp }) {
  const [filters, setFilters] = useState({ q: '', location: '', source: '', remote: false })
  const [applied, setApplied] = useState(filters)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [analyzingId, setAnalyzingId] = useState(null)
  const [analysisNote, setAnalysisNote] = useState('')
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
      <section className="page-intro">
        <p className="eyebrow"><span className="eyebrow-line" /> REAL JOB DISCOVERY</p>
        <h1>Real Job Opportunities</h1>
        <p className="page-subtitle">Browse current jobs from trusted external sources.</p>
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
    </main>
  )
}
