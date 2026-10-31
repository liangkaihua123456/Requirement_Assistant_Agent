<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Database,
  RefreshCw,
  Sparkles,
  Zap,
} from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { UsageStatsResponse } from '@/types'
import { formatSeconds, formatTokens } from '@/utils/format'
import UsageTrendChart from '@/components/UsageTrendChart.vue'

const { getUsageStats } = useTaskApi()

const loading = ref(false)
const error = ref('')
const days = ref(30)
const data = ref<UsageStatsResponse | null>(null)
const tab = ref<'requests' | 'models' | 'roles' | 'nodes' | 'sources'>('requests')

const ranges = [
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getUsageStats(days.value)
  } catch {
    error.value = '使用统计加载失败，请确认后端已启动'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(days, load)

const summary = computed(() => data.value?.summary)
const series = computed(() => data.value?.series || [])
// 窗口内大部分日子可能是 0，全画出来曲线会挤在右端。裁到有数据的区间，前后各留一天。
const visibleSeries = computed(() => {
  const all = series.value
  if (!all.length) return all
  const active = (p: (typeof all)[number]) => Boolean(p.cache_miss || p.output || p.cached || p.cost)
  const first = all.findIndex(active)
  if (first < 0) return all.slice(-7)
  let last = all.length - 1
  while (last > first && !active(all[last])) last -= 1
  return all.slice(Math.max(0, first - 1), Math.min(all.length, last + 2))
})
const requests = computed(() => data.value?.requests || [])
const buckets = computed(() => {
  if (tab.value === 'models') return data.value?.by_model || []
  if (tab.value === 'roles') return data.value?.by_role || []
  if (tab.value === 'nodes') return data.value?.by_node || []
  if (tab.value === 'sources') return data.value?.by_source || []
  return []
})
const bucketTitle = computed(() => {
  if (tab.value === 'models') return '模型'
  if (tab.value === 'roles') return '角色'
  if (tab.value === 'nodes') return '节点'
  return '来源'
})

const modelFilter = ref('all')
const statusFilter = ref('all')

const modelOptions = computed(() => (data.value?.by_model || []).map((item) => item.key))

const filteredRequests = computed(() =>
  requests.value.filter((row) => {
    if (statusFilter.value !== 'all' && row.status !== statusFilter.value) return false
    if (modelFilter.value !== 'all' && !row.models.includes(modelFilter.value)) return false
    return true
  })
)

function exportCsv() {
  const rows = filteredRequests.value
  if (!rows.length) return

  const header = ['时间', '任务ID', '需求', '模型', '输入', '输出', '总Tokens', '缓存命中', '耗时(秒)', '状态']
  const lines = [header.join(',')]
  for (const row of rows) {
    lines.push(
      [
        formatTime(row.created_at),
        row.task_id,
        `"${(row.user_input || '').replace(/"/g, '""')}"`,
        row.models,
        row.prompt_tokens,
        row.completion_tokens,
        row.total_tokens,
        row.cached_tokens,
        row.duration_seconds != null ? Number(row.duration_seconds).toFixed(1) : '',
        statusLabel(row.status),
      ].join(',')
    )
  }

  // BOM keeps Excel from mangling Chinese characters.
  const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `usage-${days.value}d-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

function wan(value?: number | null) {
  if (value == null) return '-'
  if (value === 0) return '0'
  if (value < 10_000) return value.toLocaleString('en-US')
  return (value / 10_000).toFixed(1) + ' 万'
}

function percent(value?: number) {
  return ((value || 0) * 100).toFixed(1) + '%'
}

function formatTime(value?: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-'
}

function statusLabel(status: string) {
  return status === 'completed' ? '已完成' : status === 'error' ? '失败' : status || '-'
}

function statusClass(status: string) {
  if (status === 'completed') return 'completed'
  if (status === 'error') return 'error'
  return 'running'
}
</script>

<template>
  <div class="stats-page animate-in">
    <div class="page-header">
      <div>
        <div class="eyebrow"><Activity :size="13" /> Usage</div>
        <h1>使用统计</h1>
        <p>按每一次模型调用记账，失败节点的消耗同样计入</p>
      </div>
      <div class="header-actions">
        <div class="range-switch">
          <button
            v-for="range in ranges"
            :key="range.value"
            :class="['range-btn', { active: days === range.value }]"
            @click="days = range.value"
          >{{ range.label }}</button>
        </div>
        <button class="refresh-btn" :disabled="loading" @click="load">
          <RefreshCw :size="14" :class="{ spinning: loading }" />
        </button>
      </div>
    </div>

    <div v-if="error" class="state-block error">{{ error }}</div>

    <template v-else>
      <div class="overview card">
        <div class="ov-head">
          <div class="ov-badge"><Zap :size="20" /></div>
          <div class="ov-main">
            <span class="ov-label">真实消耗 Tokens</span>
            <div class="ov-value">
              <strong>{{ (summary?.total_tokens || 0).toLocaleString() }}</strong>
              <small>≈ {{ wan(summary?.total_tokens) }}</small>
            </div>
          </div>
          <div class="ov-kpis">
            <div class="kpi">
              <span>总请求数</span>
              <strong>{{ summary?.requests || 0 }}</strong>
            </div>
            <div class="kpi">
              <span>总调用</span>
              <strong>{{ summary?.calls || 0 }}</strong>
            </div>
          </div>
        </div>

        <div class="ov-tiles">
          <div class="tile">
            <span class="tile-label"><ArrowDownToLine :size="13" /> 新增输入</span>
            <strong>{{ wan(summary?.cache_miss_tokens) }}</strong>
          </div>
          <div class="tile">
            <span class="tile-label"><ArrowUpFromLine :size="13" /> Output</span>
            <strong>{{ wan(summary?.completion_tokens) }}</strong>
          </div>
          <div class="tile" title="DeepSeek 只返回命中量，不单列缓存创建用量">
            <span class="tile-label"><Database :size="13" /> 创建 <Info :size="11" class="info" /></span>
            <strong class="muted">N/A</strong>
          </div>
          <div class="tile">
            <span class="tile-label"><Sparkles :size="13" /> 命中</span>
            <strong>{{ wan(summary?.cached_tokens) }}</strong>
          </div>
          <div class="tile hit">
            <span class="tile-label">缓存命中率</span>
            <strong class="green">{{ percent(summary?.cache_hit_rate) }}</strong>
            <div class="hit-track">
              <i :style="{ width: Math.min(100, (summary?.cache_hit_rate || 0) * 100) + '%' }" />
            </div>
          </div>
        </div>
      </div>

      <div class="trend card">
        <div class="card-head">
          <h3>使用趋势</h3>
          <span v-if="visibleSeries.length" class="range-label">
            {{ visibleSeries[0].date }} — {{ visibleSeries[visibleSeries.length - 1].date }}
          </span>
        </div>
        <UsageTrendChart :series="visibleSeries" />
        <div class="legend">
          <span><i class="dot cached" />缓存命中</span>
          <span><i class="dot input" />输入</span>
          <span><i class="dot output" />输出</span>
        </div>
      </div>

      <div class="detail card">
        <div class="tabs">
          <button :class="['tab-btn', { active: tab === 'requests' }]" @click="tab = 'requests'">请求日志</button>
          <button :class="['tab-btn', { active: tab === 'models' }]" @click="tab = 'models'">模型统计</button>
          <button :class="['tab-btn', { active: tab === 'roles' }]" @click="tab = 'roles'">角色统计</button>
          <button :class="['tab-btn', { active: tab === 'nodes' }]" @click="tab = 'nodes'">节点统计</button>
          <button :class="['tab-btn', { active: tab === 'sources' }]" @click="tab = 'sources'">来源统计</button>
        </div>

        <div v-if="tab === 'requests'">
          <div class="table-toolbar">
            <div class="filters">
              <select v-model="modelFilter" class="filter-select">
                <option value="all">全部模型</option>
                <option v-for="model in modelOptions" :key="model" :value="model">{{ model }}</option>
              </select>
              <select v-model="statusFilter" class="filter-select">
                <option value="all">全部状态</option>
                <option value="completed">已完成</option>
                <option value="error">失败</option>
                <option value="waiting_human">待处理</option>
              </select>
              <span class="filter-count">{{ filteredRequests.length }} 条</span>
            </div>
            <button class="export-btn" :disabled="!filteredRequests.length" @click="exportCsv">导出 CSV</button>
          </div>

          <div class="table-wrap">
            <table v-if="filteredRequests.length" class="table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>任务</th>
                  <th>模型</th>
                  <th class="num">调用</th>
                  <th class="num">输入</th>
                  <th class="num">输出</th>
                  <th class="num">总 Tokens</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in filteredRequests" :key="row.task_id">
                  <td class="mono">{{ formatTime(row.created_at) }}</td>
                  <td class="task-cell">
                    <span class="mono">{{ row.task_id }}</span>
                    <small>{{ row.user_input }}</small>
                  </td>
                  <td class="mono">{{ row.models || '-' }}</td>
                  <td class="num mono">{{ row.calls ?? '-' }}</td>
                  <td class="num mono">{{ formatTokens(row.prompt_tokens) }}</td>
                  <td class="num mono">{{ formatTokens(row.completion_tokens) }}</td>
                  <td class="num mono">{{ formatTokens(row.total_tokens) }}</td>
                  <td>
                    <span :class="['status', statusClass(row.status)]">{{ statusLabel(row.status) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty">没有符合筛选条件的用量记录</div>
          </div>
        </div>

        <div v-else class="table-wrap">
          <table v-if="buckets.length" class="table">
            <thead>
              <tr>
                <th>{{ bucketTitle }}</th>
                <th class="num">调用</th>
                <th class="num">新增输入</th>
                <th class="num">输出</th>
                <th class="num">缓存命中</th>
                <th class="num">总 Tokens</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in buckets" :key="item.key">
                <td>
                  <span class="bucket-label">{{ item.label || '未标注' }}</span>
                  <small v-if="item.label !== item.key" class="mono">{{ item.key }}</small>
                </td>
                <td class="num mono">{{ item.calls }}</td>
                <td class="num mono">{{ formatTokens(item.cache_miss_tokens) }}</td>
                <td class="num mono">{{ formatTokens(item.completion_tokens) }}</td>
                <td class="num mono">{{ formatTokens(item.cached_tokens) }}</td>
                <td class="num mono">{{ formatTokens(item.total_tokens) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">该时间范围内还没有用量记录</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 22px;
}
.page-header h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 4px; }
.page-header p { font-size: 14px; color: var(--text-secondary); }
.eyebrow {
  display: flex; align-items: center; gap: 6px; margin-bottom: 7px;
  color: var(--accent); font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
}
.header-actions { display: flex; align-items: center; gap: 8px; }

.range-switch {
  display: inline-flex; gap: 2px; padding: 3px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--bg-card);
}
.range-btn {
  padding: 5px 12px; border: none; border-radius: 6px; background: transparent;
  color: var(--text-secondary); font-size: 12px; font-family: var(--font-sans);
  cursor: pointer; transition: all var(--transition-fast);
}
.range-btn.active { background: var(--accent); color: #fff; font-weight: 600; }
.refresh-btn {
  display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); color: var(--text-secondary); cursor: pointer;
}
.refresh-btn:hover { color: var(--text-primary); }
.refresh-btn:disabled { opacity: 0.5; }
.spinning { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Overview ─────────────────────────────── */
.overview { padding: 22px 24px; margin-bottom: 16px; }
.ov-head { display: flex; align-items: flex-start; gap: 14px; flex-wrap: wrap; }
.ov-badge {
  display: flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; flex-shrink: 0;
  border-radius: 11px; color: var(--accent); background: var(--accent-subtle);
}
.ov-main { flex: 1; min-width: 200px; }
.ov-label { font-size: 11.5px; color: var(--text-muted); }
.ov-value { display: flex; align-items: baseline; gap: 10px; margin-top: 2px; }
.ov-value strong {
  font-size: 34px; font-weight: 800; letter-spacing: -0.035em;
  line-height: 1.15; font-family: var(--font-mono);
}
.ov-value small { font-size: 12.5px; color: var(--text-muted); font-family: var(--font-mono); }

.ov-kpis { display: flex; gap: 30px; }
.kpi { display: flex; flex-direction: column; gap: 3px; }
.kpi span { font-size: 11px; color: var(--text-muted); }
.kpi strong { font-size: 17px; font-weight: 700; font-family: var(--font-mono); }

.ov-tiles {
  display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px; margin-top: 18px;
}
.tile {
  display: flex; flex-direction: column; gap: 6px;
  padding: 12px 14px;
  border-radius: 12px; background: #f5f7fa;
}
.tile-label {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; color: var(--text-muted);
}
.tile-label svg { color: var(--text-secondary); }
.tile-label .info { opacity: 0.6; }
.tile strong { font-size: 16px; font-weight: 700; font-family: var(--font-mono); }
.tile strong.muted { color: var(--text-muted); font-weight: 600; }
.tile strong.green { color: var(--success); }
.hit-track { height: 5px; border-radius: 3px; background: #e6ebf2; overflow: hidden; margin-top: 2px; }
.hit-track i { display: block; height: 100%; background: var(--success); border-radius: 3px; }

/* ── Trend ────────────────────────────────── */
.trend { padding: 20px 22px 14px; margin-bottom: 16px; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 6px; }
.card-head h3 { font-size: 15px; font-weight: 650; }
.range-label { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.legend { display: flex; gap: 20px; justify-content: center; padding: 6px 0 2px; flex-wrap: wrap; }
.legend span { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-secondary); }
.dot { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.dot.input { background: #246bfd; }
.dot.output { background: #19a55a; }
.dot.cached { background: #8b5cf6; }

/* ── Detail ───────────────────────────────── */
.detail { padding: 0; overflow: hidden; }
.tabs { display: flex; gap: 2px; padding: 10px 16px 0; border-bottom: 1px solid var(--border-light); flex-wrap: wrap; }
.tab-btn {
  padding: 8px 13px; border: none; border-bottom: 2px solid transparent;
  background: transparent; color: var(--text-secondary);
  font-size: 12.5px; font-family: var(--font-sans); cursor: pointer;
}
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

.table-wrap { overflow-x: auto; }
.table-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border-light);
}
.filters { display: flex; align-items: center; gap: 8px; }
.filter-select {
  height: 30px; padding: 0 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-primary);
  font-size: 12px; font-family: var(--font-sans); outline: none;
}
.filter-select:focus { border-color: var(--accent); }
.filter-count { font-size: 11px; color: var(--text-muted); }
.export-btn {
  height: 30px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 12px; font-family: var(--font-sans); cursor: pointer;
}
.export-btn:hover { border-color: var(--accent); color: var(--accent); }
.export-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.table { width: 100%; border-collapse: collapse; }
.table th {
  text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 600;
  color: var(--text-muted); background: var(--bg-primary);
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.table td {
  padding: 10px 14px; font-size: 12px; color: var(--text-secondary);
  border-bottom: 1px solid var(--border-light); white-space: nowrap;
}
.table tbody tr:hover { background: var(--bg-card-hover); }
.table .num { text-align: right; }
.mono { font-family: var(--font-mono); font-size: 11px; }
.task-cell { display: flex; flex-direction: column; gap: 2px; }
.task-cell small {
  display: block; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; font-size: 10px; color: var(--text-muted);
}
.bucket-label { display: block; font-weight: 600; color: var(--text-primary); }
.bucket-label + small { display: block; }
.status { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 4px; }
.status.completed { background: var(--success-subtle); color: var(--success); }
.status.error { background: var(--danger-subtle); color: var(--danger); }
.status.running { background: var(--warning-subtle); color: var(--warning); }
.empty { padding: 40px 0; text-align: center; font-size: 12px; color: var(--text-muted); }
.state-block.error { padding: 40px 0; text-align: center; color: var(--danger); font-size: 13px; }

@media (max-width: 1100px) {
  .ov-tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .ov-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ov-kpis { gap: 18px; }
  .page-header { flex-direction: column; gap: 12px; }
}
</style>
