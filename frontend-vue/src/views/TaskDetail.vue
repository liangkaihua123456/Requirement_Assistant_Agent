<script setup lang="ts">
import { ref, watch, onMounted, computed, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, FileText, BarChart3, Braces, GitBranch, Sparkles } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import { useSSE } from '@/composables/useSSE'
import { useTaskStore } from '@/stores/task'
import TaskProgress from '@/components/TaskProgress.vue'
import ExecutionProfile from '@/components/ExecutionProfile.vue'
import TraceabilityMatrix from '@/components/TraceabilityMatrix.vue'
import ReviewResult from '@/components/ReviewResult.vue'
import PrdPreview from '@/components/PrdPreview.vue'
import TechDesignPreview from '@/components/TechDesignPreview.vue'
import ClarificationPanel from '@/components/ClarificationPanel.vue'
import ApprovalPanel from '@/components/ApprovalPanel.vue'
import DeliverableView from '@/components/DeliverableView.vue'

const route = useRoute()
const router = useRouter()
const { getTaskStatus, reoptimizeTask, retryTask, cancelTask, deleteTask } = useTaskApi()
const store = useTaskStore()

const taskId = computed(() => (route.params.id as string) || store.taskId || '')
const manualLoading = ref(false)
const busy = ref(false)
const autoRefresh = ref(true)
const lastUpdated = ref('')
const reoptimizing = ref(false)
const retrying = ref(false)
const cancelling = ref(false)
const removing = ref(false)

const canCancel = computed(() =>
  ['queued', 'running', 'waiting_human'].includes(store.taskStatus || '')
)
const canDelete = computed(() =>
  ['completed', 'error', 'cancelled'].includes(store.taskStatus || '')
)

async function handleCancelTask() {
  try {
    await ElMessageBox.confirm(
      '取消后当前节点会执行完毕再停止，已生成的产物会保留。',
      '取消任务',
      { type: 'warning', confirmButtonText: '取消任务', cancelButtonText: '返回' }
    )
  } catch {
    return
  }
  cancelling.value = true
  try {
    await cancelTask(taskId.value)
    ElMessage.success('已请求取消')
    await queryStatus({ manual: true })
  } catch {
    ElMessage.error('取消失败')
  } finally {
    cancelling.value = false
  }
}

async function handleDeleteTask() {
  try {
    await ElMessageBox.confirm(
      '删除后任务记录、checkpoint 与导出文件都会移除，无法恢复。',
      '删除任务',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '返回' }
    )
  } catch {
    return
  }
  removing.value = true
  try {
    await deleteTask(taskId.value)
    ElMessage.success('已删除')
    router.push({ name: 'history' })
  } catch {
    ElMessage.error('删除失败')
  } finally {
    removing.value = false
  }
}
const activeTab = ref('products')
const CODE_KIND_LABELS: Record<string, string> = {
  spec: '接口文档',
  ddl: '数据库脚本',
  backend: '后端代码',
  frontend: '前端代码',
  doc: '说明文档',
}
const codeArtifacts = computed(() => store.statusData?.code_artifacts ?? null)
const codeGroups = computed(() => {
  const files = codeArtifacts.value?.files ?? []
  return ['spec', 'ddl', 'backend', 'frontend', 'doc']
    .map((kind) => ({
      kind,
      label: CODE_KIND_LABELS[kind] ?? kind,
      files: files.filter((file) => file.kind === kind),
    }))
    .filter((group) => group.files.length > 0)
})

const { lastEvent, connect: connectSSE, disconnect: disconnectSSE } = useSSE(taskId.value)
let statusPollTimer: ReturnType<typeof setTimeout> | null = null

function stopStatusPoll() {
  if (statusPollTimer) {
    clearTimeout(statusPollTimer)
    statusPollTimer = null
  }
}

// 运行中 3s、终态 10s：终态也要刷新，便于同步其他入口触发的重跑或审批。
function scheduleNextPoll() {
  stopStatusPoll()
  if (!autoRefresh.value) return
  const running = ['queued', 'running'].includes(store.taskStatus || '')
  statusPollTimer = setTimeout(async () => {
    await queryStatus()
    scheduleNextPoll()
  }, running ? 3000 : 10000)
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    void queryStatus()
    scheduleNextPoll()
  } else {
    stopStatusPoll()
  }
}

onMounted(() => {
  if (taskId.value) { store.setTaskId(taskId.value); queryStatus() }
})
onUnmounted(() => {
  disconnectSSE()
  stopStatusPoll()
})

watch(lastEvent, (event) => {
  if (event && (event.type === 'node_end' || event.type === 'done' || event.type === 'interrupt' || event.type === 'error' || event.type === 'node_start' || event.type === 'heartbeat')) {
    queryStatus()
  }
})

watch(() => route.params.id, (id) => {
  if (id && typeof id === 'string') { store.setTaskId(id); queryStatus() }
})

async function queryStatus(options: { manual?: boolean } = {}) {
  const id = taskId.value
  if (!id || busy.value) return
  busy.value = true
  if (options.manual) manualLoading.value = true
  try {
    const data = await getTaskStatus(id)
    store.setStatusData(data)
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (data.status !== 'queued') connectSSE()
    scheduleNextPoll()
  } catch {
    if (options.manual) ElMessage.error('查询失败')
  } finally {
    busy.value = false
    manualLoading.value = false
  }
}

function onFeedbackSubmitted() { queryStatus() }

function hasContent(value: unknown) {
  return !!value && typeof value === 'object' && Object.keys(value as object).length > 0
}

const hasProducts = computed(() => hasContent(store.statusData?.prd_doc) || hasContent(store.statusData?.technical_design))
const hasReview = computed(() => store.statusData?.review_result && Object.keys(store.statusData.review_result).length > 0)
const interruptText = computed(() => JSON.stringify(store.statusData?.interrupt_info ?? ''))
const needsClarification = computed(() => {
  if (store.taskStatus !== 'waiting_human') return false
  if (interruptText.value.includes("'type': 'approval'") || interruptText.value.includes('"type": "approval"')) return false
  const questions = store.statusData?.clarified_requirement?.open_questions
  return Array.isArray(questions) && questions.length > 0
})
const needsApproval = computed(() => {
  if (store.taskStatus !== 'waiting_human' || needsClarification.value) return false
  return hasContent(store.statusData?.review_result)
})

const canReoptimize = computed(() => {
  const review = store.statusData?.review_result
  return !!review && review.passed === false && store.taskStatus !== 'running'
})

const canRetry = computed(() => store.taskStatus === 'error')

async function handleRetry() {
  try {
    await ElMessageBox.confirm(
      '将从失败节点继续执行，已完成的阶段不会重跑。',
      '重试任务',
      { type: 'info', confirmButtonText: '开始重试', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  retrying.value = true
  try {
    await retryTask(taskId.value)
    ElMessage.success('已重新入队')
    await queryStatus({ manual: true })
  } catch {
    ElMessage.error('重试失败，请确认任务状态为「执行失败」')
  } finally {
    retrying.value = false
  }
}

async function handleReoptimize() {
  try {
    await ElMessageBox.confirm(
      '将基于当前 PRD 重新执行工程实现与评审，生成一个新任务。原任务保留不变。',
      '二次优化',
      { type: 'info', confirmButtonText: '开始优化', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  reoptimizing.value = true
  try {
    const result = await reoptimizeTask(taskId.value)
    ElMessage.success('已创建优化任务')
    await router.push({ name: 'detail', params: { id: result.task_id } })
  } catch {
    ElMessage.error('创建失败，请确认该任务已产出 PRD')
  } finally {
    reoptimizing.value = false
  }
}
</script>

<template>
  <div class="animate-in">
    <div class="page-header">
      <div>
        <div class="agent-kicker">Agent Task</div>
        <h1>任务详情</h1>
        <p class="task-id-label">{{ taskId }}</p>
      </div>
      <div class="header-actions">
        <button
          v-if="canCancel"
          class="btn-secondary cancel-btn"
          :disabled="cancelling"
          @click="handleCancelTask"
        >
          {{ cancelling ? '取消中' : '取消任务' }}
        </button>
        <button
          v-if="canDelete"
          class="btn-secondary delete-btn"
          :disabled="removing"
          @click="handleDeleteTask"
        >
          {{ removing ? '删除中' : '删除任务' }}
        </button>
        <button
          v-if="canRetry"
          class="btn-secondary retry-btn"
          :disabled="retrying"
          @click="handleRetry"
        >
          <RefreshCw :size="14" :class="{ spinning: retrying }" />
          {{ retrying ? '重启中' : '重试任务' }}
        </button>
        <button
          v-if="canReoptimize"
          class="btn-secondary reoptimize-btn"
          :disabled="reoptimizing"
          @click="handleReoptimize"
        >
          <RefreshCw v-if="reoptimizing" :size="14" class="spinning" />
          <Sparkles v-else :size="14" />
          {{ reoptimizing ? '创建中' : '二次优化' }}
        </button>
        <button
          class="btn-secondary refresh-btn"
          :class="{ on: autoRefresh }"
          :title="autoRefresh ? '点击暂停自动刷新' : '点击开启自动刷新'"
          @click="toggleAutoRefresh"
        >
          <RefreshCw :size="14" :class="{ spinning: autoRefresh && busy }" />
          {{ autoRefresh ? '自动刷新' : '已暂停' }}
        </button>
        <span v-if="lastUpdated" class="refresh-time">更新于 {{ lastUpdated }}</span>
      </div>
    </div>

    <div v-if="store.statusData">
      <TaskProgress :data="store.statusData" />
      <ExecutionProfile :data="store.statusData" />

      <ClarificationPanel
        v-if="needsClarification"
        :task-id="taskId"
        :clarified-requirement="store.statusData.clarified_requirement"
        @feedback-submitted="onFeedbackSubmitted"
      />

      <ApprovalPanel
        v-if="needsApproval"
        :task-id="taskId"
        @feedback-submitted="onFeedbackSubmitted"
      />

      <!-- Tabs -->
      <div class="tabs-bar">
        <button :class="['tab', { active: activeTab === 'products' }]" @click="activeTab = 'products'">
          <FileText :size="14" /> 交付产物
        </button>
        <button
          :class="['tab', { active: activeTab === 'trace' }]"
          @click="activeTab = 'trace'"
          :disabled="!hasProducts"
        >
          <GitBranch :size="14" /> 追溯矩阵
        </button>
        <button
          :class="['tab', { active: activeTab === 'code' }]"
          @click="activeTab = 'code'"
        >
          <Braces :size="14" /> 代码产物
          <span v-if="codeArtifacts?.enabled" class="tab-badge">{{ codeArtifacts.file_count }}</span>
        </button>
        <button :class="['tab', { active: activeTab === 'review' }]" @click="activeTab = 'review'" :disabled="!hasReview">
          <BarChart3 :size="14" /> 评审分析
        </button>
        <button :class="['tab', { active: activeTab === 'raw' }]" @click="activeTab = 'raw'">
          <Braces :size="14" /> 原始数据
        </button>
      </div>

      <div v-if="activeTab === 'products'">
        <DeliverableView v-if="store.taskStatus === 'completed'" :task-id="taskId" />
        <PrdPreview v-if="hasContent(store.statusData.prd_doc)" :prd="store.statusData.prd_doc!" />
        <TechDesignPreview v-if="hasContent(store.statusData.technical_design)" :design="store.statusData.technical_design!" />
        <div v-if="!hasProducts && store.taskStatus === 'error'" class="empty-block">任务已失败，没有可展示的交付产物。</div>
        <div v-else-if="!hasProducts && store.taskStatus !== 'completed'" class="empty-block">产物生成中...</div>
      </div>

      <div v-if="activeTab === 'trace'">
        <TraceabilityMatrix :task-id="taskId" :active="activeTab === 'trace'" />
      </div>

      <div v-if="activeTab === 'code'">
        <div v-if="!codeArtifacts?.enabled" class="empty-block">
          <p>本任务未生成代码产物。</p>
          <p class="empty-hint">创建任务时在「代码产物」下拉里选择目标语言，即可额外产出 OpenAPI 文档、建表 SQL、后端骨架与前端页面。</p>
        </div>
        <div v-else class="code-panel">
          <div class="code-summary">
            <span class="code-lang">{{ codeArtifacts.language_label }}</span>
            <span>{{ codeArtifacts.file_count }} 个文件</span>
            <span>{{ codeArtifacts.endpoints }} 个接口</span>
            <span>{{ codeArtifacts.tables }} 张表</span>
            <span class="code-export-hint">可在导出 ZIP 中获取完整代码</span>
          </div>
          <div class="code-groups">
            <section v-for="group in codeGroups" :key="group.kind" class="code-group">
              <h4>{{ group.label }} <em>{{ group.files.length }}</em></h4>
              <ul>
                <li v-for="file in group.files" :key="file.path">
                  <code>{{ file.path }}</code>
                  <span>{{ (file.bytes / 1024).toFixed(1) }} KB</span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'review'">
        <ReviewResult v-if="hasReview" :review="store.statusData.review_result!" />
        <div v-else class="empty-block">暂无评审结果</div>
      </div>

      <div v-if="activeTab === 'raw'" class="raw-block">
        <pre>{{ JSON.stringify(store.statusData, null, 2) }}</pre>
      </div>
    </div>

    <div v-else-if="!manualLoading" class="empty-center">
      <p>输入任务 ID 查看详情</p>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.page-header h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 2px; }
.task-id-label { font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); }

.btn-secondary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  border-radius: var(--radius-sm);
  height: 32px;
}
.btn-secondary:hover { border-color: var(--text-muted); color: var(--text-primary); }
.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  font-family: var(--font-sans);
  cursor: pointer;
}
.refresh-btn:disabled { opacity: 0.6; cursor: wait; }
.refresh-btn.on { border-color: var(--accent); color: var(--accent); background: var(--accent-subtle); }
.refresh-time { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.reoptimize-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  color: var(--accent);
  border-color: var(--accent-subtle);
  background: var(--accent-subtle);
  font-family: var(--font-sans);
  cursor: pointer;
}
.reoptimize-btn:hover { border-color: var(--accent); }
.reoptimize-btn:disabled { opacity: 0.6; cursor: wait; }
.retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  color: var(--danger);
  border-color: var(--danger-subtle);
  background: var(--danger-subtle);
  font-family: var(--font-sans);
  cursor: pointer;
}
.retry-btn:hover { border-color: var(--danger); }
.retry-btn:disabled { opacity: 0.6; cursor: wait; }
.cancel-btn { color: var(--warning); border-color: var(--warning-subtle); background: var(--warning-subtle); }
.cancel-btn:hover { border-color: var(--warning); }
.delete-btn { color: var(--danger); border-color: var(--danger-subtle); background: var(--danger-subtle); }
.delete-btn:hover { border-color: var(--danger); }
.spinning { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Tabs ────────────────────────────────── */
.tabs-bar {
  display: flex; gap: 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 18px;
}
.tab {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  background: none; border: none; border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  font-size: 13px; font-weight: 500; font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-bottom: -1px;
}
.tab:hover:not(:disabled) { color: var(--text-primary); }
.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.tab:disabled { opacity: 0.3; cursor: not-allowed; }

.empty-block {
  padding: 40px 0; text-align: center; color: var(--text-muted); font-size: 13px;
}
.empty-center {
  padding: 80px 0; text-align: center; color: var(--text-muted);
}
.raw-block {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
}
.raw-block pre {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  max-height: 500px;
  overflow-y: auto;
  background: transparent;
  border: none;
  padding: 0;
}

.tab-badge {
  margin-left: 5px;
  padding: 0 5px;
  border-radius: 8px;
  font-size: 10px;
  background: var(--accent-subtle);
  color: var(--accent);
}
.empty-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}
.code-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  padding: 16px;
}
.code-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-secondary);
}
.code-lang {
  padding: 2px 9px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-subtle);
}
.code-export-hint { margin-left: auto; color: var(--text-muted); font-size: 11px; }
.code-groups { display: grid; gap: 16px; }
.code-group h4 {
  font-size: 12px;
  font-weight: 650;
  margin-bottom: 6px;
  color: var(--text-primary);
}
.code-group h4 em {
  font-style: normal;
  font-size: 10px;
  color: var(--text-muted);
  margin-left: 4px;
}
.code-group ul { display: grid; gap: 3px; }
.code-group li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
  font-size: 11.5px;
  color: var(--text-secondary);
}
.code-group code { font-family: var(--font-mono); color: var(--text-primary); }
.code-group li span { color: var(--text-muted); white-space: nowrap; }
</style>
