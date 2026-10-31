// Pydantic-aligned type definitions for the Multi-Agent System

export interface UserStory {
  role: string
  action: string
  benefit: string
}

export interface FeatureModule {
  name: string
  description: string
  priority: 'P0' | 'P1' | 'P2'
  sub_features: string[]
}

export interface UserFlow {
  name: string
  steps: string[]
}

export interface NonFunctionalRequirement {
  category: string
  description: string
  metric: string
}

export interface PRDDocument {
  product_name: string
  positioning: string
  user_stories: UserStory[]
  feature_modules: FeatureModule[]
  user_flows: UserFlow[]
  non_functional_requirements: NonFunctionalRequirement[]
  success_metrics: string[]
  out_of_scope: string[]
}

export interface ClarifiedRequirement {
  summary: string
  open_questions: string[]
}

export interface ServiceComponent {
  name: string
  responsibility: string
  tech_stack: string[]
}

export interface DBTable {
  table_name: string
  description: string
  columns: Array<{ name: string; type: string; nullable: string; description: string }>
  indexes: string[]
  related_features: string[]
}

export interface DBSchema {
  database_type: string
  tables: DBTable[]
  relationships: string[]
}

export interface APIEndpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  description: string
  request_body: string
  response_body: string
  auth_required: boolean
  related_features: string[]
}

export interface TechRisk {
  risk: string
  impact: 'high' | 'medium' | 'low'
  mitigation: string
}

export interface CodeScaffold {
  directory_structure: string[]
  key_files: Array<{ path: string; purpose: string; skeleton: string }>
  dependencies: string[]
}

export interface TechnicalDesign {
  architecture_overview: string
  architecture_style: string
  services: ServiceComponent[]
  db_schema: DBSchema
  api_endpoints: APIEndpoint[]
  tech_risks: TechRisk[]
  code_scaffold: CodeScaffold
}

export type ReviewTargetType = 'solution' | 'engineer' | 'none'

export interface ReviewIssue {
  category: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  description: string
  suggestion: string
  target: ReviewTargetType
}

export interface ReviewResult {
  overall_score: number
  prd_score: number
  tech_score: number
  issues: ReviewIssue[]
  suggestions: string[]
  passed: boolean
  reflow_target: ReviewTargetType
  summary: string
}

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_human'
  | 'completed'
  | 'error'

export interface TaskStatusResponse {
  task_id: string
  status: TaskStatus
  current_node: string
  reflow_count: number
  interrupt_info: unknown
  clarified_requirement: ClarifiedRequirement | null
  user_input: string
  review_result: ReviewResult | null
  prd_doc: PRDDocument | null
  technical_design: TechnicalDesign | null
  metrics: Record<string, unknown> | null
  error_message: string | null
}

export interface CreateTaskRequest {
  user_input: string
}

export interface CreateTaskResponse {
  task_id: string
  status: string
  message: string
  task_submit_latency_ms: number | null
}

export interface FeedbackRequest {
  feedback: string
  approved?: boolean | null
}

export interface FeedbackResponse {
  task_id: string
  status: string
  current_node: string
  message: string
}

export interface TaskResult {
  task_id: string
  deliverable: {
    clarified_requirement: ClarifiedRequirement | null
    prd_doc: PRDDocument | null
    technical_design: TechnicalDesign | null
    code_scaffold: CodeScaffold | null
    review_result: ReviewResult | null
  }
  exported_files: Record<string, string>
}

export interface TaskListItem {
  task_id: string
  user_input: string
  status: TaskStatus
}

// SSE event types
export type SSEEventType =
  | 'node_start'
  | 'token'
  | 'node_end'
  | 'interrupt'
  | 'done'
  | 'error'
  | 'heartbeat'

export interface SSEEvent {
  type: SSEEventType
  node?: string
  content?: string
  data?: unknown
  status?: string
  message?: string
}

// ===== Auth / User types (JWT) =====
export interface User {
  id: number
  username: string
  email: string | null
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface RegisterRequest {
  username: string
  password: string
  email?: string | null
}

export interface ForgotPasswordResponse {
  message: string
  reset_token?: string
}
