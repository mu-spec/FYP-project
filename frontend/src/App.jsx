import { useEffect, useState } from 'react'
import JobInput from './components/JobInput.jsx'
import ResultCard from './components/ResultCard.jsx'
import InvalidResult from './components/InvalidResult.jsx'
import History from './components/History.jsx'
import { analyzeJob, checkHealth } from './api.js'

export default function App() {
  const [backendUp, setBackendUp] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [invalid, setInvalid] = useState(null)
  const [historyKey, setHistoryKey] = useState(0)

  useEffect(() => {
    checkHealth().then(() => setBackendUp(true)).catch(() => setBackendUp(false))
  }, [])

  async function handleAnalyze(jobText, title) {
    setLoading(true); setError(null); setResult(null); setInvalid(null)
    try {
      const data = await analyzeJob(jobText, title)
      // A valid prediction reached the ML pipeline -> show it & refresh history.
      setResult(data)
      setHistoryKey((k) => k + 1) // refresh history module
    } catch (e) {
      if (e.invalid) {
        // Backend rejected the input before ML -> dedicated "Invalid" card.
        setInvalid(e.message || null)
      } else {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }

  function handleClear() {
    setResult(null)
    setError(null)
    setInvalid(null)
  }

  return (
    <div className="app">
      {/* ===== Title only ===== */}
      <header className="app-header">
        <h1 className="app-title">AI-Based Job Scam Detection</h1>
        <p className="app-subtitle">
          Paste any job post below — the AI will tell you if it's a Scam or Legitimate.
        </p>
      </header>

      <main className="container">
        {/* ===== Input field + Analyze / Clear buttons ===== */}
        <JobInput onAnalyze={handleAnalyze} onClear={handleClear} loading={loading} />

        {error && (
          <div className="alert alert-error">
            ❌ {error}
            {!backendUp && <span> — is the Flask backend running? (<code>cd backend && python app.py</code>)</span>}
          </div>
        )}

        {/* ===== Result card ===== */}
        {invalid && <InvalidResult message={invalid} />}
        {result && <ResultCard result={result} />}

        {/* ===== Search history ===== */}
        <History key={historyKey} backendUp={backendUp} />
      </main>
    </div>
  )
}
