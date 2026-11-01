import { ref, onUnmounted } from 'vue'
import { getAccessToken } from '@/composables/useAuth'
import type { SSEEvent } from '@/types'

export function useSSE(taskId: string | null) {
  const lastEvent = ref<SSEEvent | null>(null)
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const MAX_RECONNECTS = 3

  function connect() {
    if (!taskId) return
    // 已有存活连接直接复用：此前每次状态查询都重建连接，导致服务端
    // 每 5 秒（heartbeat）一对 disconnect/重建，进度事件还会丢
    if (eventSource && eventSource.readyState !== EventSource.CLOSED) return
    disconnect()

    const token = getAccessToken()
    const url = `/api/tasks/${taskId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    eventSource = new EventSource(url)
    isConnected.value = true
    error.value = null

    eventSource.onmessage = (e) => {
      try {
        const parsed: SSEEvent = JSON.parse(e.data)
        lastEvent.value = parsed
        reconnectAttempts = 0 // 有消息即视为连接健康，重置退避
        if (parsed.type === 'error') {
          error.value = parsed.message || 'Unknown error'
        }
        if (parsed.type === 'done') {
          disconnect()
        }
      } catch {
        // ignore malformed events
      }
    }

    eventSource.onerror = () => {
      isConnected.value = false
      // readyState=CLOSED 表示永久失败（HTTP 401/404 等致命错误）。
      // 此前无条件 3s 重连会在任务被删/token 过期时对后端打重连风暴
      // （uvicorn 每 3 秒刷一对日志），必须终止并提示，而不是继续重试。
      if (!eventSource || eventSource.readyState === EventSource.CLOSED) {
        eventSource = null
        error.value = '实时流连接被拒绝（登录过期或任务不存在），请刷新页面'
        return
      }
      if (reconnectAttempts >= MAX_RECONNECTS) {
        eventSource.close()
        eventSource = null
        error.value = '实时流多次重试失败，请刷新页面重试'
        return
      }
      reconnectAttempts += 1
      eventSource.close()
      eventSource = null
      // transient failure: back off before retrying
      reconnectTimer = setTimeout(() => connect(), 3000 * reconnectAttempts)
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    eventSource?.close()
    eventSource = null
    isConnected.value = false
  }

  onUnmounted(() => disconnect())

  return { lastEvent, isConnected, error, connect, disconnect }
}
