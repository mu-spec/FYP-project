import { useEffect, useRef } from 'react'
import Icon from './Icon.jsx'
import JobInput from './JobInput.jsx'
import ResultCard from './ResultCard.jsx'
import InvalidResult from './InvalidResult.jsx'

export default function Analyze({
  value,
  onChange,
  onAnalyze,
  onAutoSubmit,
  autoSubmit,
  onAutoSubmitConsumed,
  onClear,
  loading,
  error,
  invalid,
  result,
  backendUp,
}) {
  const consumedAutoSubmitId = useRef(null)

  useEffect(() => {
    if (!autoSubmit?.jobText || consumedAutoSubmitId.current === autoSubmit.id) return

    // Analyze owns the route-entry handoff. Mark it consumed before calling the
    // request so re-renders, StrictMode and the state-clearing update cannot
    // submit the same Home payload a second time.
    consumedAutoSubmitId.current = autoSubmit.id
    const { id, jobText, title } = autoSubmit
    onAutoSubmitConsumed?.(id)
    onAutoSubmit?.(jobText, title)
  }, [autoSubmit, onAutoSubmit, onAutoSubmitConsumed])

  return (
    <main className="page-shell analyze-page">
      <div className="container-narrow">
        <div className="page-intro">
          <div className="eyebrow"><span className="eyebrow-line" /> Analysis workspace</div>
          <h1>Review a job posting</h1>
          <p>Paste the listing below. The text is validated first, then analyzed with the existing NLP and XGBoost pipeline.</p>
        </div>

        <section className="analysis-card card-surface">
          <div className="analysis-card-header">
            <div>
              <span className="section-label">Job description</span>
              <h2>What are you being offered?</h2>
            </div>
            <span className="secure-label"><Icon name="lock" size={15} /> Pre-screened before analysis</span>
          </div>
          <JobInput
            value={value}
            onChange={onChange}
            onAnalyze={onAnalyze}
            onClear={onClear}
            loading={loading}
            variant="analysis"
          />
        </section>

        {error && (
          <div className="inline-alert error-alert" role="alert">
            <Icon name="warning" size={18} />
            <div><strong>We could not complete the analysis.</strong><span>{error}{!backendUp && ' Check that the Flask backend is running.'}</span></div>
          </div>
        )}

        {invalid && <InvalidResult message={invalid} />}
        {result && <ResultCard result={result} />}
      </div>
    </main>
  )
}
