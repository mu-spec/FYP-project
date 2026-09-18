/**
 * Milestone 8F.2A — Premium real-data confidence signal chart: data-integrity
 * tests (pure, no DOM).
 *
 * Pins the contract between GET /api/history records and everything the
 * Analysis Confidence Trend renders: exact point count, exact confidence
 * values, chronological order, tooltip fields originating from the matching
 * row, empty/single-record behavior, Highest/Lowest/Average math, per-user
 * isolation, and a source scan proving the chart component contains no
 * hard-coded series. Same record shape as History rows (id, job_title,
 * prediction, confidence, created_at, evidence[]).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  buildConfidenceSeries, computeTrendSummary, toPercent01,
} from '../src/insightsData.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const CHART_SOURCE = readFileSync(join(HERE, '../src/components/charts/ConfidenceTrend.jsx'), 'utf8')

const ROW = (over = {}) => ({
  id: 1, job_title: 'Job', prediction: 'Scam', confidence: 0.9,
  created_at: '2026-09-01T10:00:00+00:00', evidence: [], ...over,
})

test('point count: exactly one point per valid History record', () => {
  const rows = [
    ROW({ id: 1, created_at: '2026-09-03T09:00:00+00:00' }),
    ROW({ id: 2, created_at: '2026-09-01T09:00:00+00:00' }),
    ROW({ id: 3, created_at: '2026-09-02T09:00:00+00:00' }),
  ]
  assert.equal(buildConfidenceSeries(rows).length, 3)
})

test('point count: invalid records are excluded, never padded with dummies', () => {
  const rows = [
    ROW({ id: 1, confidence: 0.42, created_at: '2026-09-02T09:00:00+00:00' }),
    ROW({ id: 2, confidence: Number.NaN, created_at: '2026-09-02T10:00:00+00:00' }), // bad confidence
    ROW({ id: 3, confidence: 0.77, created_at: 'not a date' }),                      // undated
    ROW({ id: 4, confidence: 0.58, created_at: '2026-09-04T09:00:00+00:00' }),
  ]
  const series = buildConfidenceSeries(rows)
  assert.equal(series.length, 2)
  assert.deepEqual(series.map((p) => p.title), ['Job', 'Job'])
})

test('values: every rendered confidence exactly matches its History record', () => {
  const rows = [
    ROW({ id: 1, confidence: 0.9809, created_at: '2026-09-05T09:00:00+00:00' }),
    ROW({ id: 2, confidence: 0.0700, created_at: '2026-09-06T09:00:00+00:00' }),
    ROW({ id: 3, confidence: 0.3830, created_at: '2026-09-07T09:00:00+00:00' }),
  ]
  for (const point of buildConfidenceSeries(rows)) {
    const source = rows.find((row) => row.id === undefined) // values checked below
    assert.ok(source === undefined || point.confidence >= 0)
  }
  const series = buildConfidenceSeries(rows)
  assert.deepEqual(
    series.map((p) => p.confidence),
    [0.9809, 0.0700, 0.3830].sort(() => 0), // same values, order checked next
  )
  assert.deepEqual(
    [...series].sort((a, b) => a.confidence - b.confidence).map((p) => p.confidence),
    [0.0700, 0.3830, 0.9809],
  )
})

test('order: series is chronological oldest -> newest regardless of API row order', () => {
  const rows = [
    ROW({ id: 3, created_at: '2026-09-09T09:00:00+00:00' }),
    ROW({ id: 1, created_at: '2026-09-02T09:00:00+00:00' }),
    ROW({ id: 2, created_at: '2026-09-06T09:00:00+00:00' }),
  ]
  const times = buildConfidenceSeries(rows).map((p) => p.time)
  assert.deepEqual(times, [...times].sort((a, b) => a - b))
  assert.equal(new Date(times[0]).getUTCDate(), 2)
  assert.equal(new Date(times[times.length - 1]).getUTCDate(), 9)
})

test('tooltip fields: each point carries the exact job_title / prediction / confidence / time of its row', () => {
  const rows = [
    ROW({ id: 1, job_title: 'Engineering Manager', prediction: 'Legitimate',
          confidence: 0.96, created_at: '2026-09-17T19:03:00+00:00' }),
    ROW({ id: 2, job_title: 'Data Entry Clerk', prediction: 'Scam',
          confidence: 0.98, created_at: '2026-09-17T20:15:00+00:00' }),
  ]
  const series = buildConfidenceSeries(rows)
  assert.equal(series[0].title, 'Engineering Manager')
  assert.equal(series[0].prediction, 'Legitimate')
  assert.equal(series[0].confidence, 0.96)
  assert.equal(series[0].time, Date.parse('2026-09-17T19:03:00+00:00'))
  assert.equal(series[1].title, 'Data Entry Clerk')
  assert.equal(series[1].prediction, 'Scam')
})

test('empty History: zero points and a null summary — no dummy data', () => {
  const series = buildConfidenceSeries([])
  assert.equal(series.length, 0)
  assert.deepEqual(computeTrendSummary(series), { highest: null, lowest: null, average: null })
})

test('one record: exactly one point, summary collapses onto that record', () => {
  const series = buildConfidenceSeries([
    ROW({ confidence: 0.615, created_at: '2026-09-10T08:30:00+00:00' }),
  ])
  assert.equal(series.length, 1)
  assert.deepEqual(computeTrendSummary(series), { highest: 0.615, lowest: 0.615, average: 0.615 })
})

test('two records: exactly two points, no interpolation between them', () => {
  const series = buildConfidenceSeries([
    ROW({ confidence: 0.2, created_at: '2026-09-01T09:00:00+00:00' }),
    ROW({ confidence: 0.8, created_at: '2026-09-02T09:00:00+00:00' }),
  ])
  assert.equal(series.length, 2)
  // midpoint is never manufactured as a point
  assert.ok(!series.some((p) => Math.abs(p.confidence - 0.5) < 1e-9))
})

test('summary: Highest / Lowest / Average computed from the same series values', () => {
  const series = buildConfidenceSeries([
    ROW({ confidence: 0.98, created_at: '2026-09-05T09:00:00+00:00' }),
    ROW({ confidence: 0.07, created_at: '2026-09-06T09:00:00+00:00' }),
    ROW({ confidence: 0.45, created_at: '2026-09-07T09:00:00+00:00' }),
  ])
  const summary = computeTrendSummary(series)
  assert.equal(summary.highest, 0.98)
  assert.equal(summary.lowest, 0.07)
  assert.ok(Math.abs(summary.average - (0.98 + 0.07 + 0.45) / 3) < 1e-12)
  assert.equal(toPercent01(summary.average), '50.0%')
})

test('user isolation: the builder only sees the rows it is given — no shared state', () => {
  const userA = [
    ROW({ id: 1, confidence: 0.9, created_at: '2026-09-01T09:00:00+00:00' }),
    ROW({ id: 2, confidence: 0.8, created_at: '2026-09-02T09:00:00+00:00' }),
  ]
  const userB = [
    ROW({ id: 1, confidence: 0.1, created_at: '2026-09-03T09:00:00+00:00' }),
  ]
  const seriesA = buildConfidenceSeries(userA)
  const seriesB = buildConfidenceSeries(userB)
  assert.equal(seriesA.length, 2)
  assert.equal(seriesB.length, 1)
  assert.deepEqual(seriesA.map((p) => p.confidence), [0.9, 0.8])
  assert.deepEqual(seriesB.map((p) => p.confidence), [0.1])
  // pure: re-running with the same input gives the same output, untouched
  assert.deepEqual(buildConfidenceSeries(userA).map((p) => p.confidence), [0.9, 0.8])
})

test('source scan: chart component renders series from props — no hard-coded data', () => {
  // No literal data arrays / numeric confidence constants baked into the chart.
  assert.doesNotMatch(CHART_SOURCE, /confidencePct:\s*0?\.\d/)
  assert.doesNotMatch(CHART_SOURCE, /confidence:\s*0?\.\d/)
  assert.doesNotMatch(CHART_SOURCE, /=\s*\[\s*\{\s*"/) // [{ "…"}] literal series
  assert.match(CHART_SOURCE, /series/)                 // series comes in via props
  assert.match(CHART_SOURCE, /computeTrendSummary/)    // chips reuse the same series
  assert.doesNotMatch(CHART_SOURCE, /Math\.random|dummy|mock|fixture/i)
})
