// AuthStore 单元测试 — 覆盖 src/stores/auth.js
// 对齐 TESTING_STRATEGY.md §5.2：login/logout/refresh 并发防抖、scheduleRefresh

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import * as authApi from '@/api/auth'

// Mock @/api/auth —— 保留 store 真实逻辑，仅在 API 边界截断
vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  register: vi.fn(),
  refreshToken: vi.fn(),
  logout: vi.fn(),
}))

// 构造合法 JWT（payload 含 sub/username/role/exp）
function makeJwt(payload) {
  const header = { alg: 'HS256', typ: 'JWT' }
  const enc = (o) => btoa(JSON.stringify(o)).replace(/=/g, '')
  return `${enc(header)}.${enc(payload)}.sig`
}

function userJwt(role = 'user', userId = 1) {
  return makeJwt({ sub: String(userId), username: 'tester', role, exp: Math.floor(Date.now() / 1000) + 900 })
}

describe('AuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('login', () => {
    it('登录成功_token与用户信息持久化到localStorage', async () => {
      const at = userJwt('user', 42)
      const rt = 'refresh-token-abc'
      authApi.login.mockResolvedValue({ data: { data: { access_token: at, refresh_token: rt } } })

      const store = useAuthStore()
      const user = await store.login('tester', 'pass123')

      expect(store.token).toBe(at)
      expect(store.refreshToken).toBe(rt)
      expect(localStorage.getItem('access_token')).toBe(at)
      expect(localStorage.getItem('refresh_token')).toBe(rt)
      expect(user.id).toBe(42)
      expect(user.username).toBe('tester')
      expect(user.role).toBe('user')
      // user 也持久化
      expect(JSON.parse(localStorage.getItem('user')).id).toBe(42)
    })

    it('登录失败_token不写入', async () => {
      authApi.login.mockRejectedValue({ response: { data: { code: 'E1002' } } })
      const store = useAuthStore()
      await expect(store.login('tester', 'wrong')).rejects.toBeDefined()
      expect(store.token).toBe('')
      expect(localStorage.getItem('access_token')).toBeNull()
    })
  })

  describe('logout', () => {
    it('退出登录_清除token与user', async () => {
      const at = userJwt('user', 1)
      authApi.login.mockResolvedValue({ data: { data: { access_token: at, refresh_token: 'rt' } } })
      authApi.logout.mockResolvedValue({})
      const store = useAuthStore()
      await store.login('tester', 'pass')
      expect(store.isLoggedIn).toBe(true)

      await store.logout()
      expect(store.token).toBe('')
      expect(store.refreshToken).toBe('')
      expect(store.user).toBeNull()
      expect(store.isLoggedIn).toBe(false)
      expect(localStorage.getItem('access_token')).toBeNull()
    })

    it('后端logout失败_仍清除本地状态', async () => {
      const at = userJwt('user', 1)
      authApi.login.mockResolvedValue({ data: { data: { access_token: at, refresh_token: 'rt' } } })
      authApi.logout.mockRejectedValue(new Error('network'))
      const store = useAuthStore()
      await store.login('tester', 'pass')
      await store.logout()
      expect(store.token).toBe('')
      expect(store.isLoggedIn).toBe(false)
    })
  })

  describe('refresh 并发防抖', () => {
    it('并发调用refresh_仅发起一次API请求', async () => {
      const at1 = userJwt('user', 1)
      const at2 = makeJwt({ sub: '1', username: 'tester', role: 'user', exp: Math.floor(Date.now() / 1000) + 1000 })
      // 模拟一次耗时刷新
      authApi.refreshToken.mockImplementation(() =>
        new Promise((resolve) => setTimeout(() => resolve({ data: { data: { access_token: at2, refresh_token: 'rt2' } } }), 50))
      )
      const store = useAuthStore()
      store.refreshToken = 'old-rt'

      const [r1, r2] = await Promise.all([store.refresh(), store.refresh()])
      expect(r1).toBe(true)
      expect(r2).toBe(true)
      expect(authApi.refreshToken).toHaveBeenCalledTimes(1)
      expect(store.token).toBe(at2)
    })

    it('刷新成功_token对更新并持久化', async () => {
      const at2 = makeJwt({ sub: '1', username: 'tester', role: 'user', exp: Math.floor(Date.now() / 1000) + 2000 })
      authApi.refreshToken.mockResolvedValue({ data: { data: { access_token: at2, refresh_token: 'rt2' } } })
      const store = useAuthStore()
      store.refreshToken = 'old-rt'

      const ok = await store.refresh()
      expect(ok).toBe(true)
      expect(store.token).toBe(at2)
      expect(store.refreshToken).toBe('rt2')
      // 新 token 对持久化到 localStorage
      expect(localStorage.getItem('access_token')).toBe(at2)
      expect(localStorage.getItem('refresh_token')).toBe('rt2')
    })

    it('刷新失败_清除全部状态并抛出', async () => {
      authApi.refreshToken.mockRejectedValue(new Error('E1009'))
      const store = useAuthStore()
      store.refreshToken = 'old-rt'
      store.token = 'old-at'

      await expect(store.refresh()).rejects.toBeDefined()
      expect(store.token).toBe('')
      expect(store.refreshToken).toBe('')
      expect(store.user).toBeNull()
    })

    it('无refreshToken_refresh抛出错误', async () => {
      const store = useAuthStore()
      store.refreshToken = ''
      await expect(store.refresh()).rejects.toBeDefined()
      expect(authApi.refreshToken).not.toHaveBeenCalled()
    })
  })

  describe('register', () => {
    it('注册成功_不自动登录_token仍为空', async () => {
      authApi.register.mockResolvedValue({ data: { data: { id: 5, username: 'newuser' } } })
      const store = useAuthStore()
      const result = await store.register('newuser', 'pass123')
      expect(result.id).toBe(5)
      // 注册不自动登录
      expect(store.token).toBe('')
      expect(store.isLoggedIn).toBe(false)
    })
  })

  describe('isLoggedIn', () => {
    it('有token_isLoggedIn为true', async () => {
      const at = userJwt('user', 1)
      authApi.login.mockResolvedValue({ data: { data: { access_token: at, refresh_token: 'rt' } } })
      const store = useAuthStore()
      await store.login('tester', 'pass')
      expect(store.isLoggedIn).toBe(true)
    })
  })
})
