import api from './index'

/**
 * 创建研究任务
 * @param {string} topic - 研究主题（≤500 字符）
 * @param {object} requirements - { task_type, depth, max_sources, language }
 * @returns {Promise} response.data.data = { task_id, status, created_at }
 */
export function createTask(topic, requirements) {
  return api.post('/research', { topic, requirements })
}

/**
 * 获取当前用户的研究任务历史列表（分页，按 created_at DESC）
 * @param {object} params - { page, page_size, status, keyword }
 * @returns {Promise} response.data.data = { total, page, page_size, items }
 */
export function getTaskList(params) {
  return api.get('/research', { params })
}

/**
 * 获取单个研究任务详情
 * @param {string} taskId - 任务 UUID
 * @returns {Promise} response.data.data = ResearchTaskResponse
 */
export function getTaskDetail(taskId) {
  return api.get(`/research/${taskId}`)
}

/**
 * 删除研究任务（级联清理全部派生数据）
 * @param {string} taskId - 任务 UUID
 * @returns {Promise}
 */
export function deleteTask(taskId) {
  return api.delete(`/research/${taskId}`)
}

/**
 * 取消正在运行的研究任务
 * @param {string} taskId - 任务 UUID
 * @returns {Promise}
 */
export function cancelTask(taskId) {
  return api.post(`/research/${taskId}/cancel`)
}

/**
 * 获取任务执行状态快照（REST 版，SSE task.status.snapshot 等价物）
 * @param {string} taskId - 任务 UUID
 * @returns {Promise} response.data.data = 状态快照
 */
export function getTaskState(taskId) {
  return api.get(`/research/${taskId}/state`)
}
