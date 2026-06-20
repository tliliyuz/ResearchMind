<template>
  <div class="admin-layout">
    <!-- Admin 专用侧边栏 -->
    <aside class="admin-sidebar">
      <!-- 顶部：Logo + 标题 -->
      <div class="admin-sidebar-top">
        <div class="admin-logo-icon">
          <i class="fas fa-shield-alt"></i>
        </div>
        <div class="admin-logo-text">
          <span class="admin-title">管理后台</span>
          <span class="admin-subtitle">ResearchMind Admin</span>
        </div>
      </div>

      <!-- 导航菜单 -->
      <nav class="admin-nav">
        <router-link
          to="/admin/stats"
          class="admin-nav-item"
          active-class="active"
        >
          <i class="fas fa-chart-bar"></i>
          <span>系统统计</span>
        </router-link>
        <router-link
          to="/admin/tasks"
          class="admin-nav-item"
          :class="{ active: isTasksActive }"
        >
          <i class="fas fa-list-check"></i>
          <span>任务管理</span>
        </router-link>
        <router-link
          to="/admin/users"
          class="admin-nav-item"
          :class="{ active: isUsersActive }"
        >
          <i class="fas fa-users"></i>
          <span>用户管理</span>
        </router-link>
      </nav>

      <!-- 底部：返回研究 -->
      <div class="admin-sidebar-bottom">
        <router-link to="/research" class="back-to-app-btn">
          <i class="fas fa-arrow-left"></i>
          <span>返回研究</span>
        </router-link>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="admin-main">
      <header class="admin-header">
        <h1 class="admin-page-title">{{ pageTitle }}</h1>
      </header>
      <main class="admin-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const pageTitle = computed(() => {
  const titles = {
    AdminStats: '系统统计',
    AdminTasks: '任务管理',
    AdminTaskDetail: '任务详情',
    AdminUsers: '用户管理',
    AdminUserDetail: '用户详情',
  }
  return titles[route.name] || '管理后台'
})

/** 任务管理菜单高亮：列表页和详情页都激活 */
const isTasksActive = computed(() => {
  return route.name === 'AdminTasks' || route.name === 'AdminTaskDetail'
})

/** 用户管理菜单高亮：列表页和详情页都激活 */
const isUsersActive = computed(() => {
  return route.name === 'AdminUsers' || route.name === 'AdminUserDetail'
})
</script>

<style scoped>
.admin-layout {
  width: 100%;
  height: 100vh;
  display: flex;
}

/* ===== Admin 侧边栏 ===== */
.admin-sidebar {
  width: var(--rm-sidebar-width-admin);
  background: var(--rm-bg-sidebar);
  border-right: 1px solid var(--rm-border-dark);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  z-index: 10;
}

.admin-sidebar-top {
  padding: var(--rm-space-5) var(--rm-space-4);
  border-bottom: 1px solid var(--rm-border-dark);
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
}

.admin-logo-icon {
  width: var(--rm-space-9);
  height: var(--rm-space-9);
  background: var(--rm-primary);
  border-radius: var(--rm-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: var(--rm-text-sm);
  flex-shrink: 0;
}

.admin-logo-text {
  display: flex;
  flex-direction: column;
  line-height: var(--rm-leading-title);
}

.admin-title {
  font-size: var(--rm-text-body);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-inverse);
}

.admin-subtitle {
  font-size: var(--rm-text-3xs);
  color: var(--rm-text-inverse-dim);
}

/* 导航 */
.admin-nav {
  flex: 1;
  padding: var(--rm-space-3) var(--rm-space-3);
  overflow-y: auto;
}

.admin-nav-item {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  padding: var(--rm-space-3) var(--rm-space-3_5);
  border-radius: var(--rm-radius-sm);
  cursor: pointer;
  transition: all var(--rm-transition-fast);
  font-size: var(--rm-text-body);
  color: var(--rm-text-inverse-secondary);
  text-decoration: none;
  margin-bottom: calc(var(--rm-space-1) / 2);
}

.admin-nav-item:hover {
  background: var(--rm-bg-sidebar-hover);
  color: var(--rm-text-inverse);
}

.admin-nav-item.active {
  background: var(--rm-bg-sidebar-active);
  color: var(--rm-text-inverse);
  font-weight: var(--rm-weight-semibold);
}

.admin-nav-item i {
  width: var(--rm-space-5);
  text-align: center;
  font-size: var(--rm-text-sm);
}

/* 底部返回按钮 */
.admin-sidebar-bottom {
  padding: var(--rm-space-3) var(--rm-space-4);
  border-top: 1px solid var(--rm-border-dark);
}

.back-to-app-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-2);
  padding: var(--rm-space-2_5) var(--rm-space-3_5);
  border-radius: var(--rm-radius-sm);
  cursor: pointer;
  transition: all var(--rm-transition-fast);
  font-size: var(--rm-text-body);
  color: var(--rm-text-inverse-secondary);
  text-decoration: none;
  background: var(--rm-bg-sidebar-hover);
}

.back-to-app-btn:hover {
  background: var(--rm-bg-sidebar-active);
  color: var(--rm-text-inverse);
}

.back-to-app-btn i {
  font-size: var(--rm-text-sm);
}

/* ===== 主内容区 ===== */
.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--rm-bg-page);
  overflow: hidden;
}

.admin-header {
  height: var(--rm-header-height);
  background: var(--rm-bg-sidebar);
  border-bottom: 1px solid var(--rm-border-dark);
  display: flex;
  align-items: center;
  padding: 0 var(--rm-space-6);
  z-index: 5;
  flex-shrink: 0;
}

.admin-page-title {
  font-size: var(--rm-text-lg);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-inverse);
}

.admin-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--rm-space-6) var(--rm-space-7);
}
</style>
