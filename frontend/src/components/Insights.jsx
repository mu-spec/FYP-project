import { useEffect, useMemo, useState } from 'react'
import { getHistory } from '../api.js'
import {
  toPercent01, computeVerdictDistribution, buildConfidenceSeries,
  aggregateWarningSigns, averageConfidence,
} from '../insightsData.js'
import VerdictDonut from './charts/VerdictDonut.jsx'
import ConfidenceTrend from './charts/ConfidenceTrend.jsx'
import WarningBars from './charts/WarningBars.jsx'
import Icon from './Icon.jsx'

function formatDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/**
 * Milestone 8F.1 — professional analytics dashboard for the existing
 * Insights screen. Same data source as 7E (the signed-in user's History
 * records via /api/history — never another user's, never global), same KPI
 * formulas (pure transforms in insightsData.js), now visualized with real
 * charts: verdict donut, confidence trend and warning-sign bars. Recent
 * analyses stay a list. No fake/demo data is ever rendered.
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
    const distribution = computeVerdictDistribution(rows)
    return {
      total: distribution.total,
      scamCount: distribution.scam.count,
      legitCount: distribution.legitimate.count,
      scamShare: distribution.scam.share,
      legitShare: distribution.legitimate.share,
      avgConfidence: averageConfidence(rows),
      distribution,
      series: buildConfidenceSeries(rows),
      topFlags: aggregateWarningSigns(rows, 6),
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
          <p>A live summary of every valid prediction stored in History — verdict split, confidence trend and the warning signs detected most often.</p>
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
          <>
            <section className="empty-insights card-surface">
              <span className="empty-icon"><Icon name="chart" size={26} /></span>
              <span className="section-label">Nothing to summarize yet</span>
              <h2>No analysis insights yet</h2>
              <p>Analyze your first job to start building insights.</p>
              <button type="button" className="btn btn-primary insights-cta" onClick={() => onNavigate?.('home')}>
                <Icon name="search" size={17} /> Analyze a Job
              </button>
            </section>
            {/* 8F.2A: the trend section still renders its own real-data empty
                state — zero records means zero chart points, never dummies. */}
            <section className="insights-panel card-surface" aria-label="Analysis confidence trend">
              <div className="insights-panel-head">
                <h2>Analysis Confidence Trend</h2>
                <span className="insights-panel-note">Model decision confidence over time</span>
              </div>
              <ConfidenceTrend series={stats.series} />
            </section>
          </>
        )}

        {backendUp && !error && stats && stats.total > 0 && (
          <>
            <section className="insights-grid" aria-label="Summary metrics">
              <article className="insight-card card-surface">
                <span className="metric-label">Total jobs analyzed</span>
                <strong className="insight-value">{stats.total.toLocaleString()}</strong>
                <span className="metric-help">Valid predictions saved in History</span>
                <span className="insight-icon" aria-hidden="true"><Icon name="chart" size={17} /></span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Flagged as scam</span>
                <strong className="insight-value scam">{stats.scamCount.toLocaleString()}</strong>
                <span className="metric-help">{toPercent01(stats.scamShare)} of all analyses</span>
                <span className="insight-icon insight-icon-scam" aria-hidden="true"><Icon name="warning" size={17} /></span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Looked legitimate</span>
                <strong className="insight-value legit">{stats.legitCount.toLocaleString()}</strong>
                <span className="metric-help">{toPercent01(stats.legitShare)} of all analyses</span>
                <span className="insight-icon insight-icon-legit" aria-hidden="true"><Icon name="check" size={17} /></span>
              </article>
              <article className="insight-card card-surface">
                <span className="metric-label">Avg decision confidence</span>
                <strong className="insight-value">{toPercent01(stats.avgConfidence)}</strong>
                <span className="metric-help">Winning-class probability, all records</span>
                <span className="insight-icon insight-icon-avg" aria-hidden="true"><Icon name="spark" size={17} /></span>
              </article>
            </section>

            <div className="insights-charts-row">
              <section className="insights-panel card-surface" aria-label="Verdict distribution">
                <div className="insights-panel-head">
                  <h2>Verdict Distribution</h2>
                  <span className="insights-panel-note">Share of saved verdicts</span>
                </div>
                <VerdictDonut distribution={stats.distribution} />
              </section>

              <section className="insights-panel card-surface" aria-label="Analysis confidence trend">
                <div className="insights-panel-head">
                  <h2>Analysis Confidence Trend</h2>
                  <span className="insights-panel-note">Model decision confidence over time</span>
                </div>
                <ConfidenceTrend series={stats.series} />
              </section>
            </div>

            <div className="insights-bottom-row">
            <section className="insights-panel card-surface" aria-label="Most common warning signs">
              <div className="insights-panel-head">
                <h2>Most common warning signs</h2>
                <span className="insights-panel-note">From saved evidence maps</span>
              </div>
              {stats.topFlags.length > 0 ? (
                <WarningBars flags={stats.topFlags} />
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
              <div className="recent-list" role="table" aria-label="Recent analyses">
                <div className="recent-row recent-head" role="row">
                  <span role="columnheader">Job title</span>
                  <span role="columnheader">Verdict</span>
                  <span className="recent-conf" role="columnheader">Confidence</span>
                  <span className="recent-date" role="columnheader">Time</span>
                </div>
                {stats.recent.map((row) => (
                  <div className="recent-row" key={row.id} role="row">
                    <span className="recent-title" title={row.job_title}>{row.job_title || 'Untitled job'}</span>
                    <span className={`table-verdict ${row.prediction === 'Scam' ? 'table-scam' : 'table-legit'}`}><span />{row.prediction}</span>
                    <span className="recent-conf">{toPercent01(row.confidence)}</span>
                    <span className="recent-date">{formatDate(row.created_at)}</span>
                  </div>
                ))}
              </div>
            </section>
            </div>

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
