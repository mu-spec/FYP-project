import Icon from './Icon.jsx'

export default function InvalidResult({ message }) {
  return (
    <section className="invalid-result card-surface" role="alert">
      <div className="invalid-result-header">
        <span className="state-icon caution"><Icon name="warning" size={21} /></span>
        <div>
          <span className="section-label">Input not analyzed</span>
          <h2>Invalid Job Description</h2>
        </div>
        <span className="state-badge caution-badge">Not analyzed</span>
      </div>
      <p className="invalid-result-message">
        {message || 'The provided text does not appear to be a valid job description. Please paste a complete job advertisement.'}
      </p>
      <div className="invalid-next-step">
        <strong>Try again with a complete listing.</strong>
        <span>Include the role, project scope, responsibilities or required skills. The model was not run for this input.</span>
      </div>
    </section>
  )
}
