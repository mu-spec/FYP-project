/**
 * Milestone 8C.1 + 8C.2 — Post a Job screen.
 *
 * 8C.1: employer registration (Become an Employer → profile summary/edit).
 * 8C.2: registered employers additionally create and manage their own JOB
 * DRAFTS (Create Job Post / My Job Posts / View / Edit / Delete). Every job
 * created here has status='draft' — the backend decides the status and the
 * UI offers NO publish action. Drafts are private to the owning employer:
 * they never appear in the Jobs feed, alerts or notifications (that
 * integration happens after AI screening in 8C.3).
 */

import { useEffect, useState } from 'react'
import {
  getEmployerProfile, createEmployerProfile, updateEmployerProfile,
  getEmployerJobs, createEmployerJob, updateEmployerJob, deleteEmployerJob,
} from '../api.js'
import Icon from './Icon.jsx'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const JOB_TYPES = ['Full Time', 'Part Time', 'Contract', 'Internship', 'Temporary', 'Other']

const EMPTY_FORM = {
  company_name: '', contact_name: '', business_email: '',
  website: '', location: '', company_description: '',
}

const EMPTY_JOB = {
  title: '', location: '', job_type: '', salary: '',
  description: '', requirements: '', benefits: '',
  contact_email: '', application_url: '', closing_date: '',
}

function formatDate(iso) {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function validateProfileDraft(draft) {
  const errors = {}
  if (!draft.company_name.trim()) errors.company_name = 'Please enter the company name.'
  if (!draft.contact_name.trim()) errors.contact_name = "Please enter the contact person's name."
  if (!draft.business_email.trim()) errors.business_email = 'Please enter a business email.'
  else if (!EMAIL_RE.test(draft.business_email.trim())) errors.business_email = 'Please enter a valid business email address.'
  if (draft.website.trim()) {
    const candidate = draft.website.trim().includes('://')
      ? draft.website.trim()
      : `https://${draft.website.trim()}`
    try {
      const parsed = new URL(candidate)
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        errors.website = 'Website must be a valid HTTP or HTTPS URL.'
      }
    } catch {
      errors.website = 'Website must be a valid HTTP or HTTPS URL.'
    }
  }
  if (!draft.location.trim()) errors.location = 'Please enter the company location.'
  if (!draft.company_description.trim()) errors.company_description = 'Please enter a company description.'
  return errors
}

function validateJobDraft(draft) {
  const errors = {}
  if (!draft.title.trim()) errors.title = 'Please enter the job title.'
  if (!draft.location.trim()) errors.location = 'Please enter the job location.'
  if (!draft.job_type) errors.job_type = 'Please choose a job type.'
  if (draft.salary.trim() && draft.salary.trim().length > 120) errors.salary = 'Salary is too long (max 120 characters).'
  if (!draft.description.trim()) errors.description = 'Please enter a job description.'
  else if (draft.description.trim().length < 30) errors.description = 'Please describe the role in at least 30 characters — the description is what JobGuard will analyze later.'
  if (!draft.requirements.trim()) errors.requirements = 'Please enter the job requirements.'
  if (!draft.contact_email.trim()) errors.contact_email = 'Please enter a contact email.'
  else if (!EMAIL_RE.test(draft.contact_email.trim())) errors.contact_email = 'Please enter a valid contact email address.'
  if (draft.application_url.trim()) {
    const candidate = draft.application_url.trim().includes('://')
      ? draft.application_url.trim()
      : `https://${draft.application_url.trim()}`
    try {
      const parsed = new URL(candidate)
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        errors.application_url = 'Application URL must be a valid HTTP or HTTPS URL.'
      }
    } catch {
      errors.application_url = 'Application URL must be a valid HTTP or HTTPS URL.'
    }
  }
  if (draft.closing_date && !/^\d{4}-\d{2}-\d{2}$/.test(draft.closing_date)) {
    errors.closing_date = 'Closing date must use the YYYY-MM-DD format.'
  }
  return errors
}

/* ------------------------------------------------------------------ */
/* Employer registration form (8C.1, unchanged behavior)               */
/* ------------------------------------------------------------------ */

function EmployerForm({ initial, submitLabel, onSubmit, onCancel, saving, fieldErrors, topError }) {
  const [draft, setDraft] = useState({ ...EMPTY_FORM, ...initial })
  const [localErrors, setLocalErrors] = useState({})
  const errors = { ...localErrors, ...(fieldErrors || {}) }

  const set = (key) => (event) => {
    setDraft((d) => ({ ...d, [key]: event.target.value }))
    setLocalErrors((e) => ({ ...e, [key]: undefined }))
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    const found = validateProfileDraft(draft)
    setLocalErrors(found)
    if (Object.keys(found).length > 0) return
    onSubmit({
      company_name: draft.company_name.trim(),
      contact_name: draft.contact_name.trim(),
      business_email: draft.business_email.trim(),
      website: draft.website.trim(),
      location: draft.location.trim(),
      company_description: draft.company_description.trim(),
    })
  }

  const field = (key, label, input) => (
    <div className="jobs-field">
      <label htmlFor={`emp-${key}`}>{label}</label>
      {input}
      {errors[key] && <p className="emp-field-error" role="alert">{errors[key]}</p>}
    </div>
  )

  return (
    <form className="postjob-form card-surface" onSubmit={handleSubmit} noValidate>
      <div className="postjob-form-grid">
        {field('company_name', 'Company Name *', (
          <input id="emp-company_name" type="text" maxLength={120} placeholder="e.g. Acme Labs"
            value={draft.company_name} onChange={set('company_name')} aria-invalid={!!errors.company_name} />
        ))}
        {field('contact_name', 'Contact Person Name *', (
          <input id="emp-contact_name" type="text" maxLength={120} placeholder="e.g. Ada Smith"
            value={draft.contact_name} onChange={set('contact_name')} aria-invalid={!!errors.contact_name} />
        ))}
        {field('business_email', 'Business Email *', (
          <input id="emp-business_email" type="email" maxLength={200} placeholder="jobs@yourcompany.example"
            value={draft.business_email} onChange={set('business_email')} aria-invalid={!!errors.business_email} />
        ))}
        {field('website', 'Company Website (optional)', (
          <input id="emp-website" type="url" maxLength={300} placeholder="https://yourcompany.example"
            value={draft.website} onChange={set('website')} aria-invalid={!!errors.website} />
        ))}
        {field('location', 'Location *', (
          <input id="emp-location" type="text" maxLength={120} placeholder="e.g. Lahore"
            value={draft.location} onChange={set('location')} aria-invalid={!!errors.location} />
        ))}
        <div className="postjob-desc-field">
          {field('company_description', 'Company Description *', (
            <textarea id="emp-company_description" rows={5} maxLength={2000}
              placeholder="What your company does, roles you plan to publish…"
              value={draft.company_description} onChange={set('company_description')}
              aria-invalid={!!errors.company_description} />
          ))}
        </div>
      </div>
      {topError && <p className="prefs-error" role="alert">{topError}</p>}
      <p className="postjob-note">
        Registration only — registering your profile does not create or publish
        a job, and it is not a third-party verification of your company.
      </p>
      <div className="modal-actions postjob-actions">
        <button type="button" className="modal-cancel" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

/* ------------------------------------------------------------------ */
/* Job draft form (8C.2) — Save Draft / Cancel only; never publish     */
/* ------------------------------------------------------------------ */

function JobForm({ initial, onSubmit, onCancel, saving, fieldErrors, topError }) {
  const isEdit = !!initial.id
  const [draft, setDraft] = useState({ ...EMPTY_JOB, ...initial })
  const [localErrors, setLocalErrors] = useState({})
  const errors = { ...localErrors, ...(fieldErrors || {}) }

  const set = (key) => (event) => {
    setDraft((d) => ({ ...d, [key]: event.target.value }))
    setLocalErrors((e) => ({ ...e, [key]: undefined }))
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    const found = validateJobDraft(draft)
    setLocalErrors(found)
    if (Object.keys(found).length > 0) return
    // NOTE: no status is ever sent — the backend always stores a draft.
    onSubmit({
      title: draft.title.trim(),
      location: draft.location.trim(),
      job_type: draft.job_type,
      salary: draft.salary.trim(),
      description: draft.description.trim(),
      requirements: draft.requirements.trim(),
      benefits: draft.benefits.trim(),
      contact_email: draft.contact_email.trim(),
      application_url: draft.application_url.trim(),
      closing_date: draft.closing_date,
    })
  }

  const field = (key, label, input, wide = false) => (
    <div className={wide ? 'postjob-desc-field' : 'jobs-field'}>
      <label htmlFor={`job-${key}`}>{label}</label>
      {input}
      {errors[key] && <p className="emp-field-error" role="alert">{errors[key]}</p>}
    </div>
  )

  return (
    <form className="postjob-form card-surface" onSubmit={handleSubmit} noValidate
      aria-label={isEdit ? 'Edit job draft' : 'Create job draft'}>
      <div className="modal-head">
        <h2>{isEdit ? 'Edit Job Draft' : 'Create Job Post'}</h2>
      </div>
      <p className="modal-sub">
        Saved as a private draft — nothing is published yet. Drafts are only
        visible to you.
      </p>
      <div className="postjob-form-grid">
        {field('title', 'Job Title *', (
          <input id="job-title" type="text" maxLength={120} placeholder="e.g. Backend Engineer"
            value={draft.title} onChange={set('title')} aria-invalid={!!errors.title} />
        ))}
        {field('location', 'Location *', (
          <input id="job-location" type="text" maxLength={120} placeholder="e.g. Lahore"
            value={draft.location} onChange={set('location')} aria-invalid={!!errors.location} />
        ))}
        {field('job_type', 'Job Type *', (
          <select id="job-job_type" value={draft.job_type} onChange={set('job_type')} aria-invalid={!!errors.job_type}>
            <option value="">Choose a job type…</option>
            {JOB_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        ))}
        {field('salary', 'Salary / Compensation (optional)', (
          <input id="job-salary" type="text" maxLength={120} placeholder="e.g. 180k PKR / month"
            value={draft.salary} onChange={set('salary')} aria-invalid={!!errors.salary} />
        ))}
        {field('description', 'Job Description *', (
          <textarea id="job-description" rows={6} maxLength={20000}
            placeholder="What the role involves — this is what JobGuard will analyze later…"
            value={draft.description} onChange={set('description')} aria-invalid={!!errors.description} />
        ), true)}
        {field('requirements', 'Requirements *', (
          <textarea id="job-requirements" rows={4} maxLength={8000}
            placeholder="Skills, experience, education…"
            value={draft.requirements} onChange={set('requirements')} aria-invalid={!!errors.requirements} />
        ), true)}
        {field('benefits', 'Benefits (optional)', (
          <textarea id="job-benefits" rows={3} maxLength={4000}
            placeholder="Health cover, hybrid work, bonus…"
            value={draft.benefits} onChange={set('benefits')} aria-invalid={!!errors.benefits} />
        ), true)}
        {field('contact_email', 'Contact Email *', (
          <input id="job-contact_email" type="email" maxLength={200} placeholder="jobs@yourcompany.example"
            value={draft.contact_email} onChange={set('contact_email')} aria-invalid={!!errors.contact_email} />
        ))}
        {field('application_url', 'Application URL (optional)', (
          <input id="job-application_url" type="url" maxLength={500} placeholder="https://yourcompany.example/apply"
            value={draft.application_url} onChange={set('application_url')} aria-invalid={!!errors.application_url} />
        ))}
        {field('closing_date', 'Closing Date (optional)', (
          <input id="job-closing_date" type="date"
            value={draft.closing_date} onChange={set('closing_date')} aria-invalid={!!errors.closing_date} />
        ))}
      </div>
      {topError && <p className="prefs-error" role="alert">{topError}</p>}
      <p className="postjob-note">Draft only — publishing will be enabled after JobGuard AI screening in a later stage.</p>
      <div className="modal-actions postjob-actions">
        <button type="button" className="modal-cancel" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? 'Saving…' : 'Save Draft'}
        </button>
      </div>
    </form>
  )
}

/* ------------------------------------------------------------------ */
/* Main screen                                                         */
/* ------------------------------------------------------------------ */

export default function PostJob({ backendUp }) {
  const [profile, setProfile] = useState(null)
  const [jobs, setJobs] = useState(null) // null = not loaded
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState('view') // view | register | edit
  const [fieldErrors, setFieldErrors] = useState({})
  const [topError, setTopError] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)
  // 8C.2 draft management
  const [jobFormOpen, setJobFormOpen] = useState(false)
  const [editingJob, setEditingJob] = useState(null)
  const [jobFieldErrors, setJobFieldErrors] = useState({})
  const [jobTopError, setJobTopError] = useState('')
  const [jobFlash, setJobFlash] = useState('')
  const [detailJob, setDetailJob] = useState(null)
  const [deletingJob, setDeletingJob] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      getEmployerProfile().catch(() => ({ profile: null })),
      getEmployerJobs().catch(() => ({ jobs: [] })),
    ]).then(([p, j]) => {
      if (!active) return
      setProfile(p.profile)
      setJobs(j.jobs || [])
      setLoading(false)
    })
    return () => { active = false }
  }, [])

  const refreshJobs = async () => {
    try {
      const res = await getEmployerJobs()
      setJobs(res.jobs || [])
    } catch {/* keep the previous list */}
  }

  const submitProfile = async (payload) => {
    setSaving(true)
    setTopError('')
    setFieldErrors({})
    try {
      const res = mode === 'edit'
        ? await updateEmployerProfile(payload)
        : await createEmployerProfile(payload)
      setProfile(res.profile)
      setMode('view')
      setSavedFlash(true)
    } catch (err) {
      if (err.fieldErrors) {
        setFieldErrors(err.fieldErrors)
        setTopError(err.message || 'Please fix the highlighted fields.')
      } else {
        setTopError(err.message || 'Could not save your employer profile. Please try again.')
      }
    } finally {
      setSaving(false)
    }
  }

  const startEdit = () => {
    setTopError('')
    setFieldErrors({})
    setSavedFlash(false)
    setMode('edit')
  }

  const openJobForm = (job = null) => {
    setEditingJob(job)
    setJobFieldErrors({})
    setJobTopError('')
    setJobFlash('')
    setJobFormOpen(true)
  }

  const submitJob = async (payload) => {
    setSaving(true)
    setJobTopError('')
    setJobFieldErrors({})
    try {
      const res = editingJob
        ? await updateEmployerJob(editingJob.id, payload)
        : await createEmployerJob(payload)
      const saved = res.job
      if (saved.status !== 'draft') throw new Error('Unexpected job status.') // defensive; backend always drafts
      await refreshJobs()
      setJobFormOpen(false)
      setEditingJob(null)
      setDetailJob(null)
      setJobFlash(saved.id ? 'Job draft saved successfully.' : '')
    } catch (err) {
      if (err.fieldErrors) {
        setJobFieldErrors(err.fieldErrors)
        setJobTopError(err.message || 'Please fix the highlighted fields.')
      } else {
        setJobTopError(err.message || 'Could not save the job draft. Please try again.')
      }
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deletingJob) return
    setSaving(true)
    try {
      await deleteEmployerJob(deletingJob.id)
      setDeletingJob(null)
      if (detailJob && detailJob.id) setDetailJob(null)
      await refreshJobs()
      setJobFlash('')
    } catch {
      setDeletingJob(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="page-shell postjob-page">
      <section className="page-intro">
        <p className="eyebrow"><span className="eyebrow-line" /> EMPLOYER WORKSPACE</p>
        <h1>Post a Job</h1>
        <p className="page-subtitle">Register your employer profile to get ready for job publishing.</p>
      </section>

      {loading && (
        <section className="jobs-state card-surface" role="status" aria-live="polite">
          <p>Loading employer workspace…</p>
        </section>
      )}

      {!loading && !profile && mode !== 'register' && (
        <section className="postjob-hero card-surface">
          <span className="brand-mark" aria-hidden="true"><Icon name="shield" size={22} strokeWidth={2} /></span>
          <h2>Become an Employer</h2>
          <p className="postjob-hero-copy">
            Register your employer profile before publishing jobs on JobGuard.
          </p>
          <button
            type="button"
            className="btn-primary postjob-cta"
            disabled={backendUp === false}
            onClick={() => { setMode('register'); setSavedFlash(false) }}
          >
            Register as Employer
          </button>
        </section>
      )}

      {!loading && mode === 'register' && (
        <EmployerForm
          initial={EMPTY_FORM}
          submitLabel="Save Employer Profile"
          onSubmit={submitProfile}
          onCancel={() => setMode('view')}
          saving={saving}
          fieldErrors={fieldErrors}
          topError={topError}
        />
      )}

      {!loading && profile && mode === 'view' && (
        <section className="postjob-summary card-surface">
          <div className="postjob-summary-head">
            <span className="postjob-ready-badge">
              <Icon name="check" size={14} strokeWidth={2.5} /> Employer profile ready
            </span>
            <div className="postjob-head-actions">
              <button type="button" className="jobs-prefs-btn" onClick={startEdit}>
                <Icon name="file" size={15} strokeWidth={2} /> Edit Employer Profile
              </button>
              <button
                type="button"
                className="btn-primary postjob-create-btn"
                disabled={backendUp === false}
                onClick={() => openJobForm(null)}
              >
                Create Job Post
              </button>
            </div>
          </div>
          <dl className="postjob-summary-grid">
            <div><dt>Company Name</dt><dd>{profile.company_name}</dd></div>
            <div><dt>Contact Person</dt><dd>{profile.contact_name}</dd></div>
            <div><dt>Business Email</dt><dd>{profile.business_email}</dd></div>
            <div><dt>Location</dt><dd>{profile.location}</dd></div>
          </dl>
          {profile.company_description && (
            <p className="postjob-summary-desc">{profile.company_description}</p>
          )}
          {savedFlash && (
            <p className="postjob-flash" role="status">Employer profile saved.</p>
          )}
          <p className="postjob-next">
            Job publishing will be enabled in the next stage.
          </p>
        </section>
      )}

      {!loading && profile && mode === 'edit' && (
        <EmployerForm
          initial={{
            company_name: profile.company_name,
            contact_name: profile.contact_name,
            business_email: profile.business_email,
            website: profile.website || '',
            location: profile.location,
            company_description: profile.company_description || '',
          }}
          submitLabel="Save Changes"
          onSubmit={submitProfile}
          onCancel={() => { setMode('view'); setFieldErrors({}); setTopError('') }}
          saving={saving}
          fieldErrors={fieldErrors}
          topError={topError}
        />
      )}

      {/* 8C.2 — My Job Posts */}
      {!loading && profile && mode === 'view' && (
        <section className="postjob-myjobs" aria-label="My Job Posts">
          <div className="postjob-myjobs-head">
            <h2>My Job Posts</h2>
            {jobFlash && <p className="postjob-flash" role="status">{jobFlash}</p>}
          </div>

          {jobs && jobs.length === 0 && (
            <div className="postjob-empty card-surface">
              <p>You haven&apos;t created any job posts yet.</p>
            </div>
          )}

          {jobs && jobs.length > 0 && (
            <div className="postjob-jobs-list">
              {jobs.map((job) => (
                <article key={job.id} className="job-draft-card card-surface">
                  <div className="job-draft-main">
                    <div className="job-draft-title-row">
                      <h3 className="job-draft-title">{job.title}</h3>
                      <span className="draft-badge">
                        <Icon name="file" size={12} strokeWidth={2} /> Draft
                      </span>
                    </div>
                    <ul className="job-meta">
                      <li>📍 {job.location}</li>
                      <li>🕒 {job.job_type}</li>
                      <li>Updated {formatDate(job.updated_at) || 'recently'}</li>
                    </ul>
                  </div>
                  <div className="job-draft-actions">
                    <button type="button" className="notif-action" onClick={() => setDetailJob(job)}>View</button>
                    <button type="button" className="notif-action" onClick={() => openJobForm(job)}>Edit</button>
                    <button type="button" className="notif-action job-draft-delete" onClick={() => setDeletingJob(job)}>Delete</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Create / Edit job draft (modal) */}
      {jobFormOpen && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !saving) setJobFormOpen(false)
          }}
        >
          <JobForm
            initial={editingJob
              ? {
                id: editingJob.id,
                title: editingJob.title,
                location: editingJob.location,
                job_type: editingJob.job_type,
                salary: editingJob.salary || '',
                description: editingJob.description,
                requirements: editingJob.requirements,
                benefits: editingJob.benefits || '',
                contact_email: editingJob.contact_email,
                application_url: editingJob.application_url || '',
                closing_date: editingJob.closing_date || '',
              }
              : EMPTY_JOB}
            onSubmit={submitJob}
            onCancel={() => { setJobFormOpen(false); setEditingJob(null); setJobFieldErrors({}); setJobTopError('') }}
            saving={saving}
            fieldErrors={jobFieldErrors}
            topError={jobTopError}
          />
        </div>
      )}

      {/* Draft detail (read-only) */}
      {detailJob && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setDetailJob(null)
          }}
        >
          <div className="modal-card card-surface job-detail" role="dialog" aria-modal="true" aria-label="Job draft details">
            <div className="modal-head">
              <span className="draft-badge">
                <Icon name="file" size={12} strokeWidth={2} /> Status: Draft
              </span>
              <button type="button" className="modal-close" aria-label="Close job details" onClick={() => setDetailJob(null)}>
                <Icon name="close" size={16} strokeWidth={2} />
              </button>
            </div>
            {profile && <p className="job-company">{profile.company_name}</p>}
            <h2 className="job-title">{detailJob.title}</h2>
            <ul className="job-meta">
              <li>📍 {detailJob.location}</li>
              <li>🕒 {detailJob.job_type}</li>
              {detailJob.salary && <li>💰 {detailJob.salary}</li>}
              {detailJob.closing_date && <li>📅 Closes {detailJob.closing_date}</li>}
            </ul>
            <div className="job-detail-section">
              <h3>Description</h3>
              <p className="job-detail-text">{detailJob.description}</p>
            </div>
            <div className="job-detail-section">
              <h3>Requirements</h3>
              <p className="job-detail-text">{detailJob.requirements}</p>
            </div>
            {detailJob.benefits && (
              <div className="job-detail-section">
                <h3>Benefits</h3>
                <p className="job-detail-text">{detailJob.benefits}</p>
              </div>
            )}
            <dl className="postjob-summary-grid">
              <div><dt>Contact</dt><dd>{detailJob.contact_email}</dd></div>
              {detailJob.application_url && (
                <div>
                  <dt>Application URL</dt>
                  <dd>
                    <a href={detailJob.application_url} target="_blank" rel="noopener noreferrer" className="job-link">
                      {detailJob.application_url}
                    </a>
                  </dd>
                </div>
              )}
            </dl>
            <div className="modal-actions job-actions">
              <button
                type="button"
                className="jobs-prefs-btn"
                onClick={() => { const j = detailJob; setDetailJob(null); openJobForm(j) }}
              >
                <Icon name="file" size={15} strokeWidth={2} /> Edit Draft
              </button>
              <button type="button" className="modal-cancel" onClick={() => setDetailJob(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deletingJob && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !saving) setDeletingJob(null)
          }}
        >
          <div className="modal-card card-surface postjob-delete-dialog" role="alertdialog" aria-modal="true" aria-label="Delete job draft">
            <h2>Delete this job draft?</h2>
            <p className="modal-sub">
              &ldquo;{deletingJob.title}&rdquo; will be removed. This action cannot be undone.
            </p>
            <div className="modal-actions">
              <button type="button" className="modal-cancel" onClick={() => setDeletingJob(null)} disabled={saving}>
                Cancel
              </button>
              <button type="button" className="postjob-delete-btn" onClick={confirmDelete} disabled={saving}>
                {saving ? 'Deleting…' : 'Delete Draft'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
