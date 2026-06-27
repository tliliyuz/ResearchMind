<template>
  <div class="failed-card">
    <div class="card-body">
      <div class="card-content">
        <div class="failed-icon">
          <i class="fas fa-times-circle"></i>
        </div>

        <h2 class="failed-title">研究执行失败</h2>
        <p class="failed-message">{{ primaryMessage }}</p>

        <div v-if="errorDetail" class="failed-detail">
          <span class="detail-label">详细原因</span>
          <p class="detail-text">{{ errorDetail }}</p>
        </div>

        <div class="failed-meta">
          <span v-if="standardErrorCode" class="failed-error-code">{{ standardErrorCode }}</span>
          <span v-if="failedPhase" class="failed-phase">失败阶段：{{ phaseLabel(failedPhase) }}</span>
        </div>

        <div class="retry-section">
          <button
            v-if="recoverable"
            class="retry-btn"
            disabled
            title="断点续跑功能将在后续版本开放"
          >
            <i class="fas fa-sync-alt"></i>
            断点续跑
          </button>
          <p v-else class="failed-hint">
            该错误无法恢复，请尝试修改研究主题后重新提交
          </p>
        </div>
      </div>
    </div>

    <div class="card-footer">
      <button class="back-btn" @click="$emit('back')">
        <i class="fas fa-arrow-left"></i>
        返回新建研究
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { normalizePhaseKey, PHASE_LABELS } from '@/utils/phase'

const props = defineProps({
  errorCode: { type: String, default: null },
  errorMessage: { type: String, default: '' },
  failedPhase: { type: String, default: null },
  recoverable: { type: Boolean, default: false },
})

defineEmits(['back'])

/**
 * 标准错误码：仅展示 E 系列码（如 E3110）。
 * 异常类名等不是标准码，会下沉到 detail 区域展示。
 */
const standardErrorCode = computed(() => {
  const raw = props.errorCode
  if (raw && /^E\d{4}$/.test(raw)) return raw

  // 尝试从 errorMessage 中解析标准错误码
  return extractErrorCode(props.errorMessage)
})

/**
 * 主错误消息：提取最可读的那一行/字段。
 */
const primaryMessage = computed(() => {
  const raw = props.errorMessage || '未知错误'
  const { primary } = parseErrorMessage(raw)
  return primary
})

/**
 * 详细原因：当消息包含多行、异常类名或非标准 errorCode 时，展示为次要信息。
 */
const errorDetail = computed(() => {
  const raw = props.errorMessage || ''
  const { detail } = parseErrorMessage(raw)

  const extras = []
  if (detail) extras.push(detail)

  // errorCode 不是标准 E 码时（如异常类名），作为详细原因展示
  const code = props.errorCode
  if (code && !/^E\d{4}$/.test(code) && !detail.includes(code)) {
    extras.push(code)
  }

  return extras.join('\n')
})

/**
 * 从字符串中提取标准 E 系列错误码。
 */
function extractErrorCode(raw) {
  if (typeof raw !== 'string') return null
  const m = raw.match(/["']code["']\s*:\s*["'](E\d{4})["']/)
  if (m) return m[1]
  const free = raw.match(/\bE\d{4}\b/)
  return free ? free[0] : null
}

/**
 * 解析错误消息，分离出主要可读文本与详细原因。
 * 会清理 HTTP 前缀、JSON 包装、多余空行。
 */
function parseErrorMessage(raw) {
  if (typeof raw !== 'string') {
    return { primary: String(raw), detail: '' }
  }

  // 去掉前导 HTTP 状态前缀（如 "500: " / "500："）
  let cleaned = raw.replace(/^\d{3}\s*[:：]\s*/, '').trim()

  // 优先用正则提取最外层 JSON 中的可读字段
  const messageMatch = cleaned.match(/["']message["']\s*:\s*["']([^"']+)["']/)
  const descMatch = cleaned.match(/["']error_description["']\s*:\s*["']([^"']+)["']/)
  const extracted = (messageMatch?.[1] || descMatch?.[1] || '').trim()
  if (extracted) {
    // 如果提取出的字段本身包含换行或异常类名，继续拆分
    return splitPrimaryDetail(extracted)
  }

  // 兜底：尝试解析标准 JSON
  const braceIdx = cleaned.indexOf('{')
  if (braceIdx !== -1) {
    try {
      const parsed = JSON.parse(cleaned.slice(braceIdx))
      const candidate =
        parsed.message ||
        parsed.error_description ||
        parsed.detail?.message ||
        parsed.detail?.error_description ||
        ''
      if (candidate) {
        return splitPrimaryDetail(String(candidate).trim())
      }
    } catch {
      // 无法解析，继续走原始字符串兜底
    }
  }

  return splitPrimaryDetail(cleaned)
}

/**
 * 把字符串拆分为「主要可读消息」和「详细补充」。
 * 第一行非空内容作为主要消息；其余行作为详细原因。
 */
function splitPrimaryDetail(text) {
  const lines = text
    .split(/\r?\n/)
    .map(l => l.trim())
    .filter(l => l.length > 0)

  if (lines.length === 0) return { primary: text.trim(), detail: '' }
  if (lines.length === 1) return { primary: lines[0], detail: '' }

  const primary = lines[0]
  const detail = lines.slice(1).join('\n')
  return { primary, detail }
}

function phaseLabel(phase) {
  const short = normalizePhaseKey(phase)
  return short ? PHASE_LABELS[short] : phase
}
</script>

<style scoped>
.failed-card {
  width: 560px;
  max-width: calc(100% - var(--rm-space-8));
  min-height: 520px;
  max-height: 720px;
  background: var(--rm-bg-card);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-xl);
  box-shadow: var(--rm-shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: var(--rm-space-8) var(--rm-space-8) 0;
  overflow-y: auto;
  min-height: 0;
}

.card-content {
  width: 100%;
  text-align: center;
}

.card-footer {
  flex-shrink: 0;
  padding: var(--rm-space-6) var(--rm-space-8) var(--rm-space-8);
  text-align: center;
}

.failed-icon {
  width: 72px;
  height: 72px;
  background: var(--rm-danger-light);
  color: var(--rm-danger);
  border-radius: var(--rm-radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto var(--rm-space-5);
  font-size: 28px;
}

.failed-title {
  font-size: var(--rm-text-2xl);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-3) 0;
}

.failed-message {
  font-size: var(--rm-text-lg);
  font-weight: var(--rm-weight-medium);
  color: var(--rm-text-primary);
  margin: 0 0 var(--rm-space-4) 0;
  line-height: var(--rm-leading-relaxed);
  word-break: break-word;
}

.failed-detail {
  background: var(--rm-bg-page);
  border: 1px solid var(--rm-border-light);
  border-radius: var(--rm-radius-md);
  padding: var(--rm-space-3) var(--rm-space-4);
  margin-bottom: var(--rm-space-5);
  text-align: left;
}

.detail-label {
  display: block;
  font-size: var(--rm-text-2xs);
  font-weight: var(--rm-weight-semibold);
  color: var(--rm-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--rm-space-1);
}

.detail-text {
  font-family: var(--rm-font-mono);
  font-size: var(--rm-text-xs);
  color: var(--rm-text-secondary);
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

.failed-meta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--rm-space-3);
  margin-bottom: var(--rm-space-6);
  flex-wrap: wrap;
}

.failed-error-code {
  background: var(--rm-danger-light);
  color: #BE123C;
  font-family: var(--rm-font-mono);
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-semibold);
  padding: 3px 8px;
  border-radius: var(--rm-radius-xs);
  display: inline-block;
}

.failed-phase {
  font-size: var(--rm-text-sm);
  color: var(--rm-text-tertiary);
}

.retry-section {
  margin-bottom: var(--rm-space-5);
}

.retry-btn {
  height: 40px;
  padding: 0 24px;
  background: var(--rm-primary-light);
  color: var(--rm-primary);
  border: none;
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-body);
  font-weight: var(--rm-weight-medium);
  cursor: not-allowed;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  opacity: 0.6;
  font-family: inherit;
}

.failed-hint {
  font-size: var(--rm-text-sm);
  color: var(--rm-text-tertiary);
  margin: 0;
}

.back-btn {
  height: 40px;
  padding: 0 24px;
  background: var(--rm-bg-elevated);
  color: var(--rm-text-secondary);
  border: 1px solid var(--rm-border);
  border-radius: var(--rm-radius-sm);
  font-size: var(--rm-text-body);
  font-weight: var(--rm-weight-medium);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--rm-space-1_5);
  transition: all var(--rm-transition-fast);
  font-family: inherit;
}

.back-btn:hover {
  background: var(--rm-border-light);
}
</style>
