import { useEffect, useState } from 'react'
import { getHistory, clearHistory } from '../api.js'

// PRD 5.7 — Prediction History: Date, Prediction, Confidence, Job Title
export default function History({ backendUp }) {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (backendUp) {
      getHistory().then(setRows).catch((e) => setErr(e.message))
    }
  }, [backendUp])

  async function handleClear() {
    await clearHistory()
    setRows([])
  }

  return (
    <section id="history" className="card history-card">
      <div className="history-head">
        <h2 className="card-title">🕘 Prediction History</h2>
        {rows.length > 0 && (
          <button className="link-btn" onClick={handleClear}>Clear history</button>
        )}
      </div>
      {err && <p className="warn-text">{err}</p>}
      {!backendUp && <p className="card-sub">Start the backend to see saved predictions.</p>}
      {backendUp && rows.length === 0 && !err && (
        <p className="card-sub">No predictions yet — analyze a job above.</p>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>#</th><th>Date</th><th>Job Title</th><th>Prediction</th><th>Confidence</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{new Date(r.created_at).toLocaleString()}</td>
                  <td className="td-title">{r.job_title}</td>
                  <td>
                    <span className={`mini-badge ${r.prediction === 'Scam' ? 'badge-scam' : 'badge-legit'}`}>
                      {r.prediction}
                    </span>
                  </td>
                  <td>{Math.min(r.confidence * 100, 99.99).toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
