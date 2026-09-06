import { useState } from 'react'

// PRD 5.2 — Job Input Module: paste job description + Analyze & Clear buttons
const SAMPLE = `Warehouse Associate — Earn $6,000/week from home!
NO experience needed, NO degree required. Immediate hiring, positions filling FAST!
Just pay a $99 registration fee to secure your spot. Contact hiring.manager2024@gmail.com
or WhatsApp +1 555 012 3456. Apply now at www.quick-hire-jobs.biz !!!`

export default function JobInput({ onAnalyze, onClear, loading }) {
  const [text, setText] = useState('')

  const charCount = text.length
  const tooShort = charCount > 0 && charCount < 40

  // History needs a job title → use the first line of the pasted post
  const derivedTitle = text.split('\n').map((l) => l.trim()).find(Boolean) || 'Untitled job'

  function handleClear() {
    setText('')
    onClear?.()
  }

  return (
    <div className="card">
      <textarea
        className="textarea"
        rows={10}
        placeholder="Paste the complete job post here…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="textarea-meta">
        <span className={tooShort ? 'warn-text' : ''}>
          {charCount} characters {tooShort && '— too short, paste more text'}
        </span>
        <button type="button" className="link-btn" onClick={() => setText(SAMPLE)}>
          Load sample scam post
        </button>
      </div>

      <div className="btn-row">
        <button
          className="btn btn-primary"
          disabled={loading || charCount < 40}
          onClick={() => onAnalyze(text, derivedTitle.slice(0, 120))}
        >
          {loading ? '⏳ Analyzing…' : '🔍 Analyze Job'}
        </button>
        <button
          className="btn btn-secondary"
          disabled={loading || (charCount === 0)}
          onClick={handleClear}
        >
          ✖ Clear
        </button>
      </div>
    </div>
  )
}
