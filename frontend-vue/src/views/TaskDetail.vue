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

const { lastEvent, connect: connectSSE, disconnect: disconnectSSE } = useSSE(taskId.value)
let statusPollTimer: ReturnType<typeof setInterval> | null = null

function stopStatusPoll() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

function startStatusPoll() {
  if (statusPollTimer) return
  // 长 LLM 调用期间 SSE 可能长时间无 node_end；轮询 current_node 避免页面卡在「排队中」。
  statusPollTimer = setInterval(() => {
    if (['queued', 'running'].includes(store.taskStatus || '')) {
      queryStatus()
    } else {
      stopStatusPoll()
    }
  }, 3000)
}

onMounted(() => {
  if (taskId.value) { store.setTaskId(taskId.value); queryStatus() }
})
onUnmounted(() => {
  disconnectSSE()
  stopStatusPoll()
})

watch(lastEvent, (event) => {
  // done 不再触发查询：终态状态由 queryStatus 自身刷新，再查会重新开流形成环
  if (event && ['node_end', 'interrupt', 'error', 'node_start', 'heartbeat'].includes(event.type)) {
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
    // 仅在"进行中"开进度流；终态/待人工不开并主动关闭残余连接。
    // 对终态任务开流会秒回 done 关流，而 watch 收到 done 又触发
    // queryStatus → connectSSE，形成每秒一对请求的自环风暴。
    if (['completed', 'error', 'cancelled', 'waiting_human'].includes(data.status)) {
      disconnectSSE()
    } else {
      connectSSE()
    }
    if (['queued', 'running'].includes(data.status)) startStatusPoll()
    else stopStatusPoll()
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
  // 带需求变更的迭代对"已通过评审"任务同样开放（v2 场景）；是否放行由后端校验
  const review = store.statusData?.review_result
  return !!review && !['running', 'queued'].includes(store.taskStatus || '')
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

const reoptDialog = ref(false)
const reoptBrief = ref('')
const reoptKeepBaseline = ref(true)

function openReoptimizeDialog() {
  reoptBrief.value = ''
  reoptKeepBaseline.value = true
  reoptDialog.value = true
}

async function handleReoptimize() {
  reoptimizing.value = true
  try {
    const result = await reoptimizeTask(taskId.value, reoptBrief.value || undefined, reoptKeepBaseline.value)
    ElMessage.success(result.brief_applied ? '已按新需求创建迭代任务，将重做 PRD 与方案设计' : '已创建优化任务')
    reoptDialog.value = false
    await router.push({ name: 'detail', params: { id: result.task_id } })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败，请确认该任务已产出 PRD')
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
          @click="openReoptimizeDialog"
        >
          <RefreshCw v-if="reoptimizing" :size="14" class="spinning" />
          <Sparkles v-else :size="14" />
          {{ reoptimizing ? '创建中' : '二次优化' }}
        </button>
        <button
          class="btn-secondary refresh-btn"
          :disabled="manualLoading"
          @click="queryStatus({ manual: true })"
        >
          <RefreshCw :size="14" :class="{ spinning: manualLoading }" />
          {{ manualLoading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="store.statusData">
      <div
        v-if="store.statusData.source_task_id || store.statusData.project_history"
        class="history-card"
      >
        <p class="history-title">
          迭代历史
          <el-tag v-if="store.statusData.source_task_id" size="small" type="info">
            源任务 {{ store.statusData.source_task_id }}
          </el-tag>
        </p>
        <pre v-if="store.statusData.project_history" class="history-body">{{ store.statusData.project_history }}</pre>
      </div>
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
    <el-dialog
      v-model="reoptDialog"
      title="二次优化 · 重新讲需求（可选）"
      width="560px"
      :close-on-click-modal="false"
    >
      <p style="margin:0 0 10px;font-size:13px;color:#666;line-height:1.6">
        留空：沿用现有 PRD 直接重跑工程实现与评审。<br />
        填写：视为需求变更，新任务将从规划开始<b>重做 PRD、方案设计与工程实现</b>；
        原任务及其产物保持不变，仅作来源引用。
      </p>
      <el-input
        v-model="reoptBrief"
        type="textarea"
        :rows="6"
        maxlength="4000"
        show-word-limit
        placeholder="例如：新增优惠券发放与核销功能；支付需支持花呗分期；库存扣减改为预占模式……"
      />
      <el-checkbox v-model="reoptKeepBaseline" :disabled="!reoptBrief.trim()" style="margin-top:8px">
        保留原需求作为基线（取消勾选则完全以新描述为准）
      </el-checkbox>
      <template #footer>
        <el-button @click="reoptDialog = false">取消</el-button>
        <el-button type="primary" :loading="reoptimizing" @click="handleReoptimize">
          {{ reoptBrief.trim() ? '按新需求迭代' : '开始优化' }}
        </el-button>
      </template>
    </el-dialog>
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
.history-card { margin: 0 0 12px; padding: 10px 12px; border: 1px solid var(--border, #ddd); border-radius: 8px; background: rgba(0,0,0,0.02); }
.history-title { margin: 0 0 6px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.history-body { margin: 0; font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-all; max-height: 220px; overflow-y: auto; font-family: inherit; }
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
</style>
