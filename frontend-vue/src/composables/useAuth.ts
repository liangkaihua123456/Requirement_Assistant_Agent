import { ref } from 'vue'
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { TokenResponse, User, RegisterRequest, ForgotPasswordResponse } from '@/types'

const ACCESS_KEY = 'agent-access-token'
const REFRESH_KEY = 'agent-refresh-token'

export const authed = ref<User | null>(null)

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function isAuthenticated(): boolean {
  return !!getAccessToken()
}

function setTokens(token: TokenResponse): void {
  localStorage.setItem(ACCESS_KEY, token.access_token)
  localStorage.setItem(REFRESH_KEY, token.refresh_token)
}

function clearSession(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  authed.value = null
}

// 共享 axios 实例：自动带 Authorization，并在 401 时用 refresh token 续期后重试一次
export const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem(REFRESH_KEY)
  if (!refreshToken) return null
  try {
    const { data } = await axios.post<TokenResponse>('/api/user/refresh', {
      refresh_token: refreshToken,
    })
    setTokens(data)
    return data.access_token
  } catch {
    clearSession()
    return null
  }
}

interface RetriableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableRequest | undefined
    const status = error.response?.status
    // 仅在 401、非刷新接口、且未重试过时尝试刷新
    if (original && status === 401 && !original._retry && !original.url?.includes('/user/refresh')) {
      original._retry = true
      refreshPromise = refreshPromise ?? refreshAccessToken()
      const newToken = await refreshPromise
      refreshPromise = null
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return http(original)
      }
    }
    return Promise.reject(error)
  },
)

async function fetchMe(): Promise<User | null> {
  if (!isAuthenticated()) return null
  try {
    const { data } = await http.get<User>('/user/me')
    authed.value = data
    return data
  } catch {
    clearSession()
    return null
  }
}


// 把后端/校验错误压成一句"为什么不行"
const FIELD_LABEL: Record<string, string> = {
  username: '用户名',
  password: '密码',
  email: '邮箱',
  account: '用户名或邮箱',
  new_password: '新密码',
  old_password: '原密码',
  token: '重置令牌',
  user_input: '需求内容',
}

function shortFrom422(detail: unknown): string {
  if (!Array.isArray(detail) || detail.length === 0) return ''
  const item = detail[0] as { loc?: unknown[]; msg?: string; type?: string }
  const loc = Array.isArray(item.loc) ? item.loc : []
  const field = loc.length ? String(loc[loc.length - 1]) : ''
  const label = FIELD_LABEL[field] || ''
  const type = item.type || ''
  if (type === 'missing') return `${label}不能为空` || '请填写必填项'
  if (type === 'string_too_short') {
    const n = (item.msg || '').match(/(\d+)/)?.[1] || ''
    return n ? `${label}至少 ${n} 位` : `${label}太短`
  }
  if (type === 'string_too_long') return `${label}太长`
  if (type === 'email_parsing' || type === 'value_error') return `${label}格式不正确` || '邮箱格式不正确'
  return `${label}格式不正确` || '请检查输入'
}

export function authErrorMessage(err: unknown, fallback = '操作失败，请重试'): string {
  const e = err as { response?: { status?: number; data?: { detail?: unknown } } }
  const status = e?.response?.status
  const detail = e?.response?.data?.detail
  switch (status) {
    case 401:
      return '用户名或密码错误'
    case 403:
      return '账号已被禁用'
    case 409:
      return '用户名或邮箱已存在'
    case 400:
      return typeof detail === 'string' ? detail : '链接或重置令牌无效'
    case 422:
      return shortFrom422(detail) || '请检查输入格式'
    default:
      return fallback
  }
}


export function useAuth() {
  async function login(username: string, password: string): Promise<boolean> {
    const { data } = await http.post<TokenResponse>('/user/login', { username, password })
    setTokens(data)
    await fetchMe()
    return true
  }

  async function register(payload: RegisterRequest): Promise<User> {
    const { data } = await http.post<User>('/user/register', payload)
    // 注册成功后自动登录
    const tokens = await http.post<TokenResponse>('/user/login', {
      username: payload.username,
      password: payload.password,
    })
    setTokens(tokens.data)
    await fetchMe()
    return data
  }

  async function forgotPassword(account: string): Promise<ForgotPasswordResponse> {
    const { data } = await http.post<ForgotPasswordResponse>('/user/forgot-password', { account })
    return data
  }

  async function resetPassword(token: string, newPassword: string): Promise<void> {
    await http.post('/user/reset-password', { token, new_password: newPassword })
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
    await http.post('/user/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  }

  async function logout(): Promise<void> {
    try {
      await http.post('/user/logout')
    } catch {
      // 无状态 JWT，忽略登接接口失败
    }
    clearSession()
  }

  // 应用启动时恢复会话
  if (isAuthenticated()) {
    void fetchMe()
  }

  return {
    authed,
    isAuthenticated,
    login,
    register,
    forgotPassword,
    resetPassword,
    changePassword,
    logout,
    fetchMe,
  }
}
