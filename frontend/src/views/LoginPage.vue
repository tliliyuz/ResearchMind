<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Logo -->
      <div class="welcome-logo">
        <i class="fas fa-microscope"></i>
      </div>
      <h1 class="app-title">ResearchMind</h1>
      <p class="app-subtitle">可审计的结构化研究引擎</p>

      <!-- 切换 Tab -->
      <div class="tab-switch">
        <button
          :class="['tab-btn', { active: mode === 'login' }]"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          :class="['tab-btn', { active: mode === 'register' }]"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <!-- 表单 -->
      <form class="login-form" @submit.prevent="handleSubmit">
        <div class="input-group">
          <i class="fas fa-user prefix-icon"></i>
          <input
            v-model="username"
            class="form-input input-with-icon"
            :placeholder="mode === 'login' ? '请输入用户名' : '请设置用户名（至少 2 个字符）'"
            autocomplete="username"
          />
        </div>

        <div class="input-group">
          <i class="fas fa-lock prefix-icon"></i>
          <input
            v-model="password"
            class="form-input input-with-icon"
            type="password"
            :placeholder="mode === 'login' ? '请输入密码' : '请设置密码（至少 6 个字符）'"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          />
        </div>

        <!-- 错误提示 -->
        <div v-if="errorMsg" class="error-msg">
          <i class="fas fa-exclamation-circle"></i>
          {{ errorMsg }}
        </div>

        <!-- 提交按钮 -->
        <button type="submit" class="submit-btn" :disabled="loading">
          <i v-if="loading" class="fas fa-spinner fa-spin"></i>
          {{ mode === 'login' ? '登 录' : '注 册' }}
        </button>
      </form>

      <!-- 底部提示 -->
      <p class="toggle-tip">
        {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
        <a href="#" @click.prevent="switchMode(mode === 'login' ? 'register' : 'login')">
          {{ mode === 'login' ? '立即注册' : '去登录' }}
        </a>
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const mode = ref('login')
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

function switchMode(m) {
  mode.value = m
  username.value = ''
  password.value = ''
  errorMsg.value = ''
}

async function handleSubmit() {
  errorMsg.value = ''

  // 前端基础校验
  const name = username.value.trim()
  if (!name) {
    errorMsg.value = '请输入用户名'
    return
  }
  if (name.length < 2) {
    errorMsg.value = '用户名至少 2 个字符'
    return
  }
  if (/^\d+$/.test(name)) {
    errorMsg.value = '用户名不能为纯数字，请包含文字或字母'
    return
  }
  if (password.value.length < 6) {
    errorMsg.value = '密码至少 6 个字符'
    return
  }

  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.login(username.value.trim(), password.value)
      ElMessage.success('登录成功')
      router.push('/research')
    } else {
      await authStore.register(username.value.trim(), password.value)
      // 注册成功后切换到登录模式，清空密码
      mode.value = 'login'
      password.value = ''
      errorMsg.value = ''
      ElMessage.success('注册成功，请登录')
    }
  } catch (err) {
    const data = err.response?.data
    errorMsg.value = data?.message || '网络异常，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  width: 100%;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.10) 1px, transparent 1px),
    linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #0F172A 100%);
  background-size: 24px 24px, 100% 100%;
}

.login-card {
  width: 420px;
  padding: var(--rm-space-10) var(--rm-space-8);
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  box-shadow: var(--rm-shadow-lg);
  text-align: center;
}

/* Logo */
.welcome-logo {
  width: var(--rm-welcome-logo-size);
  height: var(--rm-welcome-logo-size);
  background: var(--rm-primary);
  border-radius: var(--rm-radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: var(--rm-text-2xl);
  margin: 0 auto;
}

.app-title {
  font-size: var(--rm-text-xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin-top: var(--rm-space-4);
}

.app-subtitle {
  font-size: var(--rm-text-xs);
  color: var(--rm-text-tertiary);
  margin-top: var(--rm-space-1);
  margin-bottom: var(--rm-space-6);
}

/* 切换 Tab */
.tab-switch {
  display: flex;
  background: var(--rm-border-light);
  border-radius: var(--rm-radius-sm);
  padding: var(--rm-space-1);
  margin-bottom: var(--rm-space-5);
}

.tab-btn {
  flex: 1;
  height: 34px;
  border: none;
  background: transparent;
  font-size: var(--rm-text-body);
  color: var(--rm-text-secondary);
  cursor: pointer;
  border-radius: var(--rm-space-1_5);
  transition: all var(--rm-transition-fast);
}

.tab-btn.active {
  background: var(--rm-bg-card);
  color: var(--rm-text-primary);
  font-weight: var(--rm-weight-semibold);
  box-shadow: var(--rm-shadow-sm);
}

/* 表单 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--rm-space-4);
}

/* 提交按钮 */
.submit-btn {
  width: 100%;
  height: 46px;
  background: var(--rm-primary);
  color: white;
  border: none;
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-sm);
  font-weight: var(--rm-weight-semibold);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-2);
  transition: all var(--rm-transition-normal);
  margin-top: var(--rm-space-2);
}

.submit-btn:hover:not(:disabled) {
  background: var(--rm-primary-hover);
  box-shadow: var(--rm-shadow-md);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 错误提示 */
.error-msg {
  display: flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  padding: var(--rm-space-2_5) var(--rm-space-3_5);
  background: var(--rm-danger-light);
  color: var(--rm-danger);
  font-size: var(--rm-text-xs);
  border-radius: var(--rm-radius-sm);
  text-align: left;
}

/* 底部切换提示 */
.toggle-tip {
  margin-top: var(--rm-space-5);
  font-size: var(--rm-text-xs);
  color: var(--rm-text-tertiary);
}

.toggle-tip a {
  color: var(--rm-primary);
  text-decoration: none;
  font-weight: var(--rm-weight-semibold);
}

.toggle-tip a:hover {
  text-decoration: underline;
}
</style>
