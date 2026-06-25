<template>
  <aside class="sidebar" :class="{ collapsed, 'menu-open': showUserMenu }">
    <!-- 顶部：折叠按钮 + Logo + 新建研究 -->
    <div class="sidebar-top">
      <!-- 收起按钮（仅展开态显示） -->
      <button
        v-show="!collapsed"
        class="collapse-toggle-btn"
        @click="toggleCollapse"
        title="收起侧边栏"
      >
        <i class="fas fa-bars"></i>
      </button>

      <!-- Logo：收起态点击可展开侧边栏 -->
      <div
        class="sidebar-logo"
        :class="{ 'logo-clickable': collapsed }"
        @click="collapsed && toggleCollapse()"
        :title="collapsed ? '展开侧边栏' : ''"
      >
        <div class="sidebar-logo-icon">
          <i class="fas fa-microscope"></i>
        </div>
        <div class="sidebar-logo-text" v-show="!collapsed">
          <span class="logo-title">ResearchMind</span>
          <span class="logo-subtitle">可审计的结构化研究引擎</span>
        </div>
      </div>

      <!-- 展开态：含文字按钮 -->
      <button
        class="new-research-btn"
        :class="{ active: route.path === '/research' }"
        @click="handleNewResearch"
        v-show="!collapsed"
      >
        <i class="fas fa-plus"></i>
        <span>新建研究</span>
      </button>
      <!-- 收起态：仅图标按钮 -->
      <button
        class="new-research-btn new-research-btn-icon"
        :class="{ active: route.path === '/research' }"
        @click="handleNewResearch"
        v-show="collapsed"
        title="新建研究"
      >
        <i class="fas fa-plus"></i>
      </button>
    </div>

    <!-- 中间：导航区域 + 历史任务列表 -->
    <div class="sidebar-middle">
      <!-- 导航链接 -->
      <nav class="rm-nav">
        <div class="section-label" v-show="!collapsed">导航</div>
        <router-link
          to="/history"
          class="nav-item"
          active-class="active"
          :title="collapsed ? '历史任务' : ''"
        >
          <i class="fas fa-history"></i>
          <span v-show="!collapsed">历史任务</span>
        </router-link>
      </nav>

      <!-- 历史任务列表（仅展开态） -->
      <div class="history-section" v-show="!collapsed">
        <div class="nav-group-label">最近任务</div>
        <div
          v-for="group in groupedTasks"
          :key="group.label"
        >
          <div class="time-group-label">{{ group.label }}</div>
          <div
            v-for="task in group.tasks"
            :key="task.task_id"
            class="nav-item task-item"
            :class="{ active: taskStore.current?.task_id === task.task_id }"
            @click="handleLoadTask(task)"
            :title="task.topic"
          >
            <i :class="taskStatusIcon(task.status)"></i>
            <span class="task-topic-sidebar">{{ task.topic }}</span>
          </div>
        </div>
        <!-- 加载中或无任务 -->
        <div
          v-if="taskStore.taskList.length === 0 && !taskStore.listLoading"
          class="history-empty"
        >
          <span class="history-empty-text">暂无任务</span>
        </div>
      </div>
    </div>

    <!-- 底部：用户信息 -->
    <div class="sidebar-bottom">
      <div class="user-bar" ref="userBarRef">
        <div
          class="user-avatar"
          :title="collapsed ? '用户菜单' : ''"
          @click.stop="toggleUserMenu"
        >
          {{ authStore.user?.username?.charAt(0)?.toUpperCase() || 'U' }}
        </div>
        <div class="user-info" v-show="!collapsed" @click.stop="toggleUserMenu">
          <div class="user-name">{{ authStore.user?.username || '用户' }}</div>
          <div class="user-role">{{ authStore.isAdmin ? '管理员' : '用户' }}</div>
        </div>

        <!-- 用户菜单卡片 -->
        <div class="user-menu-card" v-show="showUserMenu" @click.stop>
          <!-- 用户信息头部 -->
          <div class="user-menu-header">
            <div class="user-avatar">
              {{ authStore.user?.username?.charAt(0)?.toUpperCase() || 'U' }}
            </div>
            <div class="user-menu-header-info">
              <div class="user-name">{{ authStore.user?.username || '用户' }}</div>
              <div class="user-role">{{ authStore.isAdmin ? '管理员' : '用户' }}</div>
            </div>
          </div>
          <!-- 菜单选项 -->
          <button class="user-menu-item" @click="handleMenuChangePassword">
            <i class="fas fa-lock"></i>
            <span>修改密码</span>
          </button>
          <button
            v-if="authStore.isAdmin"
            class="user-menu-item"
            @click="handleMenuAdmin"
          >
            <i class="fas fa-shield-alt"></i>
            <span>管理后台</span>
          </button>
          <button class="user-menu-item danger" @click="handleMenuLogout">
            <i class="fas fa-sign-out-alt"></i>
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 修改密码弹窗 -->
    <el-dialog
      v-model="changePasswordDialogVisible"
      title="修改密码"
      width="420px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordFormRules"
        label-position="top"
        @submit.prevent="handleChangePassword"
      >
        <el-form-item label="当前密码" prop="oldPassword">
          <el-input
            v-model="passwordForm.oldPassword"
            type="password"
            show-password
            placeholder="请输入当前密码"
            autocomplete="current-password"
          />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="passwordForm.newPassword"
            type="password"
            show-password
            placeholder="请输入新密码，至少 6 位"
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input
            v-model="passwordForm.confirmPassword"
            type="password"
            show-password
            placeholder="请再次输入新密码"
            autocomplete="new-password"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changePasswordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingPassword" @click="handleChangePassword">
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </aside>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useTaskStore } from '@/stores/task'
import { changePassword } from '@/api/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const taskStore = useTaskStore()

/** 侧边栏折叠状态 */
const collapsed = ref(false)

// ===== 历史任务列表（侧边栏内） =====

/** 按时间分组的任务列表 */
const groupedTasks = computed(() => {
  const tasks = taskStore.taskList || []
  if (tasks.length === 0) return []

  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterdayStart = new Date(todayStart.getTime() - 86400000)
  const weekStart = new Date(todayStart.getTime() - 7 * 86400000)

  const groups = [
    { label: '今天', tasks: [] },
    { label: '昨天', tasks: [] },
    { label: '近 7 天', tasks: [] },
    { label: '更早', tasks: [] },
  ]

  for (const task of tasks) {
    const created = new Date(task.created_at)
    if (created >= todayStart) {
      groups[0].tasks.push(task)
    } else if (created >= yesterdayStart) {
      groups[1].tasks.push(task)
    } else if (created >= weekStart) {
      groups[2].tasks.push(task)
    } else {
      groups[3].tasks.push(task)
    }
  }

  return groups.filter(g => g.tasks.length > 0)
})

/** 任务状态图标映射 */
function taskStatusIcon(status) {
  const map = {
    completed: 'fas fa-circle-check',
    partially_completed: 'fas fa-triangle-exclamation',
    failed: 'fas fa-times-circle',
    canceled: 'fas fa-ban',
    running: 'fas fa-spinner fa-spin',
    pending: 'fas fa-clock',
  }
  return map[status] || 'fas fa-question-circle'
}

/** 点击历史任务 → 加载详情并跳转研究页 */
async function handleLoadTask(task) {
  try {
    await taskStore.fetchDetail(task.task_id)
    router.push('/research')
  } catch {
    ElMessage.error('加载任务失败')
  }
}

// 挂载时加载最近任务
onMounted(async () => {
  try {
    await taskStore.fetchList({ page: 1, page_size: 10 })
  } catch {
    // 侧边栏列表加载失败非关键，静默处理
  }
})

// ===== 用户菜单卡片 =====
const showUserMenu = ref(false)
const userBarRef = ref(null)

/** 切换用户菜单卡片可见性 */
function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

/** 关闭用户菜单卡片 */
function closeUserMenu() {
  showUserMenu.value = false
}

/** 点击菜单「修改密码」→ 关闭卡片 → 打开改密弹窗 */
function handleMenuChangePassword() {
  closeUserMenu()
  openChangePasswordDialog()
}

/** 点击菜单「管理后台」→ 关闭卡片 → 跳转管理后台 */
function handleMenuAdmin() {
  closeUserMenu()
  router.push('/admin')
}

/** 点击菜单「退出登录」→ 关闭卡片 → 执行退出 */
function handleMenuLogout() {
  closeUserMenu()
  handleLogout()
}

/** 点击文档任意位置关闭用户菜单（排除菜单内部和触发区域） */
function onDocumentClick(e) {
  const userBar = userBarRef.value
  if (userBar && !userBar.contains(e.target)) {
    closeUserMenu()
  }
}

// 菜单打开时注册 document click 监听（setTimeout 推迟避免与打开菜单的同一 click 事件冲突）
watch(showUserMenu, (val) => {
  if (val) {
    setTimeout(() => {
      document.addEventListener('click', onDocumentClick)
    }, 0)
  } else {
    document.removeEventListener('click', onDocumentClick)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
})

// ===== 修改密码弹窗 =====
const changePasswordDialogVisible = ref(false)
const passwordFormRef = ref(null)
const submittingPassword = ref(false)
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

/** 确认密码一致性校验 */
function validateConfirmPassword(rule, value, callback) {
  if (value !== passwordForm.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
  } else {
    callback()
  }
}

const passwordFormRules = {
  oldPassword: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

/** 新建研究 — 跳转到研究页 */
function handleNewResearch() {
  taskStore.clearCurrent()
  router.push('/research')
}

/** 退出登录 */
async function handleLogout() {
  try {
    await ElMessageBox.confirm(
      '退出后需重新登录，是否继续？',
      '确认退出',
      {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return // 用户取消，不执行退出
  }
  await authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

/** 打开修改密码弹窗（清空表单 + 重置校验） */
function openChangePasswordDialog() {
  passwordForm.oldPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  if (passwordFormRef.value) {
    passwordFormRef.value.resetFields()
  }
  changePasswordDialogVisible.value = true
}

/** 提交修改密码 */
async function handleChangePassword() {
  if (!passwordFormRef.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return // 校验失败不提交
  }
  submittingPassword.value = true
  try {
    await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    ElMessage.success('密码修改成功，请重新登录')
    changePasswordDialogVisible.value = false
    // 改密后吊销全部 refresh_token，清空本地状态并跳转登录
    await authStore.logout()
    router.push('/login')
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '修改失败，请检查当前密码是否正确')
  } finally {
    submittingPassword.value = false
  }
}
</script>

<style scoped>
.sidebar {
  width: var(--rm-sidebar-width);
  background: var(--rm-bg-sidebar);
  border-right: 1px solid var(--rm-border-dark);
  display: flex;
  flex-direction: column;
  z-index: 10;
  flex-shrink: 0;
  transition: width var(--rm-transition-normal);
  overflow-x: hidden;
}

/* 用户菜单打开时解除 overflow 裁剪，确保收起态卡片不被截断 */
.sidebar.menu-open {
  overflow-x: visible;
}

/* 收起状态 */
.sidebar.collapsed {
  width: var(--rm-sidebar-width-collapsed);
}

/* ===== 顶部区域 ===== */
.sidebar-top {
  padding: var(--rm-space-5) var(--rm-space-4);
  border-bottom: 1px solid var(--rm-border-dark);
  position: relative;
}

/* 折叠切换按钮 */
.collapse-toggle-btn {
  position: absolute;
  top: var(--rm-space-3_5);
  right: var(--rm-space-3);
  width: var(--rm-space-7);
  height: var(--rm-space-7);
  border: none;
  background: transparent;
  color: var(--rm-text-inverse-dim);
  cursor: pointer;
  border-radius: var(--rm-radius-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--rm-text-xs);
  transition: all var(--rm-transition-fast);
  z-index: 1;
}

.collapse-toggle-btn:hover {
  background: var(--rm-bg-sidebar-hover);
  color: var(--rm-text-inverse);
}

/* Logo 区域 */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  margin-bottom: var(--rm-space-4);
}

/* 收起态：Logo 居中且可点击展开 */
.collapsed .sidebar-logo {
  justify-content: center;
  margin-bottom: var(--rm-space-3);
}

.logo-clickable {
  cursor: pointer;
}

.sidebar-logo-icon {
  width: var(--rm-sidebar-logo-size);
  height: var(--rm-sidebar-logo-size);
  background: var(--rm-primary);
  border-radius: var(--rm-radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: var(--rm-text-sm);
  flex-shrink: 0;
}

.sidebar-logo-text {
  display: flex;
  flex-direction: column;
  line-height: var(--rm-leading-title);
}

.logo-title {
  font-size: var(--rm-text-sm);
  color: var(--rm-text-inverse);
  font-weight: var(--rm-weight-semibold);
}

.logo-subtitle {
  font-size: var(--rm-text-3xs);
  color: var(--rm-text-inverse-dim);
  font-weight: var(--rm-weight-normal);
  margin-top: calc(var(--rm-space-1) / 2);
}

/* 新建研究按钮 */
.new-research-btn {
  width: 100%;
  height: 38px;
  padding: 0 var(--rm-space-3_5);
  background: var(--rm-primary);
  color: white;
  border: none;
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-body);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-2);
  transition: all var(--rm-transition-normal);
}

.new-research-btn:hover {
  background: var(--rm-primary-hover);
}

.new-research-btn.active {
  background: var(--rm-primary);
  color: white;
}

/* 收起态：仅图标的按钮 */
.new-research-btn-icon {
  width: var(--rm-sidebar-logo-size);
  height: var(--rm-sidebar-logo-size);
  padding: 0;
  margin: 0 auto;
  border-radius: var(--rm-radius-sm);
}

/* ===== 中间区域 ===== */
.sidebar-middle {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: var(--rm-space-3) var(--rm-space-3);
  min-height: 0;
}

/* 收起态 */
.collapsed .sidebar-middle {
  padding: var(--rm-space-2);
}

.rm-nav {
  flex-shrink: 0;
}

.section-label {
  font-size: var(--rm-text-3xs);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-inverse-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: var(--rm-space-2) var(--rm-space-3);
  margin-top: var(--rm-space-2);
}

/* ===== 导航项 ===== */
.nav-item {
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
}

.nav-item:hover {
  background: var(--rm-bg-sidebar-hover);
  color: var(--rm-text-inverse);
}

.nav-item.active {
  background: var(--rm-bg-sidebar-active);
  color: var(--rm-text-inverse);
  font-weight: var(--rm-weight-semibold);
}

.nav-item i {
  width: var(--rm-space-5);
  text-align: center;
  font-size: var(--rm-text-sm);
}

/* 收起态：导航项仅图标居中 */
.collapsed .nav-item {
  justify-content: center;
  padding: var(--rm-space-3) 0;
}

.collapsed .nav-item i {
  width: auto;
}

/* ===== 底部区域 ===== */
.sidebar-bottom {
  padding: var(--rm-space-3) var(--rm-space-4);
  border-top: 1px solid var(--rm-border-dark);
}

/* 收起态 */
.collapsed .sidebar-bottom {
  padding: var(--rm-space-3);
}

.user-bar {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  padding: var(--rm-space-2);
  border-radius: var(--rm-radius-sm);
  transition: background var(--rm-transition-fast);
  position: relative;
}

/* 收起态：用户栏居中 */
.collapsed .user-bar {
  justify-content: center;
}

.user-avatar {
  width: var(--rm-space-8);
  height: var(--rm-space-8);
  border-radius: var(--rm-radius-full);
  background: var(--rm-primary-dark);
  border: 1px solid var(--rm-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  flex-shrink: 0;
  cursor: pointer;
  transition: opacity var(--rm-transition-fast);
}

.user-avatar:hover {
  opacity: 0.85;
}

.user-info {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.user-name {
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-inverse-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: var(--rm-text-3xs);
  color: var(--rm-primary);
}

/* ===== 用户菜单卡片 ===== */
.user-menu-card {
  position: absolute;
  bottom: 100%;
  right: 0;
  margin-bottom: var(--rm-space-2);
  min-width: 200px;
  background: var(--rm-bg-sidebar-active);
  border: 1px solid var(--rm-border-darker);
  border-radius: var(--rm-radius-md);
  box-shadow: var(--rm-shadow-lg);
  overflow: hidden;
  z-index: 100;
  animation: menuSlideUp var(--rm-transition-normal) ease;
}

/* 收起态：卡片从用户栏右侧弹出，底部对齐用户栏、向上展开 */
.collapsed .user-menu-card {
  left: 100%;
  right: auto;
  bottom: 0;
  top: auto;
  margin-bottom: 0;
  margin-left: var(--rm-space-2);
}

@keyframes menuSlideUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

.user-menu-header {
  padding: var(--rm-space-4);
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  border-bottom: 1px solid var(--rm-border-darker);
}

.user-menu-header-info {
  flex: 1;
  min-width: 0;
}

.user-menu-item {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
  padding: var(--rm-space-3) var(--rm-space-4);
  cursor: pointer;
  transition: background var(--rm-transition-fast);
  font-size: var(--rm-text-body);
  color: var(--rm-text-inverse-secondary);
  border: none;
  background: transparent;
  width: 100%;
  font-family: inherit;
}

.user-menu-item:hover {
  background: var(--rm-bg-sidebar-hover);
}

/* 危险操作项 */
.user-menu-item.danger {
  color: var(--rm-danger);
}

.user-menu-item.danger:hover {
  background: var(--rm-danger-border);
}

.user-menu-item i {
  width: calc(var(--rm-space-4) + var(--rm-space-1) / 2);
  text-align: center;
  font-size: var(--rm-text-sm);
}

/* ===== 历史任务列表 ===== */
.history-section {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  margin-top: var(--rm-space-3);
  padding-bottom: var(--rm-space-2);
}

.nav-group-label {
  font-size: var(--rm-text-3xs);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-inverse-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: var(--rm-space-2) var(--rm-space-3);
}

.time-group-label {
  font-size: var(--rm-text-3xs);
  color: var(--rm-text-inverse-dim);
  padding: var(--rm-space-1) var(--rm-space-3);
  margin-top: var(--rm-space-1);
}

.task-item {
  padding: var(--rm-space-1_5) var(--rm-space-3);
}

.task-item i {
  flex-shrink: 0;
  font-size: var(--rm-text-3xs);
}

/* 任务主题截断 */
.task-topic-sidebar {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

/* 状态图标颜色 */
.task-item i.fa-circle-check { color: var(--rm-success); }
.task-item i.fa-triangle-exclamation { color: var(--rm-warning); }
.task-item i.fa-times-circle { color: var(--rm-danger); }
.task-item i.fa-ban { color: var(--rm-text-inverse-dim); }
.task-item i.fa-spinner { color: var(--rm-secondary); }
.task-item i.fa-clock { color: var(--rm-text-inverse-dim); }

.history-empty {
  padding: var(--rm-space-4) var(--rm-space-3);
  text-align: center;
}

.history-empty-text {
  font-size: var(--rm-text-2xs);
  color: var(--rm-text-inverse-dim);
}
</style>
