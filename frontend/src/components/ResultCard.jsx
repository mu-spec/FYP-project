// PRD 5.5 + 5.6 — AI Prediction output & Scam Indicator Module
// Display-only formatting: internal probabilities stay raw; the UI shows
// two decimals and never renders a literal "100.00%" (ML expresses
// uncertainty, never absolute certainty).
const fmtPct = (p) => `${Math.min(p * 100, 99.99).toFixed(2)}%`

export default function ResultCard({ result }) {
  const { prediction, confidence, probabilities, red_flags, signals, job_title } = result
  const isScam = prediction === 'Scam'
  const conf = fmtPct(confidence)
  const pScam = fmtPct(probabilities.scam)
  const pLegit = fmtPct(probabilities.legitimate)

  return (
    <div className={`card result-card ${isScam ? 'scam' : 'legit'}`}>
      <div className="result-header">
        <div>
          <h2 className="card-title">{isScam ? '🚨 SCAM DETECTED' : '✅ LEGITIMATE JOB'}</h2>
          <p className="card-sub">"{job_title}"</p>
        </div>
        <div className={`verdict-badge ${isScam ? 'badge-scam' : 'badge-legit'}`}>
          {conf} confident
        </div>
      </div>

      {/* PRD 5.5 — Probability Graph (simple CSS bars) */}
      <div className="prob-graph">
        <div className="prob-row">
          <span className="prob-label">Scam</span>
          <div className="prob-bar-track">
            <div className="prob-bar scam-bar" style={{ width: `${(probabilities.scam * 100).toFixed(2)}%` }} />
          </div>
          <span className="prob-val">{pScam}</span>
        </div>
        <div className="prob-row">
          <span className="prob-label">Legitimate</span>
          <div className="prob-bar-track">
            <div className="prob-bar legit-bar" style={{ width: `${(probabilities.legitimate * 100).toFixed(2)}%` }} />
          </div>
          <span className="prob-val">{pLegit}</span>
        </div>
      </div>

      {/* PRD 5.6 — Scam Indicator Module */}
      {red_flags.length > 0 ? (
        <div className="redflags">
          <h3>⚑ Detected Red Flags ({red_flags.length})</h3>
          <ul>
            {red_flags.map((f, i) => (
              <li key={i}><span className="flag-icon">{f.icon}</span> {f.message}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="no-flags">✔ No major red flags detected in the text.</div>
      )}

      <details className="signals-details">
        <summary>📊 View extracted signals (engineered features)</summary>
        <div className="signals-grid">
          {Object.entries(signals).map(([k, v]) => (
            <div key={k} className="signal-chip">
              <span className="signal-name">{k}</span>
              <span className="signal-val">{v}</span>
            </div>
          ))}
        </div>
      </details>

      <div className="recommendation">
        <strong>Recommendation:</strong>{' '}
        {isScam
          ? 'Avoid applying until the employer is verified through official channels.'
          : 'This posting looks legitimate, but always verify the employer before sharing personal data.'}
      </div>
    </div>
  )
}
