import Icon from './Icon.jsx'

const PIPELINE = [
  ['file', 'Job Text', 'Paste the complete listing'],
  ['shield', 'Validation', 'Rejects empty, gibberish and non-job input'],
  ['brain', 'NLP', 'Cleans text and extracts signals'],
  ['chart', 'TF-IDF + 11 features', 'Combines text and numeric evidence'],
  ['spark', 'XGBoost', 'Returns the final classification'],
]

const METRICS = [
  ['99.98%', 'Accuracy'],
  ['1.00', 'ROC-AUC'],
  ['99.95%', 'Precision'],
  ['100%', 'Recall'],
]

export default function About() {
  return (
    <main className="page-shell">
      <div className="container-wide about-page">
        <div className="page-intro about-intro">
          <div className="eyebrow"><span className="eyebrow-line" /> About the system</div>
          <h1>Transparent screening,<br /><span>not blind trust.</span></h1>
          <p>JobGuard is an application-level screening tool for an initial review. It presents the existing model response together with the evidence that shaped the result.</p>
        </div>

        <section className="pipeline-section card-surface">
          <div className="section-heading">
            <div><span className="section-label">Under the hood</span><h2>From job text to prediction</h2></div>
            <span className="pipeline-note"><Icon name="lock" size={15} /> Existing model pipeline</span>
          </div>
          <div className="pipeline-flow">
            {PIPELINE.map(([icon, title, text], index) => (
              <div className="pipeline-step-wrap" key={title}>
                <article className="pipeline-step">
                  <span className="pipeline-icon"><Icon name={icon} size={19} /></span>
                  <strong>{title}</strong>
                  <span>{text}</span>
                </article>
                {index < PIPELINE.length - 1 && <span className="pipeline-arrow"><Icon name="chevron" size={18} /></span>}
              </div>
            ))}
            <span className="pipeline-arrow final-arrow"><Icon name="chevron" size={18} /></span>
            <article className="pipeline-step prediction-step">
              <span className="pipeline-icon"><Icon name="check" size={19} /></span>
              <strong>Prediction</strong>
              <span>Scam or Legitimate</span>
            </article>
          </div>
        </section>

        <section className="about-grid">
          <article className="model-card card-surface">
            <div className="section-heading compact-heading"><div><span className="section-label">Model snapshot</span><h2>Held-out evaluation</h2></div><span className="model-tag">XGBoost</span></div>
            <div className="metrics-grid">
              {METRICS.map(([value, label]) => <div className="about-metric" key={label}><strong>{value}</strong><span>{label}</span></div>)}
            </div>
            <div className="metric-note"><Icon name="info" size={16} /><p><strong>Important context:</strong> 99.98% is held-out test-set accuracy. It is not a guarantee of real-world accuracy, and every result should be independently verified.</p></div>
          </article>

          <article className="principles-card card-surface">
            <span className="section-label">Design principles</span>
            <h2>Useful evidence at a glance</h2>
            <ul className="principles-list">
              <li><span><Icon name="check" size={16} /></span><div><strong>Validation before ML</strong><p>Invalid submissions never reach the classifier.</p></div></li>
              <li><span><Icon name="check" size={16} /></span><div><strong>Probability, not certainty</strong><p>The result shows the returned score, not a promise.</p></div></li>
              <li><span><Icon name="check" size={16} /></span><div><strong>Human verification matters</strong><p>Confirm the employer before sharing money or data.</p></div></li>
            </ul>
          </article>
        </section>
      </div>
    </main>
  )
}
