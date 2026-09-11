import Icon from './Icon.jsx'

const SAMPLE = `Warehouse Associate — Earn $6,000/week from home!
NO experience needed, NO degree required. Immediate hiring, positions filling FAST!
Just pay a $99 registration fee to secure your spot. Contact hiring.manager2024@gmail.com
or WhatsApp +1 555 012 3456. Apply now at www.quick-hire-jobs.biz !!!`

export default function JobInput({
  value = '',
  onChange,
  onAnalyze,
  onClear,
  loading = false,
  variant = 'analysis',
  showSample = false,
}) {
  const text = value || ''
  const charCount = text.length
  const hasText = text.trim().length > 0
  const tooLong = charCount > 50_000
  const derivedTitle = text.split('\n').map((line) => line.trim()).find(Boolean) || 'Untitled job'

  const validationMessage = !hasText
    ? 'Paste a job description to continue.'
    : tooLong
      ? 'This description is too long. The maximum is 50,000 characters.'
      : 'Short genuine posts can pass; non-job or gibberish text is rejected before ML analysis.'

  function handleAnalyze() {
    if (!hasText || tooLong || loading) return
    onAnalyze?.(text, derivedTitle.slice(0, 120))
  }

  return (
    <div className={`job-input ${variant}`}>
      <label className="sr-only" htmlFor={`${variant}-job-text`}>Job description</label>
      <textarea
        id={`${variant}-job-text`}
        className="job-textarea"
        rows={variant === 'home' ? 7 : 13}
        placeholder="Paste the complete job advertisement here…"
        value={text}
        onChange={(event) => onChange?.(event.target.value)}
        aria-describedby={`${variant}-input-note`}
      />
      <div className="input-meta">
        <span className={tooLong ? 'validation-error' : ''}>
          {charCount.toLocaleString()} characters
        </span>
        {showSample && (
          <button type="button" className="sample-link" onClick={() => onChange?.(SAMPLE)}>
            Use sample post
          </button>
        )}
      </div>
      <div id={`${variant}-input-note`} className={`input-note ${!hasText || tooLong ? 'attention' : ''}`}>
        <span className="input-note-icon"><Icon name={tooLong ? 'warning' : 'info'} size={14} /></span>
        <span>{validationMessage}</span>
      </div>
      <div className="input-actions">
        <button
          type="button"
          className="btn btn-primary btn-analyze"
          disabled={loading || !hasText || tooLong}
          onClick={handleAnalyze}
        >
          <Icon name="search" size={18} />
          {loading ? 'Analyzing…' : 'Analyze Job'}
        </button>
        {hasText && (
          <button type="button" className="quiet-action" onClick={() => onClear?.()} disabled={loading}>
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
