// 路由守卫测试 — 直接测试 src/router/index.js 导出的 authGuard + routes
// 对齐 TESTING_STRATEGY.md §5.4：未登录→/login、已登录访问/login→/research、非admin→/admin重定向
//
// 重要：import 真实 authGuard 函数和 routes，禁止复制生产代码。
// Pinia 必须在 import 前激活，因为 authGuard 内部调用 useAuthStore()。

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { createRouter, createMemoryHistory } from 'vue-router'

// Pinia 必须先激活（authGuard → useAuthStore()）
setActivePinia(createPinia())

// 导入真实路由定义和守卫（禁止复制生产代码）
const { authGuard, default: realRouter } = await import('@/router/index')

function makeJwt(payload) {
  const enc = (o) => btoa(JSON.stringify(o)).replace(/=/g, '')
  return `${enc({ alg: 'HS256', typ: 'JWT' })}.${enc(payload)}.sig`
}

function setupStore({ loggedIn, role = 'user' } = {}) {
  const store = useAuthStore()
  if (loggedIn) {
    const at = makeJwt({ sub: '1', username: 'tester', role, exp: Math.floor(Date.now() / 1000) + 900 })
    store.setTokens(at, 'rt')
    store.user = { id: 1, username: 'tester', role }
  } else {
    store.user = null
    store.token = ''
  }
  return store
}

/** 创建测试用 router：真实 routes + 真实 authGuard */
function buildRouter() {
  const router = createRouter({ history: createMemoryHistory(), routes: realRouter.options.routes })
  router.beforeEach(authGuard)
  return router
}

describe('路由守卫（真实 authGuard + routes）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('未登录访问需认证页面_重定向到/login', async () => {
    setupStore({ loggedIn: false })
    const router = buildRouter()
    await router.push('/research')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('未登录访问/history_重定向到/login', async () => {
    setupStore({ loggedIn: false })
    const router = buildRouter()
    await router.push('/history')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('已登录用户访问/login_重定向到/research', async () => {
    setupStore({ loggedIn: true, role: 'user' })
    const router = buildRouter()
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/research')
  })

  it('普通用户访问/admin_重定向到/research', async () => {
    setupStore({ loggedIn: true, role: 'user' })
    const router = buildRouter()
    await router.push('/admin/stats')
    expect(router.currentRoute.value.path).toBe('/research')
  })

  it('admin用户访问/admin_允许通过', async () => {
    setupStore({ loggedIn: true, role: 'admin' })
    const router = buildRouter()
    await router.push('/admin/stats')
    expect(router.currentRoute.value.path).toBe('/admin/stats')
  })

  it('已登录普通用户访问/research_允许通过', async () => {
    setupStore({ loggedIn: true, role: 'user' })
    const router = buildRouter()
    await router.push('/research')
    expect(router.currentRoute.value.path).toBe('/research')
  })

  it('根路径重定向到/research', async () => {
    setupStore({ loggedIn: true, role: 'user' })
    const router = buildRouter()
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/research')
  })
})
