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
  const [pendingAnalysis, setPendingAnalysis] = useState(null)

  // Refs make the one-time navigation intent safe against React StrictMode,
  // rapid clicks, and the render that occurs between navigation and the effect.
  const nextAnalysisId = useRef(0)
  const consumedAnalysisId = useRef(null)
  const pendingHomeIntent = useRef(false)
  const analysisInFlight = useRef(false)

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
    // A navigation away from Analyze must not leave a stale Home intent that
    // could submit later after an unrelated navigation.
    if (next !== 'analyze') {
      setPendingAnalysis(null)
      pendingHomeIntent.current = false
    }
    setPage(next)
    window.history.replaceState(null, '', `#${next}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function runPrediction(jobText, title) {
    // Both Home auto-submit and the direct Analyze button use this guard, so
    // only one request can be active even during a rapid double-click.
    if (analysisInFlight.current) return
    analysisInFlight.current = true
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
      analysisInFlight.current = false
      setLoading(false)
    }
  }

  function handleHomeAnalyze(jobText, title) {
    if (analysisInFlight.current || pendingHomeIntent.current) return
    pendingHomeIntent.current = true
    const id = nextAnalysisId.current + 1
    nextAnalysisId.current = id
    setDraft(jobText)
    setPendingAnalysis({ id, jobText, title })
    navigate('analyze')
  }

  function handleManualAnalyze(jobText, title) {
    runPrediction(jobText, title)
  }

  useEffect(() => {
    if (page !== 'analyze' || !pendingAnalysis) return
    if (consumedAnalysisId.current === pendingAnalysis.id) return

    // Consume before starting the request. If the component re-renders or
    // StrictMode repeats the effect, the same navigation intent cannot submit
    // again. Refreshing the browser also cannot replay it because this state
    // is intentionally not persisted in the URL or local storage.
    consumedAnalysisId.current = pendingAnalysis.id
    pendingHomeIntent.current = false
    const { jobText, title } = pendingAnalysis
    setPendingAnalysis(null)
    runPrediction(jobText, title)
  }, [page, pendingAnalysis])

  function handleClear() {
    setPendingAnalysis(null)
    pendingHomeIntent.current = false
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
