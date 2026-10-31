<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Clock3,
  History,
  LoaderCircle,
  Plus,
  Sparkles,
} from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { TaskListItem } from '@/types'

const router = useRouter()
const { listTasks, getTaskStats } = useTaskApi()

const stats = ref({ total: 0, completed: 0, failed: 0, running: 0 })
const recentTasks = ref<TaskListItem[]>([])

const completionRate = computed(() => {
  if (!stats.value.total) return 0
  return Math.round((stats.value.completed / stats.value.total) * 100)
})

const statCards = computed(() => [
  { label: '总任务', value: stats.value.total, tone: 'blue', icon: Activity, note: '累计创建', target: { name: 'history' } },
  { label: '已完成', value: stats.value.completed, tone: 'green', icon: CheckCircle2, note: `完成率 ${completionRate.value}%`, target: { name: 'history', query: { status: 'completed' } } },
  { label: '执行中', value: stats.value.running, tone: 'amber', icon: LoaderCircle, note: '实时处理中', target: { name: 'history', query: { status: 'running' } } },
  { label: '未达标', value: stats.value.failed, tone: 'red', icon: CircleAlert, note: '建议优先处理', target: { name: 'history', query: { status: 'error' } } },
])

onMounted(async () => {
  try {
    const [counts, tasks] = await Promise.all([getTaskStats(), listTasks(6)])
    stats.value = {
      total: counts.total,
      completed: counts.completed,
      failed: counts.error,
      running: counts.running,
    }
    recentTasks.value = tasks
  } catch { /* backend may be busy */ }
})

const statusMeta: Record<string, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'tag-info' },
  running: { label: '执行中', cls: 'tag-warning' },
  waiting_human: { label: '待处理', cls: 'tag-warning' },
  cancelling: { label: '取消中', cls: 'tag-warning' },
  cancelled: { label: '已取消', cls: 'tag-info' },
  completed: { label: '已完成', cls: 'tag-success' },
  error: { label: '失败', cls: 'tag-danger' },
}
</script>

<template>
  <div class="dashboard animate-in">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="eyebrow"><Sparkles :size="13" /> Agent Workspace</div>
        <h1>仪表盘</h1>
        <p>多智能体需求交付系统运行概览</p>
      </div>
      <el-button class="btn-primary" @click="router.push({ name: 'create' })">
        <Plus :size="15" /> 创建任务
      </el-button>
    </div>

    <!-- Stats Row -->
    <div class="stats-row">
      <div
        v-for="s in statCards"
        :key="s.label"
        :class="['stat-box', 'card', 'clickable', `tone-${s.tone}`]"
        role="button"
        tabindex="0"
        @click="router.push(s.target)"
        @keydown.enter="router.push(s.target)"
      >
        <div class="stat-top">
          <span class="stat-label">{{ s.label }}</span>
          <span class="stat-icon"><component :is="s.icon" :size="18" /></span>
        </div>
        <span class="stat-num">{{ s.value }}</span>
        <span class="stat-note">{{ s.note }}</span>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="actions-row">
      <div class="action-card card" @click="router.push({ name: 'create' })">
        <span class="action-icon action-icon-blue"><Plus :size="20" /></span>
        <div class="action-copy">
          <h3>快速创建任务</h3>
          <p>输入需求描述，启动多 Agent 协作流程</p>
        </div>
        <span class="action-arrow"><ArrowRight :size="18" /></span>
      </div>
      <div class="action-card card" @click="router.push({ name: 'history' })">
        <span class="action-icon action-icon-violet"><History :size="20" /></span>
        <div class="action-copy">
          <h3>查看历史任务</h3>
          <p>浏览和管理已完成与进行中的任务</p>
        </div>
        <span class="action-arrow"><ArrowRight :size="18" /></span>
      </div>
    </div>

    <!-- Recent Tasks -->
    <div v-if="recentTasks.length" class="section">
      <div class="section-head">
        <div>
          <h2 class="section-title">最近任务</h2>
          <p>最近创建和更新的任务记录</p>
        </div>
        <button class="text-button" @click="router.push({ name: 'history' })">
          查看全部 <ArrowRight :size="14" />
        </button>
      </div>
      <div class="task-list card">
        <div
          v-for="task in recentTasks" :key="task.task_id"
          class="task-row"
          @click="router.push({ name: 'detail', params: { id: task.task_id } })"
        >
          <span class="task-leading"><Clock3 :size="16" /></span>
          <div class="task-body">
            <span class="task-text">{{ task.user_input }}</span>
            <span class="task-id">{{ task.task_id }}</span>
          </div>
          <span :class="['task-tag', statusMeta[task.status]?.cls || 'tag-info']">
            {{ statusMeta[task.status]?.label || task.status }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 30px;
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 7px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.page-header h1 {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 4px;
}
.page-header p { font-size: 14px; color: var(--text-secondary); }

/* ── Stats ──────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-box {
  position: relative;
  overflow: hidden;
  min-height: 124px;
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-box::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 3px;
  content: '';
  background: currentColor;
  opacity: 0.72;
}
.stat-top { display: flex; align-items: center; justify-content: space-between; }
.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: currentColor;
}
.stat-icon :deep(svg) { color: #fff; }
.stat-num { margin-top: 3px; font-size: 30px; font-weight: 750; letter-spacing: -0.03em; color: var(--text-primary); }
.stat-label { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.stat-note { font-size: 11px; color: var(--text-muted); }
.stat-box.clickable {
  cursor: pointer;
  transition: transform var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.stat-box.clickable:hover {
  transform: translateY(-2px);
  border-color: #b9cbf7;
  box-shadow: 0 8px 20px rgba(22, 93, 255, 0.08);
}
.stat-box.clickable:active { transform: translateY(0); }
.stat-box.clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.tone-blue { color: var(--accent); }
.tone-green { color: var(--success); }
.tone-amber { color: var(--warning); }
.tone-red { color: var(--danger); }

/* ── Actions ─────────────────────────────── */
.actions-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 36px;
}
.action-card {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 15px;
  min-height: 108px;
  padding: 22px 24px;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.action-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 13px;
}
.action-icon-blue { color: var(--accent); background: var(--accent-subtle); }
.action-icon-violet { color: #7955d9; background: #f2efff; }
.action-copy { flex: 1; }
.action-card:hover { border-color: #b9cbf7; transform: translateY(-2px); }
.action-card h3 { font-size: 15px; font-weight: 650; margin-bottom: 5px; }
.action-card p { font-size: 13px; color: var(--text-secondary); }
.action-arrow { display: flex; color: var(--text-muted); transition: transform var(--transition-fast); }
.action-card:hover .action-arrow { transform: translateX(3px); color: var(--accent); }

/* ── Tasks ──────────────────────────────── */
.section { margin-bottom: 24px; }
.section-head { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 12px; }
.section-title { font-size: 16px; font-weight: 650; }
.section-head p { margin-top: 2px; font-size: 12px; color: var(--text-muted); }
.text-button {
  display: flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
}
.task-list { display: flex; flex-direction: column; overflow: hidden; }
.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background var(--transition-fast);
}
.task-row:last-child { border-bottom: 0; }
.task-row:hover { background: var(--bg-card-hover); }
.task-leading {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  margin-right: 12px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--bg-overlay);
  color: var(--text-muted);
}
.task-body { flex: 1; overflow: hidden; }
.task-text {
  font-size: 13px;
  font-weight: 500;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}
.task-id { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.task-tag {
  font-size: 11px; font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
  margin-left: 12px;
}

/* ── Buttons & Tags ─────────────────────── */
.btn-primary {
  background: var(--accent-dark);
  border: 1px solid var(--accent-dark);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  border-radius: 8px;
  height: 38px;
  padding: 0 18px;
  box-shadow: 0 6px 14px rgba(22, 93, 255, 0.18);
}
.btn-primary:hover { background: var(--accent); border-color: var(--accent); }

.tag-info    { background: var(--info-subtle); color: var(--info); }
.tag-warning { background: var(--warning-subtle); color: var(--warning); }
.tag-success { background: var(--success-subtle); color: var(--success); }
.tag-danger  { background: var(--danger-subtle); color: var(--danger); }

@media (max-width: 900px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 620px) {
  .page-header h1 { font-size: 24px; }
  .stats-row, .actions-row { grid-template-columns: 1fr; }
  .stat-box { min-height: 100px; }
}
</style>
