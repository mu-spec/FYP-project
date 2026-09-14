import { useRef, useState } from 'react'
import Icon from './Icon.jsx'

const ACCEPT = '.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp'

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function ocrStatusLabel(ocr) {
  if (!ocr) return null
  const status = ocr.status || ''
  if (status === 'recognizing text') {
    const pct = Math.round((ocr.progress || 0) * 100)
    return `Reading image… ${pct}%`
  }
  if (status === 'loading language traineddata' || status === 'loading tesseract core' ||
      status === 'initializing tesseract' || status === 'initializing api' || status === 'starting') {
    return 'Preparing text reader…'
  }
  return 'Reading image…'
}

/**
 * Milestone 7C — Upload Screenshot mode for the Home analysis card.
 * One Analyze click: browser-side OCR runs, then the extracted text flows
 * through the existing validation → prediction pipeline.
 */
export default function JobImageInput({
  file,
  preview,
  busy = false,
  ocr = null,
  uploadError = null,
  onSelect,
  onRemove,
  onPreviewError,
  onAnalyze,
}) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const ocrLabel = ocrStatusLabel(ocr)
  const progressPct = ocr && typeof ocr.progress === 'number'
    ? Math.round(ocr.progress * 100)
    : null

  function openPicker() {
    if (!busy) inputRef.current?.click()
  }

  function handleInputChange(event) {
    const selected = event.target.files && event.target.files[0]
    event.target.value = '' // allow re-selecting the same file after Remove
    if (selected) onSelect?.(selected)
  }

  function handleDrop(event) {
    event.preventDefault()
    setDragging(false)
    if (busy) return
    const dropped = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]
    if (dropped) onSelect?.(dropped)
  }

  return (
    <div className="job-input job-image-input">
      <input
        ref={inputRef}
        id="home-job-image"
        type="file"
        accept={ACCEPT}
        className="sr-only"
        disabled={busy}
        onChange={handleInputChange}
      />

      {!file ? (
        <div
          className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''}`}
          role="button"
          tabIndex={0}
          aria-label="Select a job screenshot"
          onClick={openPicker}
          onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openPicker() } }}
          onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          <span className="dropzone-icon"><Icon name="image" size={26} /></span>
          <span className="dropzone-title">Drag &amp; drop a job screenshot here</span>
          <span className="dropzone-or">or</span>
          <span className="dropzone-select"><Icon name="upload" size={15} /> Select Image</span>
          <span className="dropzone-hint">PNG, JPG or WEBP · up to 8 MB · runs privately in your browser</span>
        </div>
      ) : (
        <div className="image-selection">
          <div className="image-preview-frame">
            {preview
              ? <img className="image-preview" src={preview} alt="Selected job screenshot preview" onError={onPreviewError} />
              : <span className="image-preview-placeholder"><Icon name="image" size={26} /></span>}
          </div>
          <div className="image-meta">
            <strong className="image-name" title={file.name}>{file.name}</strong>
            <span className="image-size">{formatBytes(file.size)}</span>
            <div className="image-actions">
              <button type="button" className="mini-action" onClick={openPicker} disabled={busy}>
                <Icon name="image" size={14} /> Replace
              </button>
              <button type="button" className="mini-action danger" onClick={() => !busy && onRemove?.()} disabled={busy}>
                <Icon name="trash" size={14} /> Remove
              </button>
            </div>
          </div>
        </div>
      )}

      {uploadError && (
        <div className="input-note attention upload-error" role="alert">
          <span className="input-note-icon"><Icon name="warning" size={14} /></span>
          <span>{uploadError}</span>
        </div>
      )}

      {!uploadError && (
        <div className="input-note">
          <span className="input-note-icon"><Icon name="info" size={14} /></span>
          <span>
            The text is read from your screenshot in the browser, then the same validation
            and analysis run. The image itself is never uploaded.
          </span>
        </div>
      )}

      {ocr && (
        <div className="ocr-progress" role="status">
          <span className="ocr-progress-label">{ocrLabel}</span>
          <div className="ocr-progress-track">
            <div
              className={`ocr-progress-fill ${progressPct === null ? 'indeterminate' : ''}`}
              style={progressPct === null ? undefined : { width: `${Math.max(4, progressPct)}%` }}
            />
          </div>
        </div>
      )}

      <div className="input-actions">
        <button
          type="button"
          className={`btn btn-primary btn-analyze ${busy ? 'is-loading' : ''}`}
          disabled={busy || !file}
          aria-busy={busy}
          onClick={() => onAnalyze?.(file)}
        >
          <Icon name="search" size={18} />
          {busy ? (ocr ? 'Reading image…' : 'Analyzing…') : 'Analyze Screenshot'}
        </button>
        {file && !busy && (
          <button type="button" className="quiet-action" onClick={onRemove}>
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
