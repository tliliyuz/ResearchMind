<template>
  <!-- 公开页面（登录页）：不加布局 -->
  <router-view v-if="$route.meta.public" />
  <!-- 其他需认证页面：使用 AppLayout（含用户侧边栏） -->
  <AppLayout v-else>
    <router-view />
  </AppLayout>
</template>

<script setup>
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const route = useRoute()
</script>
