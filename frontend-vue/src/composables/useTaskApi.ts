import { http as api } from '@/composables/useAuth'
import type {
  CreateTaskResponse,
  TaskStatusResponse,
  FeedbackRequest,
  FeedbackResponse,
  TaskResult,
  TaskListItem,
} from '@/types'

export function useTaskApi() {
  async function createTask(userInput: string): Promise<CreateTaskResponse> {
    const { data } = await api.post<CreateTaskResponse>('/tasks', {
      user_input: userInput,
    })
    return data
  }

  async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
    const { data } = await api.get<TaskStatusResponse>(`/tasks/${taskId}`)
    return data
  }

  async function submitFeedback(
    taskId: string,
    payload: FeedbackRequest
  ): Promise<FeedbackResponse> {
    const { data } = await api.post<FeedbackResponse>(
      `/tasks/${taskId}/feedback`,
      payload
    )
    return data
  }

  async function getTaskResult(taskId: string): Promise<TaskResult> {
    const { data } = await api.get<TaskResult>(`/tasks/${taskId}/result`)
    return data
  }

  async function listTasks(limit = 50, offset = 0): Promise<TaskListItem[]> {
    const { data } = await api.get<TaskListItem[]>('/tasks', {
      params: { limit, offset },
    })
    return data
  }

  return { createTask, getTaskStatus, submitFeedback, getTaskResult, listTasks }
}
