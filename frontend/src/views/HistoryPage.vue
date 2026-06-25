<template>
  <div class="history-page">
    <!-- ===== 工具栏 ===== -->
    <div class="history-toolbar">
      <div class="toolbar-left">
        <el-select
          v-model="filterStatus"
          placeholder="全部状态"
          clearable
          style="width: 140px"
          @change="onFilterChange"
        >
          <el-option label="全部" value="" />
          <el-option label="排队中" value="pending" />
          <el-option label="运行中" value="running" />
          <el-option label="已完成" value="completed" />
          <el-option label="部分完成" value="partially_completed" />
          <el-option label="失败" value="failed" />
          <el-option label="已取消" value="canceled" />
        </el-select>

        <el-input
          v-model="searchKeyword"
          placeholder="搜索主题..."
          clearable
          class="search-input"
          @input="onSearchDebounced"
        >
          <template #prefix>
            <i class="fas fa-search"></i>
          </template>
        </el-input>
      </div>

      <el-button type="primary" @click="router.push('/research')">
        <i class="fas fa-plus"></i> 新建研究
      </el-button>
    </div>

    <!-- ===== 表格 ===== -->
    <el-table
      :data="taskStore.taskList"
      v-loading="taskStore.listLoading"
      stripe
      style="width: 100%"
    >
      <!-- 空状态 -->
      <template #empty>
        <div class="empty-state">
          <i class="fas fa-inbox empty-icon"></i>
          <p class="empty-title">暂无研究任务</p>
          <p class="empty-desc">开始你的第一次深度研究</p>
          <el-button type="primary" @click="router.push('/research')">
            <i class="fas fa-plus"></i> 新建研究
          </el-button>
        </div>
      </template>

      <!-- 研究主题 -->
      <el-table-column label="研究主题" min-width="280">
        <template #default="{ row }">
          <el-tooltip :content="row.topic" placement="top" :show-after="500">
            <span class="topic-cell">{{ truncateTopic(row.topic) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>

      <!-- 类型 -->
      <el-table-column label="类型" width="90" align="center">
        <template #default="{ row }">
          <span class="task-type-tag" :class="row.task_type">
            {{ taskTypeLabel(row.task_type) }}
          </span>
        </template>
      </el-table-column>

      <!-- 状态 -->
      <el-table-column label="状态" width="120" align="center">
        <template #default="{ row }">
          <span class="status-tag" :class="row.status">
            <i :class="statusIcon(row.status)"></i>
            {{ statusLabel(row.status) }}
          </span>
        </template>
      </el-table-column>

      <!-- 来源数 -->
      <el-table-column label="来源" width="70" align="center" prop="total_sources" />

      <!-- 证据数 -->
      <el-table-column label="证据" width="70" align="center" prop="total_evidence" />

      <!-- 创建时间 -->
      <el-table-column label="创建时间" width="160" align="center">
        <template #default="{ row }">
          <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
        </template>
      </el-table-column>

      <!-- 操作 -->
      <el-table-column label="操作" width="130" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="handleView(row)">
            <i class="fas fa-eye"></i> 查看
          </el-button>
          <el-button type="danger" link size="small" @click="handleDelete(row)">
            <i class="fas fa-trash"></i> 删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- ===== 分页 ===== -->
    <div v-if="taskStore.total > 0" class="history-pagination">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="taskStore.total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElLoading, ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const taskStore = useTaskStore()

// ===== 筛选 / 分页状态 =====
const filterStatus = ref('')
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// ===== 搜索防抖（300ms） =====
let searchTimer = null
function onSearchDebounced() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadList()
  }, 300)
}

// ===== 筛选变更 → 重置到第 1 页 =====
function onFilterChange() {
  currentPage.value = 1
  loadList()
}

// ===== 分页变更 =====
function onPageChange(page) {
  currentPage.value = page
  loadList()
}

function onPageSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
  loadList()
}

// ===== 加载列表 =====
async function loadList() {
  await taskStore.fetchList({
    page: currentPage.value,
    page_size: pageSize.value,
    status: filterStatus.value || undefined,
    keyword: searchKeyword.value || undefined,
  })
}

// ===== 查看任务 → 加载详情并跳转研究页 =====
async function handleView(row) {
  try {
    await taskStore.fetchDetail(row.task_id)
    router.push('/research')
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '加载任务详情失败')
  }
}

// ===== 删除任务 =====
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除研究「${truncateTopic(row.topic)}」吗？删除后不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }

  const loading = ElLoading.service({
    lock: true,
    text: '正在删除...',
    background: 'rgba(0, 0, 0, 0.7)',
  })
  try {
    await taskStore.deleteTask(row.task_id)
    ElMessage.success('删除成功')

    // 删除当前页最后一条且不在第 1 页 → 自动回退
    if (taskStore.taskList.length === 0 && currentPage.value > 1) {
      currentPage.value--
      await loadList()
    }
  } catch (err) {
    const status = err.response?.status
    if (status === 403) {
      ElMessage.error('无权限执行此操作')
    } else {
      ElMessage.error(err.response?.data?.message || '删除失败')
    }
  } finally {
    loading.close()
  }
}

// ===== 辅助函数 =====
function truncateTopic(topic) {
  if (!topic) return ''
  return topic.length > 40 ? topic.slice(0, 40) + '...' : topic
}

function taskTypeLabel(type) {
  const map = { comparison: '对比', explainer: '解释', analysis: '影响' }
  return map[type] || type || '--'
}

function statusLabel(status) {
  const map = {
    pending: '排队中',
    running: '运行中',
    completed: '已完成',
    partially_completed: '部分完成',
    failed: '失败',
    canceled: '已取消',
  }
  return map[status] || status || '--'
}

function statusIcon(status) {
  const map = {
    pending: 'fas fa-clock',
    running: 'fas fa-spinner fa-spin',
    completed: 'fas fa-circle-check',
    partially_completed: 'fas fa-triangle-exclamation',
    failed: 'fas fa-times-circle',
    canceled: 'fas fa-ban',
  }
  return map[status] || 'fas fa-question-circle'
}

// ===== 挂载时加载 =====
onMounted(() => {
  loadList()
})
</script>

<style scoped>
/* ===== 工具栏 ===== */
.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--rm-space-5);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--rm-space-3);
}

.search-input {
  width: 240px;
}

/* ===== 表格 ===== */
.topic-cell {
  color: var(--rm-text-primary);
}

.time-cell {
  font-size: var(--rm-text-xs);
  color: var(--rm-text-secondary);
}

/* ===== 任务类型标签 ===== */
.task-type-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--rm-radius-xs);
  font-size: var(--rm-text-2xs);
  font-weight: var(--rm-weight-semibold);
}

.task-type-tag.comparison {
  background: var(--rm-secondary-light);
  color: var(--rm-secondary);
}

.task-type-tag.explainer {
  background: var(--rm-success-light);
  color: var(--rm-success);
}

.task-type-tag.analysis {
  background: var(--rm-accent-light);
  color: var(--rm-accent);
}

/* ===== 状态标签 ===== */
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--rm-radius-xs);
  font-size: var(--rm-text-2xs);
  font-weight: var(--rm-weight-semibold);
  white-space: nowrap;
}

.status-tag.pending {
  background: var(--rm-secondary-light);
  color: var(--rm-secondary);
}

.status-tag.running {
  background: var(--rm-secondary-light);
  color: var(--rm-secondary);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.status-tag.completed {
  background: var(--rm-success-light);
  color: var(--rm-success);
}

.status-tag.partially_completed {
  background: var(--rm-warning-light);
  color: var(--rm-warning);
}

.status-tag.failed {
  background: var(--rm-danger-light);
  color: var(--rm-danger);
}

.status-tag.canceled {
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
}

/* ===== 空状态 ===== */
.empty-state {
  padding: var(--rm-space-12) var(--rm-space-5);
  text-align: center;
}

.empty-icon {
  font-size: 48px;
  color: var(--rm-text-tertiary);
  margin-bottom: var(--rm-space-4);
  opacity: 0.5;
}

.empty-title {
  font-size: var(--rm-text-base);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-1) 0;
}

.empty-desc {
  font-size: var(--rm-text-sm);
  color: var(--rm-text-secondary);
  margin: 0 0 var(--rm-space-4) 0;
}

/* ===== 分页 ===== */
.history-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--rm-space-5);
}
</style>
