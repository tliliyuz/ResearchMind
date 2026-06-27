/**
 * 通用格式化工具函数
 *
 * 来源：DocMind `frontend/src/utils/format.js`，直接复制。
 * ResearchMind 新增：formatNumber() / formatDuration()。
 */

/**
 * 格式化 ISO 日期字符串为 `YYYY-MM-DD HH:mm`
 * @param {string|null|undefined} isoString
 * @returns {string}
 */
export function formatDateTime(isoString) {
  if (!isoString) return '--'
  const d = new Date(isoString)
  if (isNaN(d.getTime())) return '--'
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 别名：formatDate → formatDateTime
 * 供 FRONTEND.md 中引用的函数名
 */
export const formatDate = formatDateTime

/**
 * 格式化文件大小为可读字符串（B / KB / MB / GB）
 * @param {number|null|undefined} bytes
 * @returns {string}
 */
export function formatBytes(bytes) {
  if (bytes == null) return '--'
  const num = Number(bytes)
  if (num === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(num) / Math.log(1024)), units.length - 1)
  return (num / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

/**
 * 格式化 ISO 时间字符串为相对时间描述
 * @param {string|null|undefined} isoString
 * @returns {string}
 */
export function formatRelativeTime(isoString) {
  if (!isoString) return '从未活跃'
  const d = new Date(isoString)
  if (isNaN(d.getTime())) return '--'
  const now = Date.now()
  const diffMs = now - d.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 60) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffHour < 24) return `${diffHour} 小时前`
  if (diffDay < 7) return `${diffDay} 天前`
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 格式化数字为千分位
 * @param {number} n
 * @returns {string}
 */
export function formatNumber(n) {
  if (n == null) return '--'
  return Number(n).toLocaleString('zh-CN')
}

/**
 * 格式化毫秒耗时为可读字符串
 * @param {number} ms - 毫秒数
 * @returns {string}
 */
export function formatDuration(ms) {
  if (ms == null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const remainSec = Math.round(seconds % 60)
  return `${minutes}m${remainSec}s`
}

/**
 * 格式化已用时间为计时器字符串
 * - < 1 小时：MM:SS
 * - ≥ 1 小时：HH:MM:SS
 * @param {number} ms - 毫秒数
 * @returns {string}
 */
export function formatElapsedTime(ms) {
  if (ms == null || ms < 0) return '00:00'
  const totalSeconds = Math.floor(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const pad = (n) => String(n).padStart(2, '0')
  if (hours > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  }
  return `${pad(minutes)}:${pad(seconds)}`
}
