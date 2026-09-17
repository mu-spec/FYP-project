/**
 * Milestone 8B.2 — navbar notification bell.
 *
 * Compact bell next to the signed-in user control. Shows the unread count
 * (hidden when zero), opens a scrollable dropdown of in-app job alerts, and
 * never expands the page. All data comes from the authenticated
 * /api/notifications endpoints; strictly the signed-in user's own rows.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getNotifications, getUnreadCount,
  markNotificationRead, markAllNotificationsRead,
} from '../api.js'
import Icon from './Icon.jsx'

function timeAgo(iso) {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return ''
  const seconds = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.floor(hours / 24)
  return `${days} d ago`
}

export default function NotificationBell({ user, backendUp, onViewJob, onOpenPreferences }) {
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [items, setItems] = useState(null) // null = not loaded yet
  const [hasPrefs, setHasPrefs] = useState(true)
  const [busy, setBusy] = useState(false)
  const panelRef = useRef(null)
  const pollRef = useRef(null)

  const refreshCount = useCallback(async () => {
    if (!user || backendUp === false) return
    try {
      const data = await getUnreadCount()
      setUnread(data.unread || 0)
    } catch {
      /* transient — the badge simply keeps its last value */
    }
  }, [user, backendUp])

  const loadList = useCallback(async () => {
    if (!user) return
    setBusy(true)
    try {
      const data = await getNotifications()
      setItems(data.notifications || [])
      setUnread(data.unread || 0)
      setHasPrefs(data.has_preferences !== false)
    } catch {
      setItems([]) // friendly empty panel on transient errors
    } finally {
      setBusy(false)
    }
  }, [user])

  useEffect(() => {
    if (!user) return undefined
    refreshCount()
    pollRef.current = setInterval(refreshCount, 60000)
    // saving preferences on the Jobs page can create alerts immediately
    const onPrefsSaved = () => refreshCount()
    window.addEventListener('jobguard:prefs-saved', onPrefsSaved)
    return () => {
      clearInterval(pollRef.current)
      window.removeEventListener('jobguard:prefs-saved', onPrefsSaved)
    }
  }, [user, refreshCount])

  // Close on outside click / Escape (same pattern as the user menu).
  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next) loadList()
  }

  const markRead = async (notification) => {
    if (notification.is_read) return
    // optimistic: badge drops immediately, panel stays responsive
    setItems((list) => (list || []).map((n) => (
      n.id === notification.id ? { ...n, is_read: true } : n
    )))
    setUnread((u) => Math.max(0, u - 1))
    try {
      const data = await markNotificationRead(notification.id)
      if (typeof data.unread === 'number') setUnread(data.unread)
    } catch {
      refreshCount()
    }
  }

  const markAll = async () => {
    setItems((list) => (list || []).map((n) => ({ ...n, is_read: true })))
    setUnread(0)
    try {
      await markAllNotificationsRead()
    } catch {
      refreshCount()
    }
  }

  if (!user) return null

  return (
    <div className="notif-bell" ref={panelRef}>
      <button
        type="button"
        className="notif-bell-btn"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={toggle}
      >
        <Icon name="bell" size={18} strokeWidth={2} />
        {unread > 0 && <span className="notif-badge" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>

      {open && (
        <div className="notif-panel card-surface" role="dialog" aria-label="Notifications">
          <div className="notif-panel-head">
            <span className="section-label">Notifications</span>
            {(items || []).some((n) => !n.is_read) && (
              <button type="button" className="notif-mark-all" onClick={markAll} disabled={busy}>
                Mark All as Read
              </button>
            )}
          </div>

          <div className="notif-list">
            {busy && items === null && <p className="notif-empty">Loading…</p>}

            {!busy && items && items.length === 0 && (
              hasPrefs ? (
                <p className="notif-empty">No new matching jobs yet.</p>
              ) : (
                <div className="notif-empty">
                  <p>Set your job preferences to receive personalized job alerts.</p>
                  <button
                    type="button"
                    className="btn-primary notif-empty-cta"
                    onClick={() => {
                      setOpen(false)
                      onOpenPreferences?.()
                    }}
                  >
                    Set preferences
                  </button>
                </div>
              )
            )}

            {items && items.map((n) => (
              <article key={n.id} className={`notif-item ${n.is_read ? 'read' : 'unread'}`}>
                <div className="notif-item-top">
                  <span className="notif-item-title">{n.title}</span>
                  {!n.is_read && <span className="notif-unread-dot" aria-label="Unread" />}
                </div>
                <p className="notif-item-message">{n.message}</p>
                <div className="notif-item-foot">
                  <span className="notif-item-time">{timeAgo(n.created_at)}</span>
                  <span className="notif-item-actions">
                    {n.job && (
                      <button
                        type="button"
                        className="notif-action"
                        onClick={() => {
                          setOpen(false)
                          onViewJob?.(n)
                        }}
                      >
                        View Job
                      </button>
                    )}
                    {!n.is_read && (
                      <button
                        type="button"
                        className="notif-action"
                        onClick={() => markRead(n)}
                      >
                        Mark as Read
                      </button>
                    )}
                    {!n.job && <span className="notif-stale">listing no longer cached</span>}
                  </span>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
