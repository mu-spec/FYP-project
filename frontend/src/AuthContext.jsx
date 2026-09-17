/**
 * Milestone 8A.1 — central authentication state.
 *
 * Owns the single source of truth for "who is signed in":
 *   - on startup it asks the server (GET /api/auth/me) and only then lets the
 *     app render (the protected UI stays hidden while the check is running);
 *   - exposes signUp / signIn / signOut used by the authentication screen and
 *     the navbar user menu;
 *   - listens for 401s from any protected API call and drops the user so the
 *     app falls back to the Sign In screen.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getCurrentUser, signIn as apiSignIn, signOut as apiSignOut, signUp as apiSignUp, UNAUTHORIZED_EVENT } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getCurrentUser()
      .then((data) => {
        if (cancelled) return
        setUser(data && data.authenticated ? data.user : null)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setAuthLoading(false)
      })
    const onUnauthorized = () => setUser(null)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => {
      cancelled = true
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  }, [])

  const signIn = useCallback(async (email, password) => {
    const data = await apiSignIn(email, password)
    setUser(data.user)
    return data
  }, [])

  const signUp = useCallback(async (name, email, password, confirm) => {
    const data = await apiSignUp(name, email, password, confirm)
    setUser(data.user)
    return data
  }, [])

  // Server session destroyed; clearing the user unmounts the whole protected
  // app (which also drops any in-progress result). Stored history is kept.
  const signOut = useCallback(async () => {
    try {
      await apiSignOut()
    } finally {
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, authLoading, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
