import { useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'
import Home from './components/Home.jsx'
import Analyze from './components/Analyze.jsx'
import History from './components/History.jsx'
import Insights from './components/Insights.jsx'
import About from './components/About.jsx'
import { analyzeJob, checkHealth } from './api.js'

const PAGES = new Set(['home', 'analyze', 'history', 'insights', 'about'])

function initialPage() {
  const hash = window.location.hash.replace('#', '')
  return PAGES.has(hash) ? hash : 'home'
}

export default function App() {
  const [page, setPage] = useState(initialPage)
  const [backendUp, setBackendUp] = useState(null)
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [invalid, setInvalid] = useState(null)
  const [historyKey, setHistoryKey] = useState(0)
  const [autoSubmit, setAutoSubmit] = useState(null)

  const nextAutoSubmitId = useRef(0)
  const autoSubmitInFlight = useRef(false)

  useEffect(() => {
    const handleHashChange = () => setPage(initialPage())
    window.addEventListener('hashchange', handleHashChange)
    checkHealth()
      .then((data) => { setHealth(data); setBackendUp(true) })
      .catch(() => { setBackendUp(false); setHealth(null) })
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  function navigate(nextPage) {
    const next = PAGES.has(nextPage) ? nextPage : 'home'
    // A pending Home handoff is meaningful only for the immediate Analyze
    // navigation. Discard it if the user chooses another page first.
    if (next !== 'analyze') setAutoSubmit(null)
    setPage(next)
    window.history.replaceState(null, '', `#${next}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function runPrediction(jobText, title) {
    // This is the single request gate for both automatic and manual submits.
    if (autoSubmitInFlight.current) return
    autoSubmitInFlight.current = true
    setLoading(true)
    setError(null)
    setInvalid(null)
    setResult(null)
    try {
      const data = await analyzeJob(jobText, title)
      setResult(data)
      setHistoryKey((key) => key + 1)
    } catch (err) {
      if (err.invalid) setInvalid(err.message || null)
      else setError(err.message || 'The analysis service is unavailable.')
    } finally {
      autoSubmitInFlight.current = false
      setLoading(false)
    }
  }

  function handleHomeAnalyze(jobText, title) {
    if (autoSubmitInFlight.current || autoSubmit) return
    const id = nextAutoSubmitId.current + 1
    nextAutoSubmitId.current = id
    // The intent is held in memory only. It is not encoded in the URL, so a
    // browser refresh on #analyze cannot replay it.
    setDraft(jobText)
    setAutoSubmit({ id, jobText, title })
    navigate('analyze')
  }

  function handleManualAnalyze(jobText, title) {
    runPrediction(jobText, title)
  }

  function consumeAutoSubmit(id) {
    setAutoSubmit((current) => (current?.id === id ? null : current))
  }

  function handleClear() {
    setAutoSubmit(null)
    setDraft('')
    setResult(null)
    setError(null)
    setInvalid(null)
  }

  return (
    <div className="app-shell">
      <Header page={page} onNavigate={navigate} backendUp={backendUp} health={health} />
      {page === 'home' && (
        <Home
          value={draft}
          onChange={setDraft}
          onAnalyze={handleHomeAnalyze}
          onClear={handleClear}
          loading={loading}
          onNavigate={navigate}
        />
      )}
      {page === 'analyze' && (
        <Analyze
          value={draft}
          onChange={setDraft}
          onAnalyze={handleManualAnalyze}
          onAutoSubmit={runPrediction}
          autoSubmit={autoSubmit}
          onAutoSubmitConsumed={consumeAutoSubmit}
          onClear={handleClear}
          loading={loading}
          error={error}
          invalid={invalid}
          result={result}
          backendUp={backendUp}
        />
      )}
      {page === 'history' && <History backendUp={backendUp} refreshKey={historyKey} />}
      {page === 'insights' && <Insights />}
      {page === 'about' && <About />}
      <Footer onNavigate={navigate} />
    </div>
  )
}
