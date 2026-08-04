import {create} from 'zustand'
import {persist} from 'zustand/middleware'

export interface AuthUser {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  mobile_phone: string
  auth_type: 'local' | 'ldap'
  is_active: boolean
  role: 'admin' | 'user' | 'viewer'
  notify_on_playbook_completion: boolean
  notify_on_case_assignment: boolean
  has_avatar: boolean
  avatar_url: string
}

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: AuthUser | null
  setAuth: (token: string, user: AuthState['user'], refreshToken?: string | null) => void
  setToken: (token: string, refreshToken?: string | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      // refreshToken is only replaced when a caller actually supplies one. Callers that just
      // refresh the user profile omit it and must not clear the stored token.
      setAuth: (token, user, refreshToken) =>
        set((state) => ({ token, user, refreshToken: refreshToken ?? state.refreshToken })),
      setToken: (token, refreshToken) =>
        set((state) => ({ token, refreshToken: refreshToken ?? state.refreshToken })),
      logout: () => set({ token: null, refreshToken: null, user: null }),
    }),
    { name: 'asp-auth' },
  ),
)
