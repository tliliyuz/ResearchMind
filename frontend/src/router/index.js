import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginPage.vue'),
    meta: { public: true }
  },
  {
    path: '/research',
    name: 'Research',
    component: () => import('@/views/ResearchPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('@/views/HistoryPage.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/',
    redirect: '/research'
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/research'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫 — 认证与权限检查
// 提取为命名导出，便于测试直接引用真实逻辑（禁止测试中复制守卫代码）
export function authGuard(to, from, next) {
  const authStore = useAuthStore()

  // 已登录用户访问公开页面（如登录页）→ 重定向到研究页
  if (to.meta.public && authStore.isLoggedIn) {
    next('/research')
    return
  }

  // 需要认证的页面 → 未登录则跳转登录页
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    next('/login')
    return
  }

  next()
}

router.beforeEach(authGuard)

export default router
