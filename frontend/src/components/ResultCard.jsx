import Icon from './Icon.jsx'

const clamp = (value) => Math.max(0, Math.min(1, Number(value) || 0))
const fmtPct = (value) => `${(clamp(value) * 100).toFixed(2)}%`

function riskLevel(probability) {
  if (probability >= 0.75) return ['High risk', 'high']
  if (probability >= 0.5) return ['Elevated risk', 'elevated']
  if (probability >= 0.25) return ['Caution', 'caution']
  return ['Lower risk', 'lower']
}

export default function ResultCard({ result }) {
  const {
    prediction,
    confidence,
    probabilities = {},
    red_flags: redFlags = [],
    signals = {},
    job_title: jobTitle,
  } = result
  const scamProbability = clamp(probabilities.scam)
  const legitimateProbability = clamp(probabilities.legitimate)
  const isScam = prediction === 'Scam'
  const [riskLabel, riskTone] = riskLevel(scamProbability)

  return (
    <section className={`result-dashboard card-surface ${isScam ? 'scam-result' : 'legit-result'}`}>
      <div className="result-topline">
        <div className="result-heading">
          <span className="section-label">Analysis result</span>
          <h2>{isScam ? 'Scam risk detected' : 'Looks legitimate'}</h2>
          <p className="result-job-title">{jobTitle ? `“${jobTitle}”` : 'Submitted job posting'}</p>
        </div>
        <span className={`verdict-pill ${isScam ? 'scam-pill' : 'legit-pill'}`}>
          <span className="verdict-dot" /> {prediction}
        </span>
      </div>

      <div className="result-metrics">
        <div className="primary-metric">
          <span className="metric-label">Actual scam probability</span>
          <strong>{fmtPct(scamProbability)}</strong>
          <span className="metric-help">Returned by the existing prediction engine</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Risk indicator</span>
          <strong className={`risk-text ${riskTone}`}>{riskLabel}</strong>
          <span className="metric-help">Based on scam probability</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Decision confidence</span>
          <strong>{fmtPct(confidence)}</strong>
          <span className="metric-help">Winning-class probability</span>
        </div>
      </div>

      <div className="risk-visual" aria-label={`Scam probability ${fmtPct(scamProbability)}`}>
        <div className="risk-visual-header">
          <span>Risk scale</span>
          <span>{isScam ? 'Higher probability means more caution' : 'Lower probability is a positive signal'}</span>
        </div>
        <div className="risk-track">
          <div className={`risk-fill ${isScam ? 'risk-fill-scam' : 'risk-fill-legit'}`} style={{ width: `${(scamProbability * 100).toFixed(2)}%` }} />
          <span className="risk-threshold" aria-hidden="true" />
        </div>
        <div className="risk-scale-labels"><span>0% lower risk</span><span>50% review carefully</span><span>100% higher risk</span></div>
      </div>

      <div className="result-content-grid">
        <section className="flags-panel">
          <div className="subsection-heading">
            <div><span className="section-label">Evidence</span><h3>Detected red flags</h3></div>
            <span className={`count-badge ${redFlags.length ? 'has-flags' : 'no-flag-badge'}`}>{redFlags.length}</span>
          </div>
          {redFlags.length > 0 ? (
            <ul className="result-flags">
              {redFlags.map((flag, index) => (
                <li key={`${flag.message}-${index}`}>
                  <span className="flag-marker"><Icon name="warning" size={15} /></span>
                  <span>{flag.message}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="no-flags-state"><span><Icon name="check" size={17} /></span><p>No major red flags were detected in this text.</p></div>
          )}
        </section>

        <aside className={`recommendation-panel ${isScam ? 'recommendation-scam' : 'recommendation-legit'}`}>
          <span className="recommendation-icon"><Icon name={isScam ? 'warning' : 'check'} size={18} /></span>
          <div>
            <span className="section-label">Recommended next step</span>
            <p>{isScam
              ? 'Do not send money or personal documents. Verify the employer through an official website and independent sources before taking any action.'
              : 'Proceed thoughtfully. Verify the employer and offer through an official channel before sharing personal information.'}</p>
          </div>
        </aside>
      </div>

      <details className="technical-details">
        <summary><Icon name="chart" size={16} /> View technical signals</summary>
        <div className="technical-detail-body">
          <div className="engine-summary"><span>XGBoost scam probability</span><strong>{fmtPct(result.engine?.xgboost_scam_prob)}</strong><span>Rule score</span><strong>{fmtPct(result.engine?.rule_scam_score)}</strong></div>
          <div className="signals-grid">
            {Object.entries(signals).map(([key, value]) => (
              <div className="signal-chip" key={key}><span>{key}</span><strong>{value}</strong></div>
            ))}
          </div>
        </div>
      </details>

      <div className="result-footnote"><Icon name="info" size={14} /> The verdict and probabilities above are the model response for this submitted text.</div>
    </section>
  )
}
