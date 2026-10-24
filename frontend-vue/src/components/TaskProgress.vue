<script setup lang="ts">
import { computed } from 'vue'
import { FileInput, Brain, Lightbulb, Code, Eye, UserCheck, PackageOpen, Check } from '@lucide/vue'
import type { TaskStatusResponse } from '@/types'

const props = defineProps<{ data: TaskStatusResponse }>()

interface Node { key: string; label: string; icon: any }
const nodes: Node[] = [
  { key: 'queued',              label: '排队中',     icon: Check },
  { key: 'input_normalize',     label: '输入规范化', icon: FileInput },
  { key: 'planner',             label: '需求分析',   icon: Brain },
  { key: 'human_clarification', label: '人工澄清',   icon: Check },
  { key: 'solution',            label: '方案设计',   icon: Lightbulb },
  { key: 'engineer',            label: '工程实现',   icon: Code },
  { key: 'reviewer',            label: '智能评审',   icon: Eye },
  { key: 'human_approval',      label: '人工审批',   icon: UserCheck },
  { key: 'package_output',      label: '产物打包',   icon: PackageOpen },
]

const currentNodeIndex = computed(() => {
  const idx = nodes.findIndex(n => n.key === props.data.current_node)
  return idx >= 0 ? idx : -1
})

function nodeStatus(idx: number) {
  if (props.data.status === 'completed') return 'done'
  const cur = currentNodeIndex.value
  if (idx < cur) return 'done'
  if (idx === cur) return 'active'
  return 'pending'
}

const progressPercent = computed(() => {
  if (props.data.status === 'completed') return 100
  const idx = currentNodeIndex.value
  if (idx >= 0) return Math.round(((idx + 1) / nodes.length) * 100)
  return 0
})

const extraNodeLabels: Record<string, string> = {
  plan_evaluator: '方案评估',
  repairer: '自动修复',
  dialogue_reviewer: '对话评审',
  dialogue_solution: '方案对话',
  dialogue_engineer: '工程对话',
}

const failedNodeLabel = computed(() => {
  const key = props.data.current_node
  if (!key) return ''
  return nodes.find(n => n.key === key)?.label || extraNodeLabels[key] || key
})

const failureReason = computed(() => {
  const message = props.data.error_message?.trim()
  return message || '任务执行失败，服务没有返回具体原因。'
})

const statusMeta = computed(() => {
  const m: Record<string, { color: string; label: string }> = {
    queued: { color: 'var(--info)', label: '排队中' },
    running: { color: 'var(--warning)', label: '执行中' },
    waiting_human: { color: 'var(--warning)', label: '等待人工' },
    cancelling: { color: 'var(--warning)', label: '取消中' },
    cancelled: { color: 'var(--text-muted)', label: '已取消' },
    completed: { color: 'var(--success)', label: '已完成' },
    error: { color: 'var(--danger)', label: '执行失败' },
  }
  return m[props.data.status] || m.queued
})
</script>

<template>
  <div class="panel card">
    <div class="panel-head">
      <span class="panel-title">工作流进度</span>
      <span class="panel-badge" :style="{ color: statusMeta.color }">{{ statusMeta.label }}</span>
    </div>

    <div v-if="props.data.status === 'error'" class="error-reason">
      <strong>失败原因</strong>
      <span v-if="failedNodeLabel"> · {{ failedNodeLabel }}</span>
      <p>{{ failureReason }}</p>
    </div>

    <!-- Bar -->
    <div class="bar-wrap">
      <div class="bar-track">
        <div class="bar-fill" :class="{ failed: props.data.status === 'error' }" :style="{ width: progressPercent + '%' }" />
      </div>
      <span class="bar-pct">{{ progressPercent }}%</span>
    </div>

    <!-- Node Steps -->
    <div class="steps">
      <template v-for="(node, idx) in nodes" :key="node.key">
        <div v-if="idx > 0" :class="['step-line', nodeStatus(idx)]" />
        <div :class="['step', nodeStatus(idx)]">
          <div class="step-dot">
            <Check v-if="nodeStatus(idx) === 'done'" :size="12" />
            <component v-else :is="node.icon" :size="14" />
          </div>
          <span class="step-label">{{ node.label }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.panel {
  padding: 20px; margin-bottom: 18px;
}

.panel-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.panel-title { font-size: 14px; font-weight: 600; }
.panel-badge {
  font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 4px;
  background: var(--bg-primary);
}

/* ── Bar ─────────────────────────────────── */
.bar-wrap { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
.bar-track {
  flex: 1; height: 4px;
  background: var(--bg-primary);
  border-radius: 2px; overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.5s ease;
}
.bar-fill.failed { background: var(--danger); }

.error-reason {
  margin-bottom: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--danger-subtle);
  color: var(--danger);
  font-size: 13px;
  line-height: 1.6;
}
.error-reason strong { font-weight: 700; }
.error-reason p {
  margin-top: 4px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.bar-pct {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  font-family: var(--font-mono); min-width: 30px; text-align: right;
}

/* ── Steps ────────────────────────────────── */
.steps {
  display: flex; align-items: center; flex-wrap: wrap;
}
.step-line {
  width: 20px; height: 1px;
  background: var(--border);
  flex-shrink: 0;
  margin: 0 2px;
}
.step-line.done, .step-line.active { background: var(--accent); }

.step {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 0;
  transition: opacity var(--transition-fast);
}
.step.pending { opacity: 0.3; }
.step-label {
  font-size: 11px; font-weight: 500;
  color: var(--text-muted);
  white-space: nowrap;
}
.step.active .step-label { color: var(--accent); font-weight: 600; }
.step.done .step-label { color: var(--text-secondary); }

.step-dot {
  width: 26px; height: 26px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-primary);
  border: 1.5px solid var(--border);
  color: var(--text-muted);
  flex-shrink: 0;
  transition: all var(--transition-base);
}
.step.done .step-dot {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}
.step.active .step-dot {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-subtle);
}
.step.pending .step-dot {
  border-color: var(--border);
  color: var(--text-muted);
}
</style>
