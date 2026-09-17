/**
 * Milestone 8E.4 — unified Jobs filter definitions + query mapping.
 *
 * Pure data and pure functions (no React, no DOM) so `node --test` can
 * exercise the filter contract directly. The Jobs page renders the option
 * lists below as compact dropdowns and sends only the backend canonical
 * slugs; empty/“Any” values are omitted from the request entirely, which
 * keeps AND semantics clean (the backend ignores unknown values too).
 */

export const SOURCE_LABELS = {
  remoteok: 'Remote OK',
  arbeitnow: 'Arbeitnow',
  jobicy: 'Jobicy',
  adzuna: 'Adzuna',
  upwork: 'Upwork',
  jobguard: 'JobGuard',
}

// Canonical category slugs — must match backend job_sources/classify.py.
export const CATEGORY_OPTIONS = [
  { value: 'frontend', label: 'Frontend Development' },
  { value: 'backend', label: 'Backend Development' },
  { value: 'full_stack', label: 'Full Stack Development' },
  { value: 'mobile', label: 'Mobile Development' },
  { value: 'ai_ml', label: 'AI / Machine Learning' },
  { value: 'data_science', label: 'Data Science' },
  { value: 'cyber_security', label: 'Cyber Security' },
  { value: 'devops_cloud', label: 'DevOps / Cloud' },
  { value: 'ui_ux', label: 'UI / UX Design' },
  { value: 'graphic_design', label: 'Graphic Design' },
  { value: 'marketing', label: 'Marketing' },
  { value: 'sales', label: 'Sales' },
  { value: 'finance_accounting', label: 'Finance / Accounting' },
  { value: 'customer_support', label: 'Customer Support' },
  { value: 'human_resources', label: 'Human Resources' },
  { value: 'other', label: 'Other' },
]

// Work mode — unknown-mode jobs only ever surface under “Any” (the backend
// keeps their work_mode NULL and never guesses).
export const WORK_MODE_OPTIONS = [
  { value: 'remote', label: 'Remote' },
  { value: 'onsite', label: 'On-site' },
  { value: 'hybrid', label: 'Hybrid' },
]

// Canonical job types — must match backend job_sources/classify.py.
export const JOB_TYPE_OPTIONS = [
  { value: 'full_time', label: 'Full Time' },
  { value: 'part_time', label: 'Part Time' },
  { value: 'contract', label: 'Contract' },
  { value: 'freelance', label: 'Freelance' },
  { value: 'internship', label: 'Internship' },
  { value: 'temporary', label: 'Temporary' },
  { value: 'other', label: 'Other' },
]

export const DEFAULT_FILTERS = {
  q: '',
  location: '',
  category: '',
  workMode: '',
  jobType: '',
  source: '',
}

function labelFor(options, value) {
  return options.find((opt) => opt.value === value)?.label || value
}

/** Active filters -> GET /api/jobs query params (empty/Any values omitted). */
export function buildJobsQuery(filters) {
  const params = {}
  const q = (filters.q || '').trim()
  const location = (filters.location || '').trim()
  if (q) params.q = q
  if (location) params.location = location
  if (filters.category) params.category = filters.category
  if (filters.workMode) params.work_mode = filters.workMode
  if (filters.jobType) params.job_type = filters.jobType
  if (filters.source) params.source = filters.source
  return params
}

/** Compact chips (label + state key) for the currently active filters. */
export function activeFilterChips(filters) {
  const chips = []
  const q = (filters.q || '').trim()
  const location = (filters.location || '').trim()
  if (q) chips.push({ key: 'q', label: `“${q}”` })
  if (location) chips.push({ key: 'location', label: location })
  if (filters.category) {
    chips.push({ key: 'category', label: labelFor(CATEGORY_OPTIONS, filters.category) })
  }
  if (filters.workMode) {
    chips.push({ key: 'workMode', label: labelFor(WORK_MODE_OPTIONS, filters.workMode) })
  }
  if (filters.jobType) {
    chips.push({ key: 'jobType', label: labelFor(JOB_TYPE_OPTIONS, filters.jobType) })
  }
  if (filters.source) {
    chips.push({ key: 'source', label: SOURCE_LABELS[filters.source] || filters.source })
  }
  return chips
}

export function hasActiveFilters(filters) {
  return activeFilterChips(filters).length > 0
}
