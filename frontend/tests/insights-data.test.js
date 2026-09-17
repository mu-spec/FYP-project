/**
 * Milestone 8F.1 — Insights dashboard data transforms (pure, no DOM).
 *
 * Pins the exact formulas the charts render: verdict distribution,
 * confidence-series ordering, warning-sign aggregation, percentage
 * formatting, and the empty / single-record edge cases. Same record shape
 * as GET /api/history (id, job_title, prediction, confidence, created_at,
 * evidence[]).
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  toPercent01, computeVerdictDistribution, buildConfidenceSeries,
  aggregateWarningSigns, titleCaseCategory, averageConfidence,
} from '../src/insightsData.js'

const ROW = (over = {}) => ({
  id: 1, job_title: 'Job', prediction: 'Scam', confidence: 0.9,
  created_at: '2026-09-01T10:00:00+00:00', evidence: [], ...over,
})

test('verdict distribution: counts and shares over all records', () => {
  const rows = [
    ROW({ prediction: 'Scam', confidence: 0.98 }),
    ROW({ prediction: 'Scam' }),
    ROW({ prediction: 'Legitimate', confidence: 0.81 }),
    ROW({ prediction: 'Legitimate' }),
    ROW({ prediction: 'Legitimate' }),
  ]
  const dist = computeVerdictDistribution(rows)
  assert.equal(dist.total, 5)
  assert.equal(dist.scam.count, 2)
  assert.equal(dist.legitimate.count, 3)
  assert.equal(dist.scam.share, 2 / 5)
  assert.equal(dist.legitimate.share, 3 / 5)
})

test('verdict distribution: empty data -> all zeros, no NaN', () => {
  const dist = computeVerdictDistribution([])
  assert.deepEqual(dist, {
    total: 0,
    scam: { count: 0, share: 0 },
    legitimate: { count: 0, share: 0 },
  })
  assert.equal(computeVerdictDistribution(null).total, 0)
})

test('confidence series: unsorted newest-first History becomes oldest->newest', () => {
  const rows = [
    ROW({ id: 3, created_at: '2026-09-03T09:00:00Z', confidence: 0.7 }),
    ROW({ id: 1, created_at: '2026-09-01T09:00:00Z', confidence: 0.9 }),
    ROW({ id: 2, created_at: '2026-09-02T09:00:00Z', confidence: 0.8 }),
  ]
  const series = buildConfidenceSeries(rows)
  assert.deepEqual(series.map((p) => p.time), [
    Date.parse('2026-09-01T09:00:00Z'),
    Date.parse('2026-09-02T09:00:00Z'),
    Date.parse('2026-09-03T09:00:00Z'),
  ])
  assert.deepEqual(series.map((p) => p.confidence), [0.9, 0.8, 0.7])
})

test('confidence series: single record and unparsable dates stay stable', () => {
  const single = buildConfidenceSeries([ROW()])
  assert.equal(single.length, 1)
  assert.equal(single[0].title, 'Job')
  // undated records have no defensible x position -> excluded, never invented
  const weird = buildConfidenceSeries([
    ROW({ id: 2, created_at: 'not-a-date', confidence: 0.5 }),
    ROW({ id: 1, created_at: '2026-09-01T09:00:00Z', confidence: 0.6 }),
  ])
  assert.equal(weird.length, 1)
  assert.equal(weird[0].time, Date.parse('2026-09-01T09:00:00Z'))
  assert.equal(weird[0].confidence, 0.6)
})

test('warning-sign aggregation: counts accumulate and sort highest first', () => {
  const rows = [
    ROW({ evidence: [
      { category: 'UPFRONT PAYMENT', severity: 'High' },
      { category: 'URGENCY PRESSURE', severity: 'Medium' },
    ] }),
    ROW({ evidence: [{ category: 'UPFRONT PAYMENT', severity: 'Low' }] }),
    ROW({ evidence: [] }),
  ]
  const flags = aggregateWarningSigns(rows)
  assert.equal(flags.length, 2)
  assert.deepEqual(flags[0], { category: 'UPFRONT PAYMENT', count: 2, severity: 'high' })
  assert.deepEqual(flags[1], { category: 'URGENCY PRESSURE', count: 1, severity: 'medium' })
  // limit keeps the chart readable (top 6 by default)
  const many = aggregateWarningSigns(
    [ROW({ evidence: 'abcdef'.split('').map((c) => ({ category: c })) })], 6)
  assert.equal(many.length, 6)
})

test('warning-sign aggregation: empty data -> empty list', () => {
  assert.deepEqual(aggregateWarningSigns([]), [])
  assert.deepEqual(aggregateWarningSigns(null), [])
  assert.deepEqual(aggregateWarningSigns([ROW({ evidence: [] })]), [])
})

test('percentage calculation: clamps and formats like the 7E KPI cards', () => {
  assert.equal(toPercent01(0.981), '98.1%')
  assert.equal(toPercent01(0), '0.0%')
  assert.equal(toPercent01(1), '100.0%')
  assert.equal(toPercent01(1.4), '100.0%')   // clamped high
  assert.equal(toPercent01(-0.2), '0.0%')    // clamped low
  assert.equal(toPercent01('junk'), '0.0%')  // never NaN on the page
  assert.equal(toPercent01(undefined), '0.0%')
})

test('display helpers: title-case categories, average confidence parity', () => {
  assert.equal(titleCaseCategory('UPFRONT PAYMENT'), 'Upfront Payment')
  assert.equal(titleCaseCategory('EXCESSIVE CAPITALIZATION'), 'Excessive Capitalization')
  assert.ok(Math.abs(averageConfidence([ROW({ confidence: 0.9 }), ROW({ confidence: 0.8 })]) - 0.85) < 1e-9)
  assert.equal(averageConfidence([]), 0)
})
