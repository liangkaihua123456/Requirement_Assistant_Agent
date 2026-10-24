import axios from 'axios'
import type {
  CreateTaskResponse,
  TaskStatusResponse,
  FeedbackRequest,
  FeedbackResponse,
  TaskResult,
  TaskListItem,
  TaskPage,
  TaskStats,
  TraceabilityResponse,
  UsageStatsResponse,
  RoutingConfigResponse,
  RoutingTestResult,
  RoleRoutingUpdate,
  RequirementTemplate,
  PreflightResult,
  ExtractedRequirement,
  ExtractStatus,
} from '@/types'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

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

  async function getTraceability(taskId: string): Promise<TraceabilityResponse> {
    const { data } = await api.get<TraceabilityResponse>(`/tasks/${taskId}/traceability`)
    return data
  }

  async function getUsageStats(days = 30): Promise<UsageStatsResponse> {
    const { data } = await api.get<UsageStatsResponse>('/stats/usage', { params: { days } })
    return data
  }

  async function getRoutingConfig(): Promise<RoutingConfigResponse> {
    const { data } = await api.get<RoutingConfigResponse>('/settings/routing')
    return data
  }

  async function saveRoutingConfig(roles: RoleRoutingUpdate[]): Promise<void> {
    await api.put('/settings/routing', { roles })
  }

  async function testRouting(role: string): Promise<RoutingTestResult> {
    const { data } = await api.post<RoutingTestResult>('/settings/routing/test', { role })
    return data
  }

  async function reoptimizeTask(taskId: string): Promise<{ task_id: string }> {
    const { data } = await api.post<{ task_id: string }>(`/tasks/${taskId}/reoptimize`)
    return data
  }

  async function retryTask(taskId: string): Promise<{ task_id: string }> {
    const { data } = await api.post<{ task_id: string }>(`/tasks/${taskId}/retry`)
    return data
  }

  async function cancelTask(taskId: string): Promise<{ status: string }> {
    const { data } = await api.post<{ status: string }>(`/tasks/${taskId}/cancel`)
    return data
  }

  async function deleteTask(taskId: string): Promise<{ deleted: string }> {
    const { data } = await api.delete<{ deleted: string }>(`/tasks/${taskId}`)
    return data
  }

  function exportUrl(taskId: string, kind: 'zip' | 'docx'): string {
    return `/api/tasks/${taskId}/export/${kind}`
  }

  async function runPreflight(): Promise<PreflightResult> {
    const { data } = await api.post<PreflightResult>('/settings/preflight')
    return data
  }

  async function listTemplates(): Promise<RequirementTemplate[]> {
    const { data } = await api.get<RequirementTemplate[]>('/templates')
    return data
  }

  async function createTemplate(name: string, content: string): Promise<RequirementTemplate> {
    const { data } = await api.post<RequirementTemplate>('/templates', { name, content })
    return data
  }

  async function deleteTemplate(id: number): Promise<void> {
    await api.delete(`/templates/${id}`)
  }

  async function getExtractStatus(): Promise<ExtractStatus> {
    const { data } = await api.get<ExtractStatus>('/extract/status')
    return data
  }

  async function extractImage(file: File): Promise<ExtractedRequirement> {
    const form = new FormData()
    form.append('file', file, file.name || 'requirement.png')
    const { data } = await api.post<ExtractedRequirement>('/extract/image', form, {
      // 视觉模型 60s + 本地 OCR 30s，留出网络余量
      timeout: 120000,
    })
    return data
  }

  async function listTasks(limit = 50, offset = 0): Promise<TaskListItem[]> {
    const { data } = await api.get<TaskListItem[]>('/tasks', {
      params: { limit, offset },
    })
    return data
  }

  async function listTasksPage(params: {
    limit?: number
    offset?: number
    status?: string
    q?: string
  }): Promise<TaskPage> {
    const { data } = await api.get<TaskPage>('/tasks/page', { params })
    return data
  }

  async function getTaskStats(): Promise<TaskStats> {
    const { data } = await api.get<TaskStats>('/tasks/stats')
    return data
  }

  return {
    createTask,
    getTaskStatus,
    submitFeedback,
    getTaskResult,
    listTasks,
    listTasksPage,
    getTaskStats,
    getTraceability,
    getUsageStats,
    getRoutingConfig,
    saveRoutingConfig,
    testRouting,
    reoptimizeTask,
    retryTask,
    cancelTask,
    deleteTask,
    exportUrl,
    runPreflight,
    listTemplates,
    createTemplate,
    deleteTemplate,
    getExtractStatus,
    extractImage,
  }
}
