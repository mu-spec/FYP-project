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
  const [homeAnalysisResult, setHomeAnalysisResult] = useState(false)

  // This ref is shared by Home and the manual Analyze form. It is the final
  // request gate, so a rapid double-click cannot create a second prediction.
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
    // A result-only Analyze view is valid only for the current Home success.
    // Any later navigation resets that source marker. It is not persisted, so
    // refreshing #analyze always behaves like direct/manual navigation.
    if (next !== 'analyze') setHomeAnalysisResult(false)
    setPage(next)
    window.history.replaceState(null, '', `#${next}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function runPrediction(jobText, title, { fromHome = false } = {}) {
    if (analysisInFlight.current) return false
    analysisInFlight.current = true
    setLoading(true)
    setError(null)
    setInvalid(null)
    setResult(null)
    try {
      const data = await analyzeJob(jobText, title)
      setResult(data)
      setHistoryKey((key) => key + 1)
      if (fromHome) {
        // The request has already completed successfully. Navigate directly
        // to the result view; Analyze will not render its manual intro/form.
        setHomeAnalysisResult(true)
        navigate('analyze')
      }
      return true
    } catch (err) {
      if (err.invalid) setInvalid(err.message || null)
      else setError(err.message || 'The analysis service is unavailable.')
      // Invalid/network failures stay on Home when Home initiated the request.
      // This prevents an unnecessary route change with no result to show.
      return false
    } finally {
      analysisInFlight.current = false
      setLoading(false)
    }
  }

  function handleHomeAnalyze(jobText, title) {
    // The existing backend validator remains the source of truth. Empty text
    // is already disabled by JobInput; all other text is sent exactly once.
    runPrediction(jobText, title, { fromHome: true })
  }

  function handleManualAnalyze(jobText, title) {
    setHomeAnalysisResult(false)
    runPrediction(jobText, title)
  }

  function handleClear() {
    setHomeAnalysisResult(false)
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
          invalid={invalid}
          error={error}
          backendUp={backendUp}
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
          homeInitiated={homeAnalysisResult}
        />
      )}
      {page === 'history' && <History backendUp={backendUp} refreshKey={historyKey} />}
      {page === 'insights' && <Insights />}
      {page === 'about' && <About />}
      <Footer onNavigate={navigate} />
    </div>
  )
}
