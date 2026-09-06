// PRD 5.1 — Home Page: project title + "Detect Scam" button
export default function Home({ onDetectClick }) {
  return (
    <section className="hero" id="home">
      <div className="container hero-inner">
        <span className="hero-badge">Final Year Project</span>
        <h1 className="hero-title">AI-Based Job Scam Detection</h1>
        <p className="hero-subtitle">
          Paste any job advertisement and our XGBoost model will classify it as
          <strong> Scam</strong> or <strong>Legitimate</strong> — with confidence
          scores and detected red flags.
        </p>
        <div className="hero-actions">
          <button className="btn btn-primary btn-lg" onClick={onDetectClick}>
            🔍 Detect Scam
          </button>
        </div>
        <div className="hero-stats">
          <div className="stat"><span className="stat-num">27k+</span><span className="stat-label">Training samples</span></div>
          <div className="stat"><span className="stat-num">XGBoost</span><span className="stat-label">Classifier</span></div>
          <div className="stat"><span className="stat-num">TF-IDF</span><span className="stat-label">+ 11 signals</span></div>
          <div className="stat"><span className="stat-num">&lt;2s</span><span className="stat-label">Prediction</span></div>
        </div>
      </div>
    </section>
  )
}
