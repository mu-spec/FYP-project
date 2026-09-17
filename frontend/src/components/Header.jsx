import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import NotificationBell from './NotificationBell.jsx'

const NAV_ITEMS = [
  { id: 'home', label: 'Home' },
  { id: 'analyze', label: 'Analyze' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'history', label: 'History' },
  { id: 'insights', label: 'Insights' },
  { id: 'about', label: 'About' },
]

export default function Header({ page, onNavigate, backendUp, health, user, onSignOut, onViewJob, onOpenPreferences }) {
  const statusLabel = backendUp === null
    ? 'Checking service'
    : backendUp
      ? health?.model_loaded ? 'Model ready' : 'API online'
      : 'API offline'

  // Milestone 8A.1 — compact user control (no profile page yet): a small
  // dropdown with the name, the email and Sign Out. Closes on outside click
  // or Escape so keyboard users are never trapped.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return undefined
    const onPointerDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  const initial = (user?.name || '?').trim().charAt(0).toUpperCase()

  return (
    <header className="site-header">
      <div className="container header-inner">
        <button className="brand" type="button" onClick={() => onNavigate('home')} aria-label="Go to home">
          <span className="brand-mark"><Icon name="shield" size={21} strokeWidth={2} /></span>
          <span className="brand-copy">
            <strong>JobGuard</strong>
            <span>AI job screening</span>
          </span>
        </button>

        <nav className="main-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-link ${page === item.id ? 'active' : ''}`}
              onClick={() => onNavigate(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className={`service-status ${backendUp === null ? 'checking' : backendUp ? 'online' : 'offline'}`}>
          <span className="status-dot" />
          <span>{statusLabel}</span>
        </div>

        {user && (
          <NotificationBell
            user={user}
            backendUp={backendUp}
            onViewJob={onViewJob}
            onOpenPreferences={onOpenPreferences}
          />
        )}

        {user && (
          <div className="user-menu" ref={menuRef}>
            <button
              type="button"
              className="user-menu-btn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="user-avatar" aria-hidden="true">{initial}</span>
              <span className="user-menu-name">{user.name}</span>
              <span className="user-caret" aria-hidden="true">▾</span>
            </button>
            {menuOpen && (
              <div className="user-dropdown" role="menu" aria-label="Account">
                <div className="user-dropdown-name">{user.name}</div>
                <div className="user-dropdown-email">{user.email}</div>
                <button
                  type="button"
                  role="menuitem"
                  className="user-signout"
                  onClick={() => {
                    setMenuOpen(false)
                    onSignOut?.()
                  }}
                >
                  Sign Out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
