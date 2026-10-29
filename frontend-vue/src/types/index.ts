// Pydantic-aligned type definitions for the Multi-Agent System

export interface UserStory {
  role: string
  action: string
  benefit: string
}

export interface FeatureModule {
  feature_id?: string
  name: string
  description: string
  priority: 'P0' | 'P1' | 'P2'
  sub_features: string[]
  acceptance_criteria?: string[]
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
  related_feature_ids?: string[]
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
  related_feature_ids?: string[]
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
  _degraded?: boolean
}

export type ReviewTargetType = 'solution' | 'engineer' | 'none'

export interface RequirementTemplate {
  id: number
  name: string
  content: string
  created_at: string
}

export interface PreflightResult {
  ok: boolean
  results: Array<{
    role: string
    ok: boolean
    model: string
    elapsed_seconds: number
    error?: string
  }>
  failed_roles: string[]
}

export interface TaskPage {
  items: TaskListItem[]
  total: number
}

export interface TaskStats {
  total: number
  by_status: Record<string, number>
  completed: number
  running: number
  queued: number
  waiting_human: number
  error: number
}

export interface ReviewIssue {
  category: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  description: string
  suggestion: string
  target: ReviewTargetType
  origin?: 'new' | 'carried'
}

export interface ReviewResult {
  overall_score: number
  prd_score: number
  tech_score: number
  completeness_score?: number
  consistency_score?: number
  feasibility_score?: number
  security_score?: number
  testability_score?: number
  issues: ReviewIssue[]
  issue_reviews?: Array<{ description: string; resolved: boolean }>
  suggestions: string[]
  passed: boolean
  reflow_target: ReviewTargetType
  summary: string
}

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_human'
  | 'cancelling'
  | 'cancelled'
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

export interface TraceabilityApiItem {
  method: string
  path: string
  description: string
  related_feature_ids: string[]
}

export interface TraceabilityTableItem {
  table_name: string
  description: string
  column_count: number
  related_feature_ids: string[]
}

export interface TraceabilityServiceItem {
  name: string
  responsibility: string
}

export interface TraceabilityCell<T> {
  weight: number
  items: T[]
}

export interface TraceabilityFeature {
  feature_id: string
  name: string
  priority: string
  acceptance_criteria: string[]
  service: TraceabilityCell<TraceabilityServiceItem>
  api: TraceabilityCell<TraceabilityApiItem>
  db: TraceabilityCell<TraceabilityTableItem>
}

export interface TraceabilityResponse {
  task_id: string
  features: TraceabilityFeature[]
  summary: {
    feature_count: number
    api_score: number
    db_score: number
    prd_tech_score: number
    missing_api: string[]
    missing_db: string[]
  }
}

export interface UsageSummary {
  requests: number
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
  cache_miss_tokens: number
  cache_write_tokens: number
  cost_cny: number
  cache_hit_rate: number
  priced: boolean
  peak_calls: number
  off_peak_calls: number
  currency?: string
}

export interface UsageSeriesPoint {
  date: string
  input: number
  cache_miss: number
  output: number
  cached: number
  cost: number
  requests: number
  calls: number
}

export interface UsageBucket {
  key: string
  label: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
  cache_miss_tokens: number
  calls: number
  cost_cny: number
}

export interface UsageRequestRow {
  task_id: string
  created_at: string
  user_input: string
  status: string
  models: string
  sources?: string
  calls?: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
  cost_cny: number
  duration_seconds?: number | null
}

export interface UsagePriceRow {
  model: string
  input: number
  cached_input: number
  output: number
  currency: string
}

export interface UsageStatsResponse {
  days: number
  summary: UsageSummary
  series: UsageSeriesPoint[]
  by_model: UsageBucket[]
  by_role: UsageBucket[]
  by_node: UsageBucket[]
  by_source: UsageBucket[]
  requests: UsageRequestRow[]
  pricing?: UsagePriceRow[]
}

export interface RoleRoutingConfig {
  role: string
  label: string
  model: string
  api_base: string
  api_key_masked: string
  api_key_set: boolean
  max_tokens: number
  reasoning_effort: string
  effective_model: string
  effective_api_base: string
  is_override: boolean
}

export interface RoutingConfigResponse {
  routing_enabled: boolean
  fallback_enabled: boolean
  global: { model: string; api_base: string; max_tokens: number }
  roles: RoleRoutingConfig[]
}

export interface RoutingTestResult {
  ok: boolean
  model?: string
  elapsed_seconds?: number
  reply?: string
  error?: string
}

export interface RoleRoutingUpdate {
  role: string
  model: string
  api_base: string
  api_key: string
  max_tokens: number
  reasoning_effort: string
}

export interface ModelPriceRow {
  model: string
  input: number
  cached_input: number
  output: number
  currency: string
  manual: boolean
}

export interface PricingMeta {
  synced_at?: string
  source?: string
  errors?: string[]
  updated_models?: string[]
}

export interface PricingConfigResponse {
  models: ModelPriceRow[]
  meta: PricingMeta
  usd_to_cny_rate: number
}

export interface PricingSyncResult {
  prices: Record<string, { input: number; cached_input: number; output: number; currency: string }>
  meta: PricingMeta
}

export interface CostRecalcResult {
  tasks: number
  updated: number
  skipped: number
  old_cost_cny: number
  new_cost_cny: number
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
  current_node?: string
  created_at?: string
  overall_score?: number | null
  review_passed?: boolean | null
  duration_seconds?: number | null
  llm_calls?: number | null
  api_coverage?: number | null
  db_coverage?: number | null
  reflow_count?: number
  total_tokens?: number | null
  cost_cny?: number | null
}

export interface TokenUsageBucket {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens: number
  calls: number
}

export interface TokenUsageSummary {
  total: TokenUsageBucket
  by_role: Record<string, TokenUsageBucket>
  by_model: Record<string, TokenUsageBucket>
  cost_cny: number
  priced: boolean
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

// ── Image requirement extraction ──────────────
export type ExtractSource = 'vision' | 'ocr' | 'none'

export interface ExtractedRequirement {
  ok: boolean
  source: ExtractSource
  title: string
  text: string
  goal: string
  features: string[]
  constraints: string[]
  audience: string
  confidence: number
  warnings: string[]
  elapsed_ms: number
  filename?: string
  image: {
    width: number
    height: number
    bytes: number
    original_bytes: number
    format: string
  }
}

export interface ExtractStatus {
  enabled: boolean
  vision_ready: boolean
  vision_model: string
  ocr_ready: boolean
  ocr_detail: string
  preferred: ExtractSource
  limits: {
    max_bytes: number
    max_pixels: number
    long_edge: number
    vision_timeout: number
    ocr_timeout: number
  }
}

export interface ExtractApplyPayload {
  mode: 'structured' | 'free'
  goal: string
  features: string[]
  constraints: string[]
  audience: string
  text: string
}
