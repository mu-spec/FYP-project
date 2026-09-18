/**
 * Milestone 8F.1 — Insights dashboard data transforms (PURE, no React).
 *
 * Every number on the Insights dashboard is computed here from the exact
 * History API records the signed-in user already owns (id, job_title,
 * prediction, confidence, created_at, evidence[]) — nothing is mocked,
 * invented or aggregated across users. The formulas mirror the original
 * 7E screen so every previously displayed value keeps the same value.
 */

/** 0..1 -> "12.3%" (clamped, same formatting as the 7E KPI cards). */
export function toPercent01(value) {
  const clamped = Math.max(0, Math.min(1, Number(value) || 0))
  return `${(clamped * 100).toFixed(1)}%`
}

/**
 * Verdict distribution for the donut — identical counting to the 7E KPIs:
 * Scam = records labelled "Scam", Legitimate = records labelled
 * "Legitimate", shares are taken over ALL records (never re-normalized).
 * Center value is the total number of analyses.
 */
export function computeVerdictDistribution(rows) {
  const list = Array.isArray(rows) ? rows : []
  const total = list.length
  const scamCount = list.filter((row) => row?.prediction === 'Scam').length
  const legitCount = list.filter((row) => row?.prediction === 'Legitimate').length
  return {
    total,
    scam: { count: scamCount, share: total ? scamCount / total : 0 },
    legitimate: { count: legitCount, share: total ? legitCount / total : 0 },
  }
}

/**
 * Confidence trend series ordered OLDEST -> NEWEST by created_at (History
 * arrives newest-first). Only records with a numeric confidence AND a
 * parsable timestamp become points — a time axis has no defensible x
 * position for an undated record, so it is excluded rather than invented.
 * No interpolation, no padding, no fake points for empty gaps.
 */
export function buildConfidenceSeries(rows) {
  const list = Array.isArray(rows) ? rows : []
  return list
    .map((row, index) => {
      const time = Date.parse(row?.created_at)
      return {
        index,
        time: Number.isFinite(time) ? time : null,
        title: row?.job_title || 'Untitled job',
        prediction: row?.prediction || '—',
        confidence: Number(row?.confidence),
      }
    })
    .filter((point) => Number.isFinite(point.confidence) && point.time !== null)
    .sort((a, b) => a.time - b.time || a.index - b.index)
}

/**
 * Warning-sign aggregation — EXACTLY the 7E derivation from saved evidence
 * maps: category falls back to message then "Detected signal"; severity is
 * the first-seen value; counts accumulate per category; sorted highest
 * count first (insertion order breaks ties); top `limit` categories.
 */
export function aggregateWarningSigns(rows, limit = 6) {
  const list = Array.isArray(rows) ? rows : []
  const categories = new Map()
  for (const row of list) {
    const evidence = Array.isArray(row?.evidence) ? row.evidence : []
    for (const flag of evidence) {
      const name = flag?.category || flag?.message || 'Detected signal'
      const severity = String(flag?.severity || 'Low').toLowerCase()
      const entry = categories.get(name) || { count: 0, severity }
      entry.count += 1
      categories.set(name, entry)
    }
  }
  return [...categories.entries()]
    .map(([category, info]) => ({ category, ...info }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
}

/** "UPFRONT PAYMENT" -> "Upfront Payment" (display-only formatting). */
export function titleCaseCategory(name) {
  const text = String(name ?? '')
  return text
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ') || text
}

/** Average decision confidence over all records (7E KPI formula). */
export function averageConfidence(rows) {
  const list = Array.isArray(rows) ? rows : []
  if (!list.length) return 0
  return list.reduce((sum, row) => sum + (Number(row?.confidence) || 0), 0) / list.length
}

/**
 * Milestone 8F.2A — Highest / Lowest / Average decision confidence computed
 * over the EXACT same series the confidence chart renders
 * (buildConfidenceSeries output — one entry per real History record). No
 * period-over-period comparisons are invented; all three are null for an
 * empty series so callers fall back to the empty state instead of showing
 * zeros that look like real measurements.
 */
export function computeTrendSummary(series) {
  const list = Array.isArray(series) ? series : []
  const values = list
    .map((point) => Number(point?.confidence))
    .filter((value) => Number.isFinite(value))
  if (!values.length) return { highest: null, lowest: null, average: null }
  return {
    highest: Math.max(...values),
    lowest: Math.min(...values),
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
  }
}
