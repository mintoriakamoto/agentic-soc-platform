import axios, {AxiosError, type InternalAxiosRequestConfig} from 'axios'
import {useAuthStore} from '../stores/auth'
import {buildLoginRedirectPath, getCurrentAuthRedirectPath} from '../utils/authRedirect'

const client = axios.create({ baseURL: '/api' })

const REFRESH_PATH = '/auth/refresh/'

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retriedAfterRefresh?: boolean
}

// A separate instance so the refresh call itself never re-enters the interceptor below.
const refreshClient = axios.create({ baseURL: '/api' })

// Concurrent 401s share one refresh, so a page full of requests does not fire N refreshes and
// invalidate each other's rotated token.
let pendingRefresh: Promise<string> | null = null

function signOut() {
  useAuthStore.getState().logout()
  window.location.href = buildLoginRedirectPath(getCurrentAuthRedirectPath())
}

async function refreshAccessToken() {
  const { refreshToken } = useAuthStore.getState()
  if (!refreshToken) throw new Error('No refresh token')

  const { data } = await refreshClient.post<{ access: string; refresh?: string }>(REFRESH_PATH, {
    refresh: refreshToken,
  })
  // ROTATE_REFRESH_TOKENS is enabled, so keep the replacement when the server sends one.
  useAuthStore.getState().setToken(data.access, data.refresh ?? null)
  return data.access
}

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined

    if (error.response?.status !== 401) return Promise.reject(error)

    if (!original || original._retriedAfterRefresh || !useAuthStore.getState().refreshToken) {
      signOut()
      return Promise.reject(error)
    }

    try {
      pendingRefresh = pendingRefresh ?? refreshAccessToken().finally(() => { pendingRefresh = null })
      const token = await pendingRefresh
      original._retriedAfterRefresh = true
      original.headers.Authorization = `Bearer ${token}`
      return await client(original)
    } catch {
      signOut()
      return Promise.reject(error)
    }
  },
)

export default client
