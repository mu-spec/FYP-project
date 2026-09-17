/**
 * Milestone 8E.4 — unified Jobs filter contract (pure logic, no DOM).
 *
 * The Jobs page renders its dropdowns from src/filters.js and maps filter
 * state to API params through buildJobsQuery, so these tests pin the exact
 * wire contract: canonical slugs only, empty/Any values omitted, AND-ready.
 * Slugs must stay in lockstep with backend/job_sources/classify.py.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SOURCE_LABELS, CATEGORY_OPTIONS, WORK_MODE_OPTIONS, JOB_TYPE_OPTIONS,
  DEFAULT_FILTERS, buildJobsQuery, activeFilterChips, hasActiveFilters,
} from '../src/filters.js'

test('default filters are all-empty and produce an empty query', () => {
  assert.deepEqual(DEFAULT_FILTERS, {
    q: '', location: '', category: '', workMode: '', jobType: '', source: '',
  })
  assert.deepEqual(buildJobsQuery(DEFAULT_FILTERS), {})
  assert.equal(hasActiveFilters(DEFAULT_FILTERS), false)
  assert.deepEqual(activeFilterChips(DEFAULT_FILTERS), [])
})

test('option lists match the milestone-approved values', () => {
  assert.deepEqual(CATEGORY_OPTIONS.map((o) => o.value), [
    'frontend', 'backend', 'full_stack', 'mobile', 'ai_ml', 'data_science',
    'cyber_security', 'devops_cloud', 'ui_ux', 'graphic_design', 'marketing',
    'sales', 'finance_accounting', 'customer_support', 'human_resources', 'other',
  ])
  assert.deepEqual(WORK_MODE_OPTIONS.map((o) => o.value),
    ['remote', 'onsite', 'hybrid'])
  assert.deepEqual(JOB_TYPE_OPTIONS.map((o) => o.value), [
    'full_time', 'part_time', 'contract', 'freelance', 'internship',
    'temporary', 'other',
  ])
  // every option carries a human label (states are never color-only)
  for (const list of [CATEGORY_OPTIONS, WORK_MODE_OPTIONS, JOB_TYPE_OPTIONS]) {
    for (const opt of list) assert.equal(typeof opt.label, 'string')
  }
})

test('buildJobsQuery maps state to canonical backend params', () => {
  const query = buildJobsQuery({
    q: '  react  ', location: ' Lahore ', category: 'frontend',
    workMode: 'remote', jobType: 'full_time', source: 'adzuna',
  })
  assert.deepEqual(query, {
    q: 'react', location: 'Lahore', category: 'frontend',
    work_mode: 'remote', job_type: 'full_time', source: 'adzuna',
  })
})

test('empty and Any values are omitted so AND semantics stay clean', () => {
  const query = buildJobsQuery({
    q: '', location: '  ', category: '', workMode: '', jobType: '', source: '',
  })
  assert.deepEqual(query, {})
  // whitespace-only text behaves as empty
  assert.deepEqual(buildJobsQuery({ ...DEFAULT_FILTERS, q: '   ' }), {})
})

test('unselected work mode / job type never send unknown-guessing params', () => {
  const query = buildJobsQuery({ ...DEFAULT_FILTERS, category: 'backend' })
  assert.deepEqual(query, { category: 'backend' })
  assert.ok(!('work_mode' in query))
  assert.ok(!('job_type' in query))
})

test('chips reflect each active filter with its display label', () => {
  const chips = activeFilterChips({
    q: 'flask', location: 'Berlin', category: 'backend',
    workMode: 'remote', jobType: 'full_time', source: 'adzuna',
  })
  assert.deepEqual(chips, [
    { key: 'q', label: '“flask”' },
    { key: 'location', label: 'Berlin' },
    { key: 'category', label: 'Backend Development' },
    { key: 'workMode', label: 'Remote' },
    { key: 'jobType', label: 'Full Time' },
    { key: 'source', label: 'Adzuna' },
  ])
  assert.equal(hasActiveFilters({
    ...DEFAULT_FILTERS, workMode: 'hybrid',
  }), true)
})

test('source labels cover all six providers', () => {
  assert.deepEqual(Object.keys(SOURCE_LABELS).sort(),
    ['adzuna', 'arbeitnow', 'jobguard', 'jobicy', 'remoteok', 'upwork'])
})
