import { useEffect, useMemo, useState } from 'react'
import { getHistory } from '../api.js'
import Icon from './Icon.jsx'

const fmtPct1 = (value) => `${(Math.max(0, Math.min(1, Number(value) || 0)) * 100).toFixed(1)}%`

function formatDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const SEVERITY_CLASS = { high: 'sev-high', medium: 'sev-medium', low: 'sev-low' }

/**
 * Milestone 7E — real Insights, derived ONLY from the existing History API
 * fields (id, job_title, prediction, confidence, created_at, evidence[]).
 * Nothing is mocked or invented: every number on this page is computed from
 * the records the backend already returns. Metrics that cannot be derived
 * reliably (e.g. per-record scam probability) are intentionally not shown.
 */
export default function Insights({ backendUp, onNavigate }) {
  const [rows, setRows] = useState(null) // null = loading
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!backendUp) return
    setError(null)
    getHistory().then(setRows).catch((err) => setError(err.message))
  }, [backendUp])

  const stats = useMemo(() => {
    if (!Array.isArray(rows)) return null
    const total = rows.length
    if (total === 0) return { total: 0 }

    const scamRows = rows.filter((row) => row.prediction === 'Scam')
    const legitRows = rows.filter((row) => row.prediction === 'Legitimate')

    // Most common red-flag categories across saved evidence maps.
    const categories = new Map()
    for (const row of rows) {
      const evidence = Array.isArray(row.evidence) ? row.evidence : []
      for (const flag of evidence) {
        const name = flag.category || flag.message || 'Detected signal'
        const severity = String(flag.severity || 'Low').toLowerCase()
        const entry = categories.get(name) || { count: 0, severity }
        entry.count += 1
        categories.set(name, entry)
      }
    }
    const topFlags = [...categories.entries()]
      .map(([category, info]) => ({ category, ...info }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 6)
    const maxFlagCount = topFlags.length ? topFlags[0].count : 0

    return {
      total,
      scamCount: scamRows.length,
      legitCount: legitRows.length,
      scamShare: total ? scamRows.length / total : 0,
      legitShare: total ? legitRows.length / total : 0,
      avgConfidence: total ? rows.reduce((sum, row) => sum + (Number(row.confidence) || 0), 0) / total : 0,
      topFlags,
      maxFlagCount,
      recent: rows.slice(0, 5),
      lastAnalyzed: rows[0]?.created_at || null,
    }
  }, [rows])

  return (
    <main className="page-shell">
      <div className="container-wide">
        <div className="page-intro">
          <div className="eyebrow"><span className="eyebrow-line" /> Insights</div>
          <h1>Patterns from your analyses</h1>
          <p>A live summary of every valid prediction stored in History — scam share, average decision confidence and the warning signs detected most often.</p>
        </div>

        {!backendUp && (
          <section className="empty-insights card-surface">
            <span className="empty-icon"><Icon name="shield" size={26} /></span>
            <span className="section-label">History is unavailable</span>
            <h2>Connect the Flask backend</h2>
            <p>Insights are calculated from your saved prediction history, so the API needs to be running.</p>
          </section>
        )}

        {backendUp && error && (
          <div className="inline-alert error-alert" role="alert">
            <Icon name="warning" size={18} />
            <div><strong>Insights could not be loaded.</strong><span>{error}</span></div>
          </div>
        )}

        {backendUp && !error && rows === null && (
          <section className="empty-insights card-surface" aria-busy="true">
            <span className="empty-icon"><Icon name="chart" size={26} /></span>
            <span className="section-label">Loading</span>
            <h2>Crunching your history…</h2>
          </section>
        )}

        {backendUp && !error && stats && stats.total === 0 && (
          <section className="empty-insights card-surface">
            <span className="empty-icon"><Icon name="chart" size={26} /></span>
            <span className="section-label">Nothing to summarize yet</span>
            <h2>No insights yet</h2>
            <p>Analyze a few job posts to see patterns and warning signals here.</p>
            <button type="button" className="btn btn-primary insights-cta" onClick={() => onNavigate?.('home')}>
              <Icon name="search" size={17} /> Analyze a Job
            </button>
          </section>
        )}

        {backendUp && !error && stats && stats.total > 0 && (
          <>
            <section className="insights-grid" aria-label="Summary metrics">
              <article className="insight-card card-surface">
                <span className="metric-label">Total jobs analyzed</span>
                <strong className="insight-value">{stats.total.toLocaleString()}</strong>
                <span className="metric-help">Valid predictions saved in History</span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Flagged as scam</span>
                <strong className="insight-value scam">{stats.scamCount.toLocaleString()}</strong>
                <span className="metric-help">{fmtPct1(stats.scamShare)} of all analyses</span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Looked legitimate</span>
                <strong className="insight-value legit">{stats.legitCount.toLocaleString()}</strong>
                <span className="metric-help">{fmtPct1(stats.legitShare)} of all analyses</span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Avg decision confidence</span>
                <strong className="insight-value">{fmtPct1(stats.avgConfidence)}</strong>
                <span className="metric-help">Winning-class probability, all records</span>
              </article>
            </section>

            <section className="insights-panel card-surface" aria-label="Scam vs legitimate split">
              <div className="insights-panel-head">
                <h2>Scam vs legitimate</h2>
                <span className="insights-panel-note">Share of saved verdicts</span>
              </div>
              <div className="split-bar" role="img" aria-label={`Scam ${fmtPct1(stats.scamShare)}, legitimate ${fmtPct1(stats.legitShare)}`}>
                <span className="seg-scam" style={{ width: `${(stats.scamShare * 100).toFixed(2)}%` }} />
                <span className="seg-legit" style={{ width: `${(stats.legitShare * 100).toFixed(2)}%` }} />
              </div>
              <div className="split-legend">
                <span className="legend-item"><span className="legend-dot dot-scam" /> Scam · {stats.scamCount} ({fmtPct1(stats.scamShare)})</span>
                <span className="legend-item"><span className="legend-dot dot-legit" /> Legitimate · {stats.legitCount} ({fmtPct1(stats.legitShare)})</span>
              </div>
            </section>

            <section className="insights-panel card-surface" aria-label="Most common warning signs">
              <div className="insights-panel-head">
                <h2>Most common warning signs</h2>
                <span className="insights-panel-note">From saved evidence maps</span>
              </div>
              {stats.topFlags.length > 0 ? (
                <div className="flag-ranks">
                  {stats.topFlags.map((flag) => (
                    <div className="flag-rank" key={flag.category}>
                      <div className="flag-rank-top">
                        <strong>{flag.category}</strong>
                        <span className="flag-rank-count">{flag.count}× {flag.severity} severity</span>
                      </div>
                      <div className={`flag-rank-bar ${SEVERITY_CLASS[flag.severity] || 'sev-low'}`}>
                        <span style={{ width: `${Math.max(8, (flag.count / stats.maxFlagCount) * 100).toFixed(1)}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="insights-panel-empty">No red flags have been recorded yet — every analyzed post came back clean.</p>
              )}
            </section>

            <section className="insights-panel card-surface" aria-label="Recent analyses">
              <div className="insights-panel-head">
                <h2>Recent analyses</h2>
                <button type="button" className="text-action" onClick={() => onNavigate?.('history')}>
                  View full history <Icon name="arrow" size={15} />
                </button>
              </div>
              <div className="recent-list">
                {stats.recent.map((row) => (
                  <div className="recent-row" key={row.id}>
                    <span className={`table-verdict ${row.prediction === 'Scam' ? 'table-scam' : 'table-legit'}`}><span />{row.prediction}</span>
                    <span className="recent-title" title={row.job_title}>{row.job_title || 'Untitled job'}</span>
                    <span className="recent-conf">{fmtPct1(row.confidence)}</span>
                    <span className="recent-date">{formatDate(row.created_at)}</span>
                  </div>
                ))}
              </div>
            </section>

            <p className="result-footnote insights-footnote">
              <Icon name="info" size={14} />
              Calculated live from the {stats.total.toLocaleString()} record{stats.total === 1 ? '' : 's'} currently in History
              {stats.lastAnalyzed ? ` · most recent ${formatDate(stats.lastAnalyzed)}` : ''}. Full job text is never stored.
            </p>
          </>
        )}
      </div>
    </main>
  )
}
