/**
 * SSE 流式事件解析工具
 *
 * 使用 fetch + ReadableStream 读取 SSE 流，支持：
 * - 按 \n\n 分割事件帧，保留不完整尾部到 buffer
 * - 跳过注释帧（以 : 开头，如心跳 : ping）
 * - 解析 event: / data: 行，JSON.parse data
 * - 指数退避重连（1s/2s/4s/8s，最多 3 次）
 * - 手动关闭（abortController.abort + reader.cancel）
 *
 * 来源：DocMind SSE 解析框架 + ResearchMind 替换全部事件处理器。
 * 对齐 FRONTEND.md §8 + API.md §4。
 */

/**
 * connectSSE — 建立 SSE 连接并持续解析事件
 *
 * @param {string} url - SSE 端点 URL（如 /api/research/{task_id}/stream）
 * @param {object} options
 * @param {object} [options.headers] - 额外请求头
 * @param {function} options.onEvent - (eventName: string, data: object) => void  事件回调
 * @param {function} options.onStatusChange - (status: string) => void  连接状态变化
 *   状态：'connecting' | 'connected' | 'reconnecting' | 'error' | 'disconnected'
 * @param {function} [options.onError] - (error: Error) => void  连接/解析错误
 * @param {number} [options.maxRetries=3] - 最大重连次数
 * @param {number} [options.retryDelay=1000] - 初始重连延迟（ms），每次翻倍
 * @returns {{ close: () => void }}  调用 close() 关闭连接并阻止重连
 */
export function connectSSE(url, options) {
  const {
    headers = {},
    onEvent,
    onStatusChange,
    onError,
    maxRetries = 3,
    retryDelay = 1000,
  } = options

  let abortController = null
  let reader = null
  let shouldReconnect = true   // 用户手动 close 时设为 false
  let retryCount = 0
  let currentDelay = retryDelay

  // —— 核心连接逻辑 ——
  async function connect() {
    abortController = new AbortController()

    // 构建请求头
    const requestHeaders = { ...headers }
    const token = localStorage.getItem('access_token')
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`
    }

    try {
      if (retryCount === 0) {
        onStatusChange('connecting')
      }

      const response = await fetch(url, {
        headers: requestHeaders,
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`SSE 连接失败：HTTP ${response.status}`)
      }

      // 连接成功
      onStatusChange(retryCount > 0 ? 'reconnecting' : 'connected')
      retryCount = 0
      currentDelay = retryDelay

      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      // —— 逐块读取循环 ——
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按 \n\n 分割完整事件帧
        const parts = buffer.split('\n\n')
        // 最后一段可能不完整，保留在 buffer 中
        buffer = parts.pop()

        for (const frame of parts) {
          parseFrame(frame)
        }
      }

      // 流正常结束（未预期 —— SSE 应持续推送）
      if (shouldReconnect) {
        scheduleReconnect()
      }
    } catch (err) {
      // 手动关闭导致的 AbortError，不重连
      if (err.name === 'AbortError') {
        onStatusChange('disconnected')
        return
      }

      // 网络错误或其他异常
      if (onError) {
        onError(err)
      }

      if (shouldReconnect) {
        scheduleReconnect()
      } else {
        onStatusChange('disconnected')
      }
    }
  }

  // —— 解析单个事件帧 ——
  function parseFrame(frame) {
    if (!frame.trim()) return

    const lines = frame.split('\n')
    let eventName = ''
    const dataLines = []

    for (const line of lines) {
      // 跳过注释帧（以 : 开头）
      if (line.startsWith(':')) {
        continue
      }

      if (line.startsWith('event: ')) {
        eventName = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataLines.push(line.slice(6))
      } else if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5))
      }
    }

    if (eventName && dataLines.length > 0) {
      const dataStr = dataLines.join('\n')
      try {
        const data = JSON.parse(dataStr)
        onEvent(eventName, data)
      } catch {
        // JSON 解析失败，跳过该帧（不中断连接）
        if (onError) {
          onError(new Error(`SSE 数据解析失败：${dataStr.slice(0, 100)}`))
        }
      }
    }
  }

  // —— 重连调度（指数退避） ——
  function scheduleReconnect() {
    if (retryCount >= maxRetries) {
      onStatusChange('error')
      return
    }

    onStatusChange('reconnecting')
    setTimeout(() => {
      retryCount++
      currentDelay *= 2
      connect()
    }, currentDelay)
  }

  // —— 手动关闭 ——
  function close() {
    shouldReconnect = false
    if (abortController) {
      abortController.abort()
    }
    if (reader) {
      reader.cancel().catch(() => {})
    }
    onStatusChange('disconnected')
  }

  // 启动首次连接
  connect()

  return { close }
}
