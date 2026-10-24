<script setup lang="ts">
import { computed } from 'vue'
import type { TaskStatusResponse, TokenUsageSummary } from '@/types'
import { formatTokens } from '@/utils/format'

const props = defineProps<{ data: TaskStatusResponse }>()

interface Timing {
  node: string
  duration_seconds: number
}

const ROLE_LABELS: Record<string, string> = {
  planner: '需求分析',
  solution: '方案设计',
  engineer: '工程实现',
  reviewer: '智能评审',
  repairer: '自动修复',
  evaluator: '方案评估',
  dialogue: '对话',
  normalizer: '输入规范化',
  default: '默认',
}

const NODE_LABELS: Record<string, string> = {
  input_normalize: '输入规范化',
  planner: '需求分析',
  plan_evaluator: '方案评估',
  human_clarification: '人工澄清',
  solution: '方案设计',
  engineer: '工程实现',
  repairer: '自动修复',
  reviewer: '智能评审',
  human_approval: '人工审批',
  package_output: '产物打包',
}

const metrics = computed(() => (props.data.metrics || {}) as Record<string, unknown>)

const timings = computed<Timing[]>(() => {
  const list = (metrics.value.node_latencies as Timing[] | undefined) || []
  return list
    .filter((item) => item && typeof item.duration_seconds === 'number' && item.duration_seconds > 0)
    .sort((a, b) => b.duration_seconds - a.duration_seconds)
})

const total = computed(() => timings.value.reduce((sum, item) => sum + item.duration_seconds, 0))
const llmCalls = computed(() => Number(metrics.value.llm_call_count || 0))
const slowest = computed(() => timings.value[0])
const visible = computed(() => timings.value.slice(0, 8))

const usage = computed<TokenUsageSummary | null>(() => {
  const raw = metrics.value.token_usage
  return raw && typeof raw === 'object' ? (raw as TokenUsageSummary) : null
})

const roleEntries = computed(() =>
  Object.entries(usage.value?.by_role || {})
    .filter(([, item]) => item.total_tokens > 0)
    .sort((a, b) => b[1].total_tokens - a[1].total_tokens)
)

function roleLabel(role: string) {
  return ROLE_LABELS[role] || role
}

function pct(value: number) {
  return total.value ? Math.max(2, Math.round((value / total.value) * 100)) : 0
}

function seconds(value: number) {
  return value >= 1 ? value.toFixed(1) + 's' : Math.round(value * 1000) + 'ms'
}

function label(node: string) {
  return NODE_LABELS[node] || node
}
</script>

<template>
  <div v-if="timings.length" class="panel card">
    <div class="panel-head">
      <span class="panel-title">执行剖面</span>
      <span class="panel-note">按节点耗时降序</span>
    </div>

    <div class="stats">
      <div class="stat">
        <span class="stat-value">{{ seconds(total) }}</span>
        <span class="stat-label">节点总耗时</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ llmCalls }}</span>
        <span class="stat-label">LLM 调用</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ slowest ? label(slowest.node) : '-' }}</span>
        <span class="stat-label">最慢节点{{ slowest ? ' · ' + seconds(slowest.duration_seconds) : '' }}</span>
      </div>
    </div>

    <div class="bars">
      <div v-for="item in visible" :key="item.node + item.duration_seconds" class="bar-row">
        <span class="bar-label">{{ label(item.node) }}</span>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: pct(item.duration_seconds) + '%' }" />
        </div>
        <span class="bar-value">{{ seconds(item.duration_seconds) }}</span>
      </div>
    </div>

    <div v-if="usage" class="usage-block">
      <div class="usage-line">
        <span class="usage-total">{{ formatTokens(usage.total.total_tokens) }} tokens</span>
        <span class="usage-detail">
          输入 {{ formatTokens(usage.total.prompt_tokens) }} · 输出 {{ formatTokens(usage.total.completion_tokens) }}
        </span>
      </div>
      <div v-if="roleEntries.length" class="role-chips">
        <span v-for="[role, item] in roleEntries" :key="role" class="role-chip">
          {{ roleLabel(role) }} <b>{{ formatTokens(item.total_tokens) }}</b>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel { padding: 18px 20px; margin-bottom: 18px; }

.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}
.panel-title { font-size: 14px; font-weight: 600; }
.panel-note { font-size: 11px; color: var(--text-muted); }

.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.stat-value {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  font-family: var(--font-mono);
}
.stat-label { font-size: 11px; color: var(--text-muted); }

.bars { display: flex; flex-direction: column; gap: 7px; }
.bar-row {
  display: grid;
  grid-template-columns: 92px 1fr 54px;
  align-items: center;
  gap: 10px;
}
.bar-label {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bar-track {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  opacity: 0.85;
}
.bar-value {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  text-align: right;
}

.usage-block {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.usage-line { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; }
.usage-total { font-size: 14px; font-weight: 700; font-family: var(--font-mono); }
.usage-detail { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.usage-cost { margin-left: auto; font-size: 12px; font-weight: 600; color: var(--accent); font-family: var(--font-mono); }
.usage-cost.muted { color: var(--text-muted); font-weight: 400; }
.role-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.role-chip {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 2px 7px;
}
.role-chip b { font-family: var(--font-mono); font-weight: 600; color: var(--text-primary); }

@media (max-width: 720px) {
  .stats { grid-template-columns: 1fr; }
}
</style>
