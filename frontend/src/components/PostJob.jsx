/**
 * Milestone 8C.1 — Post a Job screen (employer registration foundation).
 *
 * A JobGuard account chooses "Post a Job"; without an employer profile the
 * screen offers "Become an Employer" registration, with a profile it shows a
 * clean summary and in-place editing. REGISTRATION ONLY: no job is created
 * or published in this milestone, and nothing here claims third-party
 * verification of a company. The profile belongs strictly to the signed-in
 * user (backend enforces ownership by session user_id).
 */

import { useEffect, useState } from 'react'
import { getEmployerProfile, createEmployerProfile, updateEmployerProfile } from '../api.js'
import Icon from './Icon.jsx'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const EMPTY_FORM = {
  company_name: '', contact_name: '', business_email: '',
  website: '', location: '', company_description: '',
}

function validateDraft(draft) {
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
    const found = validateDraft(draft)
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
          <input
            id="emp-company_name"
            type="text"
            maxLength={120}
            placeholder="e.g. Acme Labs"
            value={draft.company_name}
            onChange={set('company_name')}
            aria-invalid={!!errors.company_name}
          />
        ))}
        {field('contact_name', 'Contact Person Name *', (
          <input
            id="emp-contact_name"
            type="text"
            maxLength={120}
            placeholder="e.g. Ada Smith"
            value={draft.contact_name}
            onChange={set('contact_name')}
            aria-invalid={!!errors.contact_name}
          />
        ))}
        {field('business_email', 'Business Email *', (
          <input
            id="emp-business_email"
            type="email"
            maxLength={200}
            placeholder="jobs@yourcompany.example"
            value={draft.business_email}
            onChange={set('business_email')}
            aria-invalid={!!errors.business_email}
          />
        ))}
        {field('website', 'Company Website (optional)', (
          <input
            id="emp-website"
            type="url"
            maxLength={300}
            placeholder="https://yourcompany.example"
            value={draft.website}
            onChange={set('website')}
            aria-invalid={!!errors.website}
          />
        ))}
        {field('location', 'Location *', (
          <input
            id="emp-location"
            type="text"
            maxLength={120}
            placeholder="e.g. Lahore"
            value={draft.location}
            onChange={set('location')}
            aria-invalid={!!errors.location}
          />
        ))}
        <div className="postjob-desc-field">
          {field('company_description', 'Company Description *', (
            <textarea
              id="emp-company_description"
              rows={5}
              maxLength={2000}
              placeholder="What your company does, roles you plan to publish…"
              value={draft.company_description}
              onChange={set('company_description')}
              aria-invalid={!!errors.company_description}
            />
          ))}
        </div>
      </div>
      {topError && <p className="prefs-error" role="alert">{topError}</p>}
      <p className="postjob-note">
        Registration only — registering your profile does not create or publish
        a job, and it is not a third-party verification of your company.
      </p>
      <div className="modal-actions postjob-actions">
        <button type="button" className="modal-cancel" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

export default function PostJob({ backendUp }) {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState('view') // view | register | edit
  const [fieldErrors, setFieldErrors] = useState({})
  const [topError, setTopError] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    let active = true
    getEmployerProfile()
      .then((res) => {
        if (!active) return
        setProfile(res.profile)
        setLoading(false)
      })
      .catch(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  const submit = async (payload) => {
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

  return (
    <main className="page-shell postjob-page">
      <section className="page-intro">
        <p className="eyebrow"><span className="eyebrow-line" /> EMPLOYER WORKSPACE</p>
        <h1>Post a Job</h1>
        <p className="page-subtitle">Register your employer profile to get ready for job publishing.</p>
      </section>

      {loading && (
        <section className="jobs-state card-surface" role="status" aria-live="polite">
          <p>Loading employer profile…</p>
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
          onSubmit={submit}
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
            <button type="button" className="jobs-prefs-btn" onClick={startEdit}>
              <Icon name="file" size={15} strokeWidth={2} /> Edit Employer Profile
            </button>
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
          onSubmit={submit}
          onCancel={() => { setMode('view'); setFieldErrors({}); setTopError('') }}
          saving={saving}
          fieldErrors={fieldErrors}
          topError={topError}
        />
      )}
    </main>
  )
}
