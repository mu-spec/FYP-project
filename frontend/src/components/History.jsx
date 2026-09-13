import { useEffect, useMemo, useState } from 'react'
import { clearHistory, getHistory } from '../api.js'
import Icon from './Icon.jsx'

const fmtPct = (value) => `${(Math.max(0, Math.min(1, Number(value) || 0)) * 100).toFixed(2)}%`

function formatDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function History({ backendUp, refreshKey }) {
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('All')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    if (!backendUp) return
    setError(null)
    getHistory().then(setRows).catch((err) => setError(err.message))
  }, [backendUp, refreshKey])

  async function handleClear() {
    try {
      await clearHistory()
      setRows([])
      setSelected(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const filteredRows = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return rows.filter((row) => {
      const matchesFilter = filter === 'All' || row.prediction === filter
      const matchesSearch = !normalized || `${row.job_title} ${row.prediction} ${row.created_at}`.toLowerCase().includes(normalized)
      return matchesFilter && matchesSearch
    })
  }, [rows, query, filter])

  return (
    <main className="page-shell history-page">
      <div className="container-wide">
        <div className="page-intro history-intro">
          <div className="eyebrow"><span className="eyebrow-line" /> Saved analyses</div>
          <h1>Prediction history</h1>
          <p>Review the verdict, confidence and date for previous valid analyses. Invalid submissions are never saved.</p>
        </div>

        <section className="history-surface card-surface">
          <div className="history-toolbar">
            <div className="history-count"><strong>{rows.length}</strong><span>saved predictions</span></div>
            <div className="history-controls">
              <label className="search-field">
                <Icon name="search" size={17} />
                <span className="sr-only">Search history</span>
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search job titles…" />
              </label>
              <label className="filter-field">
                <Icon name="filter" size={16} />
                <span className="sr-only">Filter by verdict</span>
                <select value={filter} onChange={(event) => setFilter(event.target.value)}>
                  <option>All</option>
                  <option>Scam</option>
                  <option>Legitimate</option>
                </select>
              </label>
              {rows.length > 0 && <button className="quiet-action danger-action" type="button" onClick={handleClear}>Clear history</button>}
            </div>
          </div>

          {error && <div className="inline-alert error-alert" role="alert"><Icon name="warning" size={17} /><span>{error}</span></div>}
          {!backendUp && <div className="empty-history"><span className="empty-icon"><Icon name="shield" size={24} /></span><h2>History is unavailable</h2><p>Connect the Flask backend to load saved predictions.</p></div>}
          {backendUp && !error && rows.length === 0 && <div className="empty-history"><span className="empty-icon"><Icon name="history" size={24} /></span><h2>No predictions yet</h2><p>Valid analyses will appear here after you submit a job post.</p></div>}
          {backendUp && !error && rows.length > 0 && filteredRows.length === 0 && <div className="empty-history compact-empty"><span className="empty-icon"><Icon name="search" size={22} /></span><h2>No matching predictions</h2><p>Try a different search term or filter.</p></div>}

          {backendUp && !error && filteredRows.length > 0 && (
            <div className="history-table-wrap">
              <table className="history-table">
                <thead><tr><th>Job title</th><th>Verdict</th><th>Probability</th><th>Date</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {filteredRows.map((row) => (
                    <tr key={row.id}>
                      <td><div className="history-title"><span className={`row-icon ${row.prediction === 'Scam' ? 'row-icon-scam' : 'row-icon-legit'}`}><Icon name={row.prediction === 'Scam' ? 'warning' : 'check'} size={15} /></span><span title={row.job_title}>{row.job_title || 'Untitled job'}</span></div></td>
                      <td><span className={`table-verdict ${row.prediction === 'Scam' ? 'table-scam' : 'table-legit'}`}><span />{row.prediction}</span></td>
                      <td><strong>{fmtPct(row.confidence)}</strong><span className="table-muted"> winning class</span></td>
                      <td className="date-cell">{formatDate(row.created_at)}</td>
                      <td className="action-cell"><button type="button" className="view-details" onClick={() => setSelected(row)}>View details <Icon name="chevron" size={15} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="history-note"><Icon name="info" size={14} /> History stores the job title, verdict, confidence, timestamp and evidence map from each valid prediction.</p>
        </section>
      </div>

      {selected && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null) }}>
          <section className="history-modal" role="dialog" aria-modal="true" aria-labelledby="history-detail-title">
            <div className="modal-header"><div><span className="section-label">Saved prediction #{selected.id}</span><h2 id="history-detail-title">Analysis details</h2></div><button className="icon-button" type="button" onClick={() => setSelected(null)} aria-label="Close details"><Icon name="close" size={19} /></button></div>
            <div className="modal-verdict-row"><span className={`verdict-pill ${selected.prediction === 'Scam' ? 'scam-pill' : 'legit-pill'}`}><span className="verdict-dot" />{selected.prediction}</span><strong>{fmtPct(selected.confidence)} confidence</strong></div>
            <dl className="detail-list"><div><dt>Job title</dt><dd>{selected.job_title || 'Untitled job'}</dd></div><div><dt>Analyzed</dt><dd>{formatDate(selected.created_at)}</dd></div><div><dt>Record ID</dt><dd>#{selected.id}</dd></div></dl>
            <div className="saved-evidence">
              <span className="section-label">Saved evidence map</span>
              {Array.isArray(selected.evidence) && selected.evidence.length > 0 ? (
                <ul className="saved-evidence-list">
                  {selected.evidence.map((flag, index) => (
                    <li className="saved-evidence-item" key={`${flag.category || flag.message || 'signal'}-${index}`}>
                      <div className="saved-evidence-item-top">
                        <strong>{flag.category || flag.message || 'Detected signal'}</strong>
                        <span>{flag.severity || 'Signal'}</span>
                      </div>
                      {Array.isArray(flag.evidence) && flag.evidence.length > 0 && (
                        <div className="saved-evidence-snippets">
                          {flag.evidence.map((snippet, snippetIndex) => <span key={`${snippet}-${snippetIndex}`}>“{snippet}”</span>)}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="saved-evidence-empty">No red flags were stored for this analysis.</p>
              )}
            </div>
            <p className="modal-note"><Icon name="info" size={15} /> The current SQLite history schema stores summary fields, the timestamp and the evidence map; the original job text is not persisted.</p>
          </section>
        </div>
      )}
    </main>
  )
}
