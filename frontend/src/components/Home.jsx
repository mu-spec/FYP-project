import Icon from './Icon.jsx'
import JobInput from './JobInput.jsx'

const VALUE_POINTS = [
  {
    icon: 'brain',
    title: 'AI Analysis',
    text: 'A trained classifier reviews the wording and signals in each job post.',
  },
  {
    icon: 'file',
    title: 'Evidence-Based Results',
    text: 'See the returned probability and the red flags found in the posting.',
  },
  {
    icon: 'check',
    title: 'Clear Guidance',
    text: 'Get a direct next step instead of a confusing technical score.',
  },
]

const HOW_IT_WORKS = [
  ['01', 'Paste the job post', 'Use the complete text of the advertisement.'],
  ['02', 'Run the analysis', 'Validation checks the input before the model runs.'],
  ['03', 'Review the evidence', 'Use the verdict, probability and flags to decide what to verify.'],
]

const SCAM_WARNINGS = [
  ['Upfront fees', 'A request for registration, training or equipment money is a strong warning sign.'],
  ['Urgent pressure', 'Countdowns and “act now” language can discourage careful verification.'],
  ['Unrealistic pay', 'Very high earnings for little experience deserve extra scrutiny.'],
  ['Off-platform requests', 'Personal email, messaging apps or payment links can hide the real employer.'],
]

export default function Home({ value, onChange, onAnalyze, onClear, loading, onNavigate }) {
  return (
    <main className="home-page">
      <div className="container-wide">
        <section className="hero-section">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> AI-powered job screening</div>
            <h1>AI Job Scam<br /><span>Detector</span></h1>
            <p className="hero-tagline">Check a job before you trust it.</p>
            <p className="hero-description">
              Make a more informed first decision with a clear, evidence-led review of a job advertisement.
            </p>
            <div className="hero-proof">
              <span><Icon name="shield" size={16} /> Privacy-conscious screening</span>
              <span><Icon name="spark" size={16} /> Results in seconds</span>
            </div>
          </div>

          <div className="analysis-panel hero-analysis-panel">
            <div className="panel-kicker">Start with a job post</div>
            <div className="panel-heading-row">
              <div>
                <h2>Analyze before you apply</h2>
                <p>Paste the full listing for the most useful result.</p>
              </div>
              <span className="panel-icon"><Icon name="search" size={20} /></span>
            </div>
            <JobInput
              value={value}
              onChange={onChange}
              onAnalyze={onAnalyze}
              onClear={onClear}
              loading={loading}
              variant="home"
              showSample
            />
          </div>
        </section>

        <section className="value-grid" aria-label="Product benefits">
          {VALUE_POINTS.map((point) => (
            <article className="value-card" key={point.title}>
              <span className="feature-icon"><Icon name={point.icon} size={20} /></span>
              <div>
                <h3>{point.title}</h3>
                <p>{point.text}</p>
              </div>
            </article>
          ))}
        </section>

        <section className="section-block how-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">A simple review flow</div>
              <h2>How it works</h2>
            </div>
            <p>Designed to keep the important evidence easy to understand.</p>
          </div>
          <div className="steps-grid">
            {HOW_IT_WORKS.map(([number, title, text]) => (
              <article className="step-card" key={number}>
                <span className="step-number">{number}</span>
                <div className="step-connector" />
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="stats-strip" aria-label="System facts">
          <div className="stats-intro"><span className="eyebrow">Built for the project</span><strong>Transparent by design</strong></div>
          <div className="stat-item"><strong>25,278</strong><span>records</span></div>
          <div className="stat-item"><strong>10,000</strong><span>TF-IDF features</span></div>
          <div className="stat-item"><strong>11</strong><span>numeric features</span></div>
          <div className="stat-item"><strong>XGBoost</strong><span>classifier</span></div>
        </section>

        <section className="section-block warnings-section">
          <div className="section-heading compact-heading">
            <div>
              <div className="eyebrow">Before you trust a listing</div>
              <h2>Common warning signs</h2>
            </div>
            <button className="text-action" type="button" onClick={() => onNavigate('analyze')}>
              Run an analysis <Icon name="arrow" size={16} />
            </button>
          </div>
          <div className="warning-grid">
            {SCAM_WARNINGS.map(([title, text]) => (
              <article className="warning-card" key={title}>
                <span className="warning-icon"><Icon name="warning" size={18} /></span>
                <div><h3>{title}</h3><p>{text}</p></div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
