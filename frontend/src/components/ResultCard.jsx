import Icon from './Icon.jsx'

const clamp = (value) => Math.max(0, Math.min(1, Number(value) || 0))
const fmtPct = (value) => `${(clamp(value) * 100).toFixed(2)}%`
const SEVERITY_ORDER = ['High', 'Medium', 'Low']

function riskLevel(probability) {
  if (probability >= 0.75) return ['High risk', 'high']
  if (probability >= 0.5) return ['Elevated risk', 'elevated']
  if (probability >= 0.25) return ['Caution', 'caution']
  return ['Lower risk', 'lower']
}

function EvidenceCard({ flag }) {
  const evidence = Array.isArray(flag.evidence) ? flag.evidence.filter(Boolean) : []
  const severity = flag.severity || 'Low'

  return (
    <article className={`evidence-card evidence-${severity.toLowerCase()}`}>
      <div className="evidence-card-top">
        <div className="evidence-category">
          <span className="flag-marker"><Icon name="warning" size={15} /></span>
          <strong>{flag.category || 'DETECTED SIGNAL'}</strong>
        </div>
        <span className={`severity-badge severity-${severity.toLowerCase()}`}>{severity}</span>
      </div>
      {evidence.length > 0 && (
        <div className="evidence-snippets" aria-label="Matched text from the job description">
          {evidence.map((snippet, index) => (
            <blockquote key={`${snippet}-${index}`}>“{snippet}”</blockquote>
          ))}
        </div>
      )}
      <p className="evidence-explanation">{flag.explanation || flag.message}</p>
    </article>
  )
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
  const isScam = prediction === 'Scam'
  const [riskLabel, riskTone] = riskLevel(scamProbability)
  const groupedFlags = SEVERITY_ORDER
    .map((severity) => ({ severity, flags: redFlags.filter((flag) => flag.severity === severity) }))
    .filter((group) => group.flags.length > 0)

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

      <div className="evidence-map-panel">
        <div className="evidence-map-heading">
          <div>
            <span className="section-label">Evidence map</span>
            <h3>Text signals found in the posting</h3>
            <p>Each item below is linked to a deterministic rule that fired on this submitted text.</p>
          </div>
          <span className={`count-badge ${redFlags.length ? 'has-flags' : 'no-flag-badge'}`}>{redFlags.length}</span>
        </div>

        {groupedFlags.length > 0 ? (
          <div className="evidence-groups">
            {groupedFlags.map((group) => (
              <section className="evidence-group" key={group.severity}>
                <div className={`severity-heading severity-heading-${group.severity.toLowerCase()}`}><span />{group.severity} severity</div>
                <div className="evidence-list">
                  {group.flags.map((flag, index) => <EvidenceCard key={`${flag.category || flag.message}-${index}`} flag={flag} />)}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="no-flags-state">
            <span><Icon name="check" size={17} /></span>
            <div>
              <p>No major scam indicators were detected.</p>
              <small>This does not guarantee employer legitimacy. Verify the employer independently before sharing money or personal information.</small>
            </div>
          </div>
        )}
      </div>

      <aside className={`recommendation-panel ${isScam ? 'recommendation-scam' : 'recommendation-legit'}`}>
        <span className="recommendation-icon"><Icon name={isScam ? 'warning' : 'check'} size={18} /></span>
        <div>
          <span className="section-label">Recommended next step</span>
          <p>{isScam
            ? 'Do not send money or personal documents. Verify the employer through an official website and independent sources before taking any action.'
            : 'Proceed thoughtfully. Verify the employer and offer through an official channel before sharing personal information.'}</p>
        </div>
      </aside>

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
