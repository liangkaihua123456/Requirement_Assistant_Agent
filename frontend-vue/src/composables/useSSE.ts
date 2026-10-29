import { ref, onUnmounted } from 'vue'
import type { SSEEvent } from '@/types'

export function useSSE(getTaskId: () => string | null) {
  const lastEvent = ref<SSEEvent | null>(null)
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    const taskId = getTaskId()
    if (!taskId) return
    if (eventSource && eventSource.readyState !== EventSource.CLOSED) return
    disconnect()

    const url = `/api/tasks/${taskId}/stream`
    eventSource = new EventSource(url)
    isConnected.value = true
    error.value = null

    eventSource.onmessage = (e) => {
      try {
        const parsed: SSEEvent = JSON.parse(e.data)
        lastEvent.value = parsed
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
      eventSource?.close()
      // auto-reconnect after 3s
      reconnectTimer = setTimeout(() => connect(), 3000)
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
