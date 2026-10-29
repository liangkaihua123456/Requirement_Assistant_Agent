<script setup lang="ts">
import { ref, watch, onMounted, computed, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshCw, FileText, BarChart3, Braces } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import { useSSE } from '@/composables/useSSE'
import { useTaskStore } from '@/stores/task'
import TaskProgress from '@/components/TaskProgress.vue'
import ReviewResult from '@/components/ReviewResult.vue'
import PrdPreview from '@/components/PrdPreview.vue'
import TechDesignPreview from '@/components/TechDesignPreview.vue'
import ClarificationPanel from '@/components/ClarificationPanel.vue'
import ApprovalPanel from '@/components/ApprovalPanel.vue'
import DeliverableView from '@/components/DeliverableView.vue'

const route = useRoute()
const { getTaskStatus } = useTaskApi()
const store = useTaskStore()

const taskId = computed(() => (route.params.id as string) || store.taskId || '')
const loading = ref(false)
const activeTab = ref('products')

const { lastEvent, connect: connectSSE, disconnect: disconnectSSE } = useSSE(() => taskId.value)

onMounted(() => {
  if (taskId.value) { store.setTaskId(taskId.value); queryStatus() }
})
onUnmounted(() => disconnectSSE())

watch(lastEvent, (event) => {
  if (event && (event.type === 'node_end' || event.type === 'done' || event.type === 'interrupt' || event.type === 'error')) {
    queryStatus()
  }
})

watch(() => route.params.id, (id) => {
  if (id && typeof id === 'string') { store.setTaskId(id); queryStatus() }
})

async function queryStatus() {
  const id = taskId.value
  if (!id) return
  loading.value = true
  try {
    const data = await getTaskStatus(id)
    store.setStatusData(data)
    if (data.status === 'running' || data.status === 'queued') connectSSE()
    else disconnectSSE()
  } catch { ElMessage.error('查询失败') }
  finally { loading.value = false }
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
</script>

<template>
  <div class="animate-in">
    <div class="page-header">
      <div>
        <div class="agent-kicker">Agent Task</div>
        <h1>任务详情</h1>
        <p class="task-id-label">{{ taskId }}</p>
      </div>
      <el-button class="btn-secondary" :loading="loading" @click="queryStatus">
        <RefreshCw :size="14" style="margin-right: 5px" /> 刷新
      </el-button>
    </div>

    <div v-if="store.statusData">
      <TaskProgress :data="store.statusData" />

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
        <button :class="['tab', { active: activeTab === 'review' }]" @click="activeTab = 'review'" :disabled="!hasReview">
          <BarChart3 :size="14" /> 评审分析
        </button>
        <button :class="['tab', { active: activeTab === 'raw' }]" @click="activeTab = 'raw'">
          <Braces :size="14" /> 原始数据
        </button>
      </div>

      <div v-if="activeTab === 'products'">
        <PrdPreview v-if="hasContent(store.statusData.prd_doc)" :prd="store.statusData.prd_doc!" />
        <TechDesignPreview v-if="hasContent(store.statusData.technical_design)" :design="store.statusData.technical_design!" />
        <DeliverableView v-if="store.taskStatus === 'completed'" :task-id="taskId" />
        <div v-if="!hasProducts && store.taskStatus === 'error'" class="empty-block">任务已失败，没有可展示的交付产物。</div>
        <div v-else-if="!hasProducts && store.taskStatus !== 'completed'" class="empty-block">产物生成中...</div>
      </div>

      <div v-if="activeTab === 'review'">
        <ReviewResult v-if="hasReview" :review="store.statusData.review_result!" />
        <div v-else class="empty-block">暂无评审结果</div>
      </div>

      <div v-if="activeTab === 'raw'" class="raw-block">
        <pre>{{ JSON.stringify(store.statusData, null, 2) }}</pre>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-center">
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
