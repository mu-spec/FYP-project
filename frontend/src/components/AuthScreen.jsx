/**
 * Milestone 8A.1 — Sign In / Create Account screen.
 *
 * Shown INSTEAD of the whole JobGuard application while nobody is signed in.
 * Styled with the approved Espresso + Burnt Orange identity (no layout or
 * design changes anywhere else). Every new account is a normal JobGuard user.
 */

import { useState } from 'react'
import { useAuth } from '../AuthContext.jsx'
import Icon from './Icon.jsx'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function validatePassword(pw) {
  const problems = []
  if (pw.length < 8) problems.push('At least 8 characters')
  if (!/[A-Z]/.test(pw)) problems.push('One uppercase letter')
  if (!/[a-z]/.test(pw)) problems.push('One lowercase letter')
  if (!/[0-9]/.test(pw)) problems.push('One number')
  return problems
}

export default function AuthScreen() {
  const { signIn, signUp } = useAuth()
  const [mode, setMode] = useState('signin') // 'signin' | 'signup'
  const [fields, setFields] = useState({ name: '', email: '', password: '', confirm: '' })
  const [fieldErrors, setFieldErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setFields((f) => ({ ...f, [key]: e.target.value }))

  function switchMode(next) {
    setMode(next)
    setFieldErrors({})
    setFormError('')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (busy) return
    setFormError('')

    const errors = {}
    const email = fields.email.trim().toLowerCase()
    if (mode === 'signup') {
      if (!fields.name.trim()) errors.name = 'Please enter your full name.'
      if (!EMAIL_RE.test(email)) errors.email = 'Please enter a valid email address.'
      const pwProblems = validatePassword(fields.password)
      if (pwProblems.length) errors.password = `Password needs: ${pwProblems.join(', ')}.`
      if (fields.confirm !== fields.password) errors.confirm = 'Passwords do not match.'
    } else {
      if (!EMAIL_RE.test(email)) errors.email = 'Please enter a valid email address.'
      if (!fields.password) errors.password = 'Please enter your password.'
    }
    setFieldErrors(errors)
    if (Object.keys(errors).length) return

    setBusy(true)
    try {
      if (mode === 'signup') {
        await signUp(fields.name.trim(), email, fields.password, fields.confirm)
      } else {
        await signIn(email, fields.password)
      }
      window.location.hash = '#home' // authenticated → JobGuard Home
    } catch (err) {
      if (err.fieldErrors && Object.keys(err.fieldErrors).length) {
        setFieldErrors(err.fieldErrors)
      } else {
        setFormError(err.message || 'Something went wrong. Please try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="shield" size={21} strokeWidth={2} />
          </span>
          <div className="brand-copy">
            <strong>JobGuard</strong>
            <span>AI job screening</span>
          </div>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="Authentication">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signin'}
            className={`auth-tab ${mode === 'signin' ? 'active' : ''}`}
            onClick={() => switchMode('signin')}
          >
            Sign In
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signup'}
            className={`auth-tab ${mode === 'signup' ? 'active' : ''}`}
            onClick={() => switchMode('signup')}
          >
            Create Account
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit} noValidate>
          {mode === 'signup' && (
            <div className="auth-field">
              <label htmlFor="auth-name">Full Name</label>
              <input
                id="auth-name"
                type="text"
                autoComplete="name"
                placeholder="Your full name"
                value={fields.name}
                onChange={set('name')}
                aria-invalid={!!fieldErrors.name}
              />
              {fieldErrors.name && <p className="auth-field-error" aria-live="polite">{fieldErrors.name}</p>}
            </div>
          )}

          <div className="auth-field">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={fields.email}
              onChange={set('email')}
              aria-invalid={!!fieldErrors.email}
            />
            {fieldErrors.email && <p className="auth-field-error" aria-live="polite">{fieldErrors.email}</p>}
          </div>

          <div className="auth-field">
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              placeholder={mode === 'signup' ? 'Create a password' : 'Your password'}
              value={fields.password}
              onChange={set('password')}
              aria-invalid={!!fieldErrors.password}
            />
            {fieldErrors.password && <p className="auth-field-error" aria-live="polite">{fieldErrors.password}</p>}
            {mode === 'signup' && !fieldErrors.password && (
              <p className="auth-hint">Minimum 8 characters with an uppercase letter, a lowercase letter and a number.</p>
            )}
          </div>

          {mode === 'signup' && (
            <div className="auth-field">
              <label htmlFor="auth-confirm">Confirm Password</label>
              <input
                id="auth-confirm"
                type="password"
                autoComplete="new-password"
                placeholder="Repeat the password"
                value={fields.confirm}
                onChange={set('confirm')}
                aria-invalid={!!fieldErrors.confirm}
              />
              {fieldErrors.confirm && <p className="auth-field-error" aria-live="polite">{fieldErrors.confirm}</p>}
            </div>
          )}

          {formError && <p className="auth-form-error" aria-live="assertive">{formError}</p>}

          <button type="submit" className="btn-primary auth-submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'signup' ? 'Sign Up' : 'Sign In'}
          </button>
        </form>

        <p className="auth-footnote">
          {mode === 'signin'
            ? 'New to JobGuard? Switch to Create Account — it takes seconds.'
            : 'Every new account is a standard JobGuard user. Your analyses stay private to your session.'}
        </p>
      </div>
    </div>
  )
}
