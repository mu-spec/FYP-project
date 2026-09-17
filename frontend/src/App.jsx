import { useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'
import Home from './components/Home.jsx'
import Analyze from './components/Analyze.jsx'
import History from './components/History.jsx'
import Insights from './components/Insights.jsx'
import About from './components/About.jsx'
import Jobs from './components/Jobs.jsx'
import AuthScreen from './components/AuthScreen.jsx'
import Icon from './components/Icon.jsx'
import { AuthProvider, useAuth } from './AuthContext.jsx'
import { analyzeJob, analyzeJobUrl, checkHealth } from './api.js'
import { runOcr } from './lib/ocrClient.js'
import {
  normalizeOcrText,
  evaluateOcrText,
  derivedTitleFromText,
  OCR_TEXT_MESSAGE,
  OCR_FAILURE_MESSAGE,
} from './lib/ocrText.js'

const PAGES = new Set(['home', 'analyze', 'jobs', 'history', 'insights', 'about'])

function initialPage() {
  const hash = window.location.hash.replace('#', '')
  return PAGES.has(hash) ? hash : 'home'
}

/**
 * Milestone 8A.1 — authentication gate.
 *
 * App start → GET /api/auth/me:
 *   - while the session check is running, NOTHING from the protected app is
 *     rendered (only a minimal branded splash);
 *   - authenticated  → the existing JobGuard application;
 *   - anonymous      → the Sign In / Create Account screen.
 * A 401 from any protected API later on drops the user and returns here.
 */
export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}

function AuthGate() {
  const { user, authLoading, signOut } = useAuth()

  if (authLoading) {
    return (
      <div className="auth-splash" role="status" aria-live="polite">
        <span className="brand-mark" aria-hidden="true">
          <Icon name="shield" size={22} strokeWidth={2} />
        </span>
        <p>Checking your session…</p>
      </div>
    )
  }
  if (!user) return <AuthScreen />
  return <JobGuardApp user={user} onSignOut={signOut} />
}

function JobGuardApp({ user, onSignOut }) {
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
  // Milestone 7C — OCR progress (null when idle) and transparency info for
  // the result view ({text, fileName} set after a successful screenshot run).
  const [ocr, setOcr] = useState(null)
  const [ocrInfo, setOcrInfo] = useState(null)

  // This ref is shared by Home and the manual Analyze form. It is the final
  // request gate, so a rapid double-click cannot create a second prediction.
  const analysisInFlight = useRef(false)
  const navigationVersion = useRef(0)

  useEffect(() => {
    const handleLocationChange = () => {
      navigationVersion.current += 1
      // Browser Back/Forward changes the URL without going through navigate().
      // Treat it as manual route entry and discard result-only source state;
      // refreshing or returning to #analyze must never replay an analysis.
      setPage(initialPage())
      setHomeAnalysisResult(false)
      setResult(null)
      setError(null)
      setInvalid(null)
      setOcrInfo(null)
      setOcr(null)
    }

    window.addEventListener('hashchange', handleLocationChange)
    window.addEventListener('popstate', handleLocationChange)
    checkHealth()
      .then((data) => { setHealth(data); setBackendUp(true) })
      .catch(() => { setBackendUp(false); setHealth(null) })
    return () => {
      window.removeEventListener('hashchange', handleLocationChange)
      window.removeEventListener('popstate', handleLocationChange)
    }
  }, [])

  function navigate(nextPage, { preserveResult = false } = {}) {
    const next = PAGES.has(nextPage) ? nextPage : 'home'
    const current = initialPage()
    navigationVersion.current += 1

    if (!preserveResult) {
      setHomeAnalysisResult(false)
      setResult(null)
      setError(null)
      setInvalid(null)
      setOcrInfo(null)
    }

    setPage(next)
    // pushState creates a real browser-history entry, so Back returns to the
    // previous app page. Do not add an entry when the active page is clicked.
    if (current !== next) window.history.pushState(null, '', `#${next}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // Shared completion path for every analysis mode: runs the EXISTING
  // /api/predict request, applies navigation-version invalidation (a Back/
  // Forward event or navigation while pending discards the stale result),
  // and routes Home-initiated flows to the result-only Analyze view.
  async function executeAnalysis(request, autoNavigate, requestNavigationVersion) {
    try {
      const data = await request()
      if (navigationVersion.current !== requestNavigationVersion) return false
      setResult(data)
      setHistoryKey((key) => key + 1)
      if (autoNavigate) {
        setHomeAnalysisResult(true)
        navigate('analyze', { preserveResult: true })
      }
      return true
    } catch (err) {
      if (navigationVersion.current !== requestNavigationVersion) return false
      if (err.invalid) setInvalid(err.message || null)
      else setError(err.message || 'The analysis service is unavailable.')
      return false
    } finally {
      analysisInFlight.current = false
      setLoading(false)
    }
  }

  async function runPrediction(jobText, title, { fromHome = false } = {}) {
    if (analysisInFlight.current) return false
    analysisInFlight.current = true
    const requestNavigationVersion = navigationVersion.current
    setLoading(true)
    setError(null)
    setInvalid(null)
    setResult(null)
    return executeAnalysis(() => analyzeJob(jobText, title), fromHome, requestNavigationVersion)
  }

  function handleHomeAnalyze(jobText, title) {
    // The existing backend validator remains the source of truth. Empty text
    // is already disabled by JobInput; all other text is sent exactly once.
    runPrediction(jobText, title, { fromHome: true })
  }

  // Milestone 8B.1 — "Analyze with JobGuard" on the Jobs page. The external
  // listing goes through the EXISTING one-click pipeline (shared in-flight
  // gate, validator, XGBoost/rules engine, per-user history) — no second
  // classifier and no special scoring for external jobs.
  function handleExternalJobAnalyze(jobText, title) {
    return runPrediction(jobText, title, { fromHome: true })
  }

  // Milestone 7B — URL analysis. Shares the in-flight gate and navigation
  // version with the text flow, so a double-click cannot create a second
  // prediction and a pending request can never overwrite a chosen page.
  // The backend fetches/extracts the text, then runs the SAME validation and
  // predict_one() pipeline; the response shape is identical to /api/predict.
  async function runUrlPrediction(url) {
    if (analysisInFlight.current) return false
    analysisInFlight.current = true
    const requestNavigationVersion = navigationVersion.current
    setLoading(true)
    setError(null)
    setInvalid(null)
    setResult(null)
    // The backend fetches/extracts the text, then runs the SAME validation and
    // predict_one() pipeline; the response shape is identical to /api/predict.
    return executeAnalysis(() => analyzeJobUrl(url), true, requestNavigationVersion)
  }

  // Milestone 7C — screenshot analysis: OCR runs in the browser, then the
  // extracted text goes through the SAME existing validation → predict_one()
  // path as pasted text. One Analyze click covers OCR + prediction; the
  // shared in-flight gate prevents double submission, and the navigation
  // version discards OCR/prediction results if the user navigates away.
  async function runImagePrediction(file) {
    if (analysisInFlight.current) return false
    analysisInFlight.current = true
    const requestNavigationVersion = navigationVersion.current
    setLoading(true)
    setError(null)
    setInvalid(null)
    setResult(null)
    try {
      setOcr({ status: 'starting', progress: 0 })
      let rawText = ''
      try {
        rawText = await runOcr(file, (m) => {
          if (navigationVersion.current === requestNavigationVersion) {
            setOcr({ status: m.status, progress: m.progress })
          }
        })
      } catch (ocrErr) {
        if (navigationVersion.current !== requestNavigationVersion) return false
        console.error('OCR failed:', ocrErr)
        setError(OCR_FAILURE_MESSAGE)
        return false
      }
      // The user navigated away while OCR ran — discard the stale result.
      if (navigationVersion.current !== requestNavigationVersion) return false

      const normalized = normalizeOcrText(rawText)
      const gate = evaluateOcrText(normalized)
      if (!gate.ok) {
        // Never send empty/garbage OCR output to the classifier.
        setError(OCR_TEXT_MESSAGE)
        return false
      }
      setOcr(null)
      const title = derivedTitleFromText(normalized)
      const ok = await executeAnalysis(() => analyzeJob(normalized, title), true, requestNavigationVersion)
      if (ok) setOcrInfo({ text: normalized, fileName: file.name })
      return ok
    } finally {
      analysisInFlight.current = false
      setLoading(false)
      setOcr(null)
    }
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
    setOcrInfo(null)
  }

  return (
    <div className="app-shell">
      <Header page={page} onNavigate={navigate} backendUp={backendUp} health={health} user={user} onSignOut={onSignOut} />
      {page === 'home' && (
        <Home
          value={draft}
          onChange={setDraft}
          onAnalyze={handleHomeAnalyze}
          onClear={handleClear}
          onAnalyzeImage={runImagePrediction}
          ocr={ocr}
          onAnalyzeUrl={runUrlPrediction}
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
          ocrInfo={ocrInfo}
        />
      )}
      {page === 'jobs' && <Jobs onAnalyzeJob={handleExternalJobAnalyze} backendUp={backendUp} />}
      {page === 'history' && <History backendUp={backendUp} refreshKey={historyKey} />}
      {page === 'insights' && <Insights backendUp={backendUp} onNavigate={navigate} />}
      {page === 'about' && <About />}
      <Footer onNavigate={navigate} />
    </div>
  )
}
