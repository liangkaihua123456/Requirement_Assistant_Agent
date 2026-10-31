<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Activity, CheckCircle2, ChevronRight, CircleAlert, Clock3, Inbox, Plus, RefreshCw, Search, Sparkles } from '@lucide/vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskApi } from '@/composables/useTaskApi'
import { useTaskStore } from '@/stores/task'
import type { TaskListItem, TaskStats } from '@/types'
import { formatTokens } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const { listTasksPage, getTaskStats, cancelTask, deleteTask } = useTaskApi()
const store = useTaskStore()

const tasks = ref<TaskListItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const stats = ref<TaskStats | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = 10
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const filters = ['all', 'queued', 'running', 'waiting_human', 'completed', 'error']

function resolveStatus(value: unknown) {
  return typeof value === 'string' && filters.includes(value) ? value : 'all'
}

const statusFilter = ref(resolveStatus(route.query.status))

watch(
  () => route.query.status,
  (value) => {
    statusFilter.value = resolveStatus(value)
  }
)
const filterLabels: Record<string, string> = {
  all: '全部', queued: '排队中', running: '执行中', waiting_human: '待处理', completed: '已完成', error: '失败',
}

const statusConfig: Record<string, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'tag-info' },
  running: { label: '执行中', cls: 'tag-warning' },
  waiting_human: { label: '待处理', cls: 'tag-warning' },
  cancelling: { label: '取消中', cls: 'tag-warning' },
  cancelled: { label: '已取消', cls: 'tag-info' },
  completed: { label: '已完成', cls: 'tag-success' },
  error: { label: '失败', cls: 'tag-danger' },
}

const filteredTasks = computed(() => tasks.value)

const selected = ref<string[]>([])

const comparison = computed(() => {
  if (selected.value.length !== 2) return null
  const [first, second] = selected.value.map(id => tasks.value.find(t => t.task_id === id))
  return first && second ? { first, second } : null
})

function toggleSelect(id: string) {
  const index = selected.value.indexOf(id)
  if (index >= 0) {
    selected.value.splice(index, 1)
    return
  }
  if (selected.value.length >= 2) selected.value.shift()
  selected.value.push(id)
}

function formatSeconds(value?: number | null) {
  if (value == null) return '-'
  return value >= 10 ? value.toFixed(0) + 's' : value.toFixed(1) + 's'
}

// Tasks recorded before the duration fix carry only the last graph invocation,
// which is impossible to reconcile with several LLM calls. Show them as unknown.
function isLegacyDuration(task: TaskListItem) {
  return task.duration_seconds != null && task.duration_seconds < 5 && (task.llm_calls ?? 0) > 3
}

function toPercent(value?: number | null) {
  return value == null ? null : Number(value) * 100
}

interface CompareRow {
  label: string
  a: string
  b: string
  delta: string
  tone: 'good' | 'bad' | 'neutral'
}

function buildRow(
  label: string,
  a?: number | null,
  b?: number | null,
  unit = '',
  better: 'low' | 'high' = 'high',
  decimals = 1,
): CompareRow {
  if (a == null || b == null) return { label, a: '-', b: '-', delta: '', tone: 'neutral' }
  const diff = Number(b) - Number(a)
  const tone: CompareRow['tone'] =
    diff === 0 ? 'neutral' : better === 'low' ? (diff < 0 ? 'good' : 'bad') : (diff > 0 ? 'good' : 'bad')
  const sign = diff > 0 ? '+' : ''
  return {
    label,
    a: `${Number(a).toFixed(decimals)}${unit}`,
    b: `${Number(b).toFixed(decimals)}${unit}`,
    delta: diff === 0 ? '持平' : `${sign}${diff.toFixed(decimals)}${unit}`,
    tone,
  }
}

function tokenRow(): CompareRow {
  const a = comparison.value?.first.total_tokens
  const b = comparison.value?.second.total_tokens
  if (a == null || b == null) {
    return { label: 'Token 用量', a: '-', b: '-', delta: '', tone: 'neutral' }
  }
  const diff = Number(b) - Number(a)
  return {
    label: 'Token 用量',
    a: formatTokens(a),
    b: formatTokens(b),
    delta: diff === 0 ? '持平' : `${diff > 0 ? '+' : '-'}${formatTokens(Math.abs(diff))}`,
    tone: diff === 0 ? 'neutral' : diff < 0 ? 'good' : 'bad',
  }
}

const compareRows = computed<CompareRow[]>(() => {
  if (!comparison.value) return []
  const { first, second } = comparison.value
  return [
    buildRow('耗时', first.duration_seconds, second.duration_seconds, 's', 'low'),
    buildRow('综合评分', first.overall_score, second.overall_score, '', 'high'),
    buildRow('LLM 调用', first.llm_calls, second.llm_calls, '', 'low', 0),
    tokenRow(),
    buildRow('API 覆盖', toPercent(first.api_coverage), toPercent(second.api_coverage), '%', 'high', 0),
    buildRow('数据表覆盖', toPercent(first.db_coverage), toPercent(second.db_coverage), '%', 'high', 0),
  ]
})

const summaryCards = computed(() => [
  { label: '全部任务', value: stats.value?.total ?? 0, icon: Activity, tone: 'blue' },
  { label: '执行中', value: stats.value?.running ?? 0, icon: Clock3, tone: 'amber' },
  { label: '已完成', value: stats.value?.completed ?? 0, icon: CheckCircle2, tone: 'green' },
  { label: '需要关注', value: (stats.value?.error ?? 0) + (stats.value?.waiting_human ?? 0), icon: CircleAlert, tone: 'red' },
])

onMounted(refresh)

async function refresh() {
  loading.value = true
  try {
    const [data, counts] = await Promise.all([
      listTasksPage({
        limit: pageSize,
        offset: (page.value - 1) * pageSize,
        status: statusFilter.value,
        q: searchQuery.value.trim(),
      }),
      getTaskStats(),
    ])
    tasks.value = data.items
    total.value = data.total
    stats.value = counts
    selected.value = []
  } catch {
    tasks.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function setStatus(next: string) {
  if (statusFilter.value === next) return
  statusFilter.value = next
}

function goPage(next: number) {
  const target = Math.min(Math.max(1, next), totalPages.value)
  if (target === page.value) return
  page.value = target
  refresh()
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchQuery, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    refresh()
  }, 300)
})

watch(statusFilter, () => {
  page.value = 1
  refresh()
})

function viewTask(id: string) {
  store.setTaskId(id)
  router.push({ name: 'detail', params: { id } })
}

async function handleCancel(task: TaskListItem) {
  try {
    await ElMessageBox.confirm(
      `取消任务 ${task.task_id}？执行中的任务会在当前节点结束后停止。`,
      '取消任务',
      { type: 'warning', confirmButtonText: '取消任务', cancelButtonText: '返回' }
    )
  } catch {
    return
  }
  try {
    await cancelTask(task.task_id)
    ElMessage.success('已请求取消')
    await refresh()
  } catch {
    ElMessage.error('取消失败')
  }
}

async function handleDelete(task: TaskListItem) {
  try {
    await ElMessageBox.confirm(
      `删除任务 ${task.task_id}？记录、checkpoint 与导出文件都会移除，无法恢复。`,
      '删除任务',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '返回' }
    )
  } catch {
    return
  }
  try {
    await deleteTask(task.task_id)
    ElMessage.success('已删除')
    await refresh()
  } catch {
    ElMessage.error('删除失败，请先取消运行中的任务')
  }
}
</script>

<template>
  <div class="history-page animate-in">
    <div class="page-header">
      <div>
        <div class="eyebrow"><Sparkles :size="13" /> Agent Tasks</div>
        <h1>历史任务</h1>
        <p>浏览和管理所有需求交付任务</p>
      </div>
      <div class="header-actions">
        <el-button class="btn-secondary" :loading="loading" @click="refresh"><RefreshCw :size="14" /> 刷新</el-button>
        <el-button class="btn-primary" @click="router.push({ name: 'create' })"><Plus :size="14" /> 新建任务</el-button>
      </div>
    </div>

    <div class="summary-grid">
      <div v-for="item in summaryCards" :key="item.label" :class="['summary-card', 'card', `tone-${item.tone}`]">
        <span class="summary-icon"><component :is="item.icon" :size="17" /></span>
        <div><strong>{{ item.value }}</strong><span>{{ item.label }}</span></div>
      </div>
    </div>

    <div class="content-card card">
      <div class="toolbar">
        <div class="search-box">
          <Search :size="15" />
          <input v-model="searchQuery" class="search-input" placeholder="搜索任务 ID 或需求描述..." />
        </div>
        <div class="result-count">共 {{ total }} 条结果</div>
      </div>
      <div class="filter-row">
        <button
          v-for="f in filters" :key="f"
          :class="['filter-btn', { active: statusFilter === f }]"
          @click="setStatus(f)"
        >{{ filterLabels[f] }}</button>
      </div>

      <div v-if="comparison" class="compare-panel">
        <div class="compare-head">
          <span class="compare-title">任务对比</span>
          <span class="compare-ids">
            <code>{{ comparison.first.task_id }}</code>
            <span class="compare-arrow">→</span>
            <code>{{ comparison.second.task_id }}</code>
          </span>
          <button class="compare-clear" @click="selected = []">清空</button>
        </div>
        <div class="compare-table">
          <div v-for="row in compareRows" :key="row.label" class="compare-row">
            <span class="compare-label">{{ row.label }}</span>
            <span class="compare-values">{{ row.a }} → {{ row.b }}</span>
            <span :class="['compare-delta', row.tone]">{{ row.delta || '-' }}</span>
          </div>
        </div>
        <p class="compare-hint">差值以右侧任务相对左侧计算；耗时与调用数越低越好。</p>
      </div>

      <div v-if="filteredTasks.length" class="list">
        <div v-for="task in filteredTasks" :key="task.task_id" class="list-row" @click="viewTask(task.task_id)">
          <label class="select-box" @click.stop>
            <input
              type="checkbox"
              :checked="selected.includes(task.task_id)"
              @change="toggleSelect(task.task_id)"
            />
          </label>
          <span class="task-icon"><Inbox :size="17" /></span>
          <div class="list-body">
            <span class="list-text">{{ task.user_input }}</span>
            <span class="list-id">ID · {{ task.task_id }}</span>
          </div>
          <div class="row-metrics" @click.stop>
            <span v-if="task.duration_seconds != null" class="metric" :title="isLegacyDuration(task) ? '早期版本只记录了最后一次调用的耗时，无法还原总耗时' : ''">
              {{ isLegacyDuration(task) ? '—' : formatSeconds(task.duration_seconds) }}
            </span>
            <span v-if="task.overall_score != null" class="metric">{{ Number(task.overall_score).toFixed(1) }} 分</span>
            <span v-if="task.llm_calls != null" class="metric">{{ task.llm_calls }} 调用</span>
            <span v-if="task.total_tokens != null" class="metric">{{ formatTokens(task.total_tokens) }} tok</span>
          </div>
          <span :class="['list-tag', statusConfig[task.status]?.cls || 'tag-info']">
            {{ statusConfig[task.status]?.label || task.status }}
          </span>
          <div class="row-actions" @click.stop>
            <button
              v-if="['queued', 'running', 'waiting_human', 'cancelling'].includes(task.status)"
              class="row-action"
              @click="handleCancel(task)"
            >取消</button>
            <button v-else class="row-action danger" @click="handleDelete(task)">删除</button>
          </div>
          <ChevronRight :size="17" class="row-arrow" />
        </div>
      </div>

      <div v-else-if="!loading" class="empty-center">
        <Inbox :size="34" />
        <h3>暂无匹配任务</h3>
        <p>调整筛选条件，或创建一个新的交付任务。</p>
        <el-button class="btn-primary" size="small" @click="router.push({ name: 'create' })">创建任务</el-button>
      </div>

      <div v-if="total > pageSize" class="pager">
        <button class="pager-btn" :disabled="page === 1 || loading" @click="goPage(page - 1)">上一页</button>
        <span class="pager-info">{{ page }} / {{ totalPages }}</span>
        <button class="pager-btn" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 26px;
}
.page-header h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 4px; }
.page-header p { font-size: 14px; color: var(--text-secondary); }
.eyebrow { display: flex; align-items: center; gap: 6px; margin-bottom: 7px; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.header-actions { display: flex; gap: 8px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 14px 0 4px; }
.pager-btn {
  height: 30px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 12px; cursor: pointer;
}
.pager-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.pager-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pager-info { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.row-actions { display: flex; gap: 6px; margin-left: 10px; }
.row-action {
  height: 24px; padding: 0 8px;
  border: 1px solid var(--border); border-radius: 5px;
  background: var(--bg-card); color: var(--text-muted);
  font-size: 11px; cursor: pointer;
}
.row-action:hover { border-color: var(--accent); color: var(--accent); }
.row-action.danger:hover { border-color: var(--danger); color: var(--danger); }

.btn-secondary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  gap: 6px; border-radius: 8px; height: 36px;
}
.btn-secondary:hover { border-color: var(--text-muted); color: var(--text-primary); }

.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.summary-card { display: flex; align-items: center; gap: 12px; padding: 16px 18px; }
.summary-icon { display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 11px; color: var(--accent); background: var(--accent-subtle); }
.summary-card strong { display: block; font-size: 21px; line-height: 1.1; color: var(--text-primary); }
.summary-card span:last-child { font-size: 11px; color: var(--text-muted); }
.tone-green .summary-icon { color: var(--success); background: var(--success-subtle); }
.tone-amber .summary-icon { color: var(--warning); background: var(--warning-subtle); }
.tone-red .summary-icon { color: var(--danger); background: var(--danger-subtle); }
.content-card { overflow: hidden; }
.toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 20px 12px;
}
.search-box {
  display: flex; align-items: center;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 0 12px;
  flex: 1; max-width: 420px;
  color: var(--text-muted);
}
.search-input {
  width: 100%;
  height: 38px;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 13px;
  font-family: var(--font-sans);
  outline: none;
}
.search-input::placeholder { color: var(--text-placeholder); }
.result-count { font-size: 11px; color: var(--text-muted); }
.filter-row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 0 20px 16px; border-bottom: 1px solid var(--border-light); }
.filter-btn {
  padding: 5px 10px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 11px; font-weight: 500; font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.filter-btn:hover { border-color: var(--text-muted); color: var(--text-primary); }
.filter-btn.active {
  background: var(--accent-subtle); border-color: var(--accent); color: var(--accent);
}

/* ── Compare ─────────────────────────────── */
.compare-panel {
  margin: 16px 20px 0;
  border: 1px solid var(--border);
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
}
.compare-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.compare-title { font-size: 12px; font-weight: 700; color: var(--accent); }
.compare-ids { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.compare-ids code {
  font-family: var(--font-mono); font-size: 11px; color: var(--text-primary);
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px;
}
.compare-arrow { font-size: 11px; color: var(--text-muted); }
.compare-clear {
  background: transparent; border: none; color: var(--text-secondary);
  font-size: 11px; cursor: pointer; padding: 2px 4px;
}
.compare-clear:hover { color: var(--danger); }
.compare-table { display: flex; flex-direction: column; gap: 4px; }
.compare-row {
  display: grid; grid-template-columns: 88px 1fr 90px; align-items: center; gap: 10px;
  font-size: 12px; background: var(--bg-card); border-radius: 4px; padding: 5px 8px;
}
.compare-label { color: var(--text-secondary); }
.compare-values { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); }
.compare-delta { font-family: var(--font-mono); font-size: 11px; font-weight: 600; text-align: right; }
.compare-delta.good { color: var(--success); }
.compare-delta.bad { color: var(--danger); }
.compare-delta.neutral { color: var(--text-muted); }
.compare-hint { font-size: 10px; color: var(--text-muted); margin-top: 8px; }

.select-box { display: flex; align-items: center; margin-right: 10px; }
.select-box input { width: 14px; height: 14px; accent-color: var(--accent); cursor: pointer; }
.row-metrics { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.metric { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); white-space: nowrap; }

.list { display: flex; flex-direction: column; }
.list-row {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 76px; padding: 13px 20px; border-bottom: 1px solid var(--border-light); cursor: pointer;
  transition: background var(--transition-fast);
}
.list-row:last-child { border-bottom: 0; }
.list-row:hover { background: var(--bg-card-hover); }
.task-icon { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; margin-right: 12px; flex-shrink: 0; border-radius: 10px; color: var(--text-muted); background: var(--bg-overlay); }
.list-body { flex: 1; overflow: hidden; }
.list-text {
  font-size: 13px; font-weight: 500;
  display: block;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  margin-bottom: 4px;
}
.list-id { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.list-tag {
  font-size: 11px; font-weight: 600; padding: 2px 8px;
  border-radius: 6px; flex-shrink: 0; margin-left: 12px;
}
.row-arrow { margin-left: 12px; color: var(--text-placeholder); }
.list-row:hover .row-arrow { color: var(--accent); transform: translateX(2px); }

/* ── Tags ─────────────────────────────────── */
.tag-info    { background: var(--info-subtle); color: var(--info); }
.tag-warning { background: var(--warning-subtle); color: var(--warning); }
.tag-success { background: var(--success-subtle); color: var(--success); }
.tag-danger  { background: var(--danger-subtle); color: var(--danger); }

.btn-primary {
  background: var(--accent-dark);
  border: 1px solid var(--accent-dark);
  color: #fff;
  font-weight: 600;
  font-size: 12px;
  display: inline-flex; gap: 6px; border-radius: 8px; height: 36px;
}
.empty-center { padding: 72px 0; text-align: center; color: var(--text-muted); }
.empty-center > svg { margin-bottom: 10px; color: var(--text-placeholder); }
.empty-center h3 { color: var(--text-primary); font-size: 15px; }
.empty-center p { margin: 4px 0 16px; font-size: 12px; }

@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .page-header { gap: 14px; } .page-header h1 { font-size: 24px; } .summary-grid { grid-template-columns: 1fr 1fr; } .summary-card { padding: 13px; } .header-actions .btn-secondary { display: none; } .toolbar { align-items: stretch; flex-direction: column; } .search-box { max-width: none; } .result-count { display: none; } }
</style>
