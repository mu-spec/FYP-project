import Icon from './Icon.jsx'

export default function Insights() {
  return (
    <main className="page-shell">
      <div className="container-narrow">
        <div className="page-intro">
          <div className="eyebrow"><span className="eyebrow-line" /> Insights</div>
          <h1>Understand the bigger picture</h1>
          <p>This space is reserved for future, evidence-based analytics. No synthetic charts or placeholder numbers are shown here.</p>
        </div>
        <section className="empty-insights card-surface">
          <span className="empty-icon"><Icon name="chart" size={27} /></span>
          <span className="section-label">Coming in a future milestone</span>
          <h2>Insights will appear here</h2>
          <p>Planned views include trends across analyzed posts, common warning signals and model review summaries once the necessary data is available.</p>
          <div className="planned-insights">
            <span><Icon name="chart" size={16} /> Verified trend summaries</span>
            <span><Icon name="history" size={16} /> History-based patterns</span>
            <span><Icon name="file" size={16} /> Evidence breakdowns</span>
          </div>
        </section>
      </div>
    </main>
  )
}
