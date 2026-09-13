import Icon from './Icon.jsx'

/**
 * Milestone 7B — Job URL input mode for the Home analysis card.
 * One click of Analyze: the backend fetches the public page (SSRF-protected),
 * extracts the job text, then runs the same validation + prediction pipeline.
 */
export default function JobUrlInput({
  value = '',
  onChange,
  onAnalyze,
  onClear,
  loading = false,
}) {
  const url = (value || '').trim()
  const hasUrl = url.length > 0

  function handleAnalyze() {
    if (!hasUrl || loading) return
    onAnalyze?.(url)
  }

  return (
    <div className="job-input job-url-input">
      <label className="sr-only" htmlFor="home-job-url">Job posting URL</label>
      <div className="url-field">
        <span className="url-field-icon"><Icon name="link" size={17} /></span>
        <input
          id="home-job-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="Paste a public job posting link (https://…)"
          value={value}
          disabled={loading}
          onChange={(event) => onChange?.(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') handleAnalyze() }}
        />
      </div>
      <div className="input-note">
        <span className="input-note-icon"><Icon name="info" size={14} /></span>
        <span>
          The page is fetched, the job text is extracted, then the same validation and
          analysis run. Public links only — private/internal addresses are rejected.
        </span>
      </div>
      <div className="input-actions">
        <button
          type="button"
          className={`btn btn-primary btn-analyze ${loading ? 'is-loading' : ''}`}
          disabled={loading || !hasUrl}
          aria-busy={loading}
          onClick={handleAnalyze}
        >
          <Icon name="search" size={18} />
          {loading ? 'Fetching & analyzing…' : 'Analyze Job'}
        </button>
        {hasUrl && (
          <button type="button" className="quiet-action" onClick={() => onClear?.()} disabled={loading}>
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
