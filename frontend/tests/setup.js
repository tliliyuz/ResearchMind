// 前端测试全局配置 — Mock localStorage、Element Plus、清理 DOM

import { afterEach, vi } from 'vitest'
import { cleanup } from '@vue/test-utils'

// 每个测试后清理 DOM（vue/test-utils）
afterEach(() => {
  cleanup()
})

// ── Mock localStorage ────────────────────────────────────────

const localStorageMock = (() => {
  let store = {}
  return {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => { store[key] = String(value) },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
})

// ── Mock Element Plus ────────────────────────────────────────

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  ElMessageBox: {
    confirm: vi.fn(() => Promise.resolve()),
    alert: vi.fn(() => Promise.resolve()),
  },
  ElLoading: {
    service: vi.fn(() => ({
      close: vi.fn(),
      setText: vi.fn(),
    })),
  },
}))

// ── Mock window.matchMedia (Element Plus 响应式依赖) ─────────

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// ── Mock ResizeObserver (ECharts 依赖) ───────────────────────

global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))
