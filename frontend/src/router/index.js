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
  // Admin 独立布局（嵌套路由）
  {
    path: '/admin',
    component: () => import('@/components/layout/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        redirect: '/admin/stats',
      },
      {
        path: 'stats',
        name: 'AdminStats',
        component: () => import('@/views/admin/StatsPage.vue'),
      },
      {
        path: 'tasks',
        name: 'AdminTasks',
        component: () => import('@/views/admin/AdminTaskList.vue'),
      },
      {
        path: 'tasks/:task_id',
        name: 'AdminTaskDetail',
        component: () => import('@/views/admin/AdminTaskDetail.vue'),
      },
      {
        path: 'users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/AdminUserList.vue'),
      },
      {
        path: 'users/:user_id',
        name: 'AdminUserDetail',
        component: () => import('@/views/admin/AdminUserDetail.vue'),
      },
    ],
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

  // 需要管理员权限 → 非 admin 用户重定向
  // 使用 to.matched 遍历所有匹配路由记录，因为 Vue Router 4 子路由不继承父路由 meta
  const requiresAdmin = to.matched.some(record => record.meta.requiresAdmin)
  if (requiresAdmin && !authStore.isAdmin) {
    next('/research')
    return
  }

  next()
}

router.beforeEach(authGuard)

export default router
