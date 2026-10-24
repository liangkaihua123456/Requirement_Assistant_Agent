<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, AlertTriangle } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { TraceabilityResponse } from '@/types'

const props = defineProps<{ taskId: string; active: boolean }>()

const { getTraceability } = useTaskApi()
const data = ref<TraceabilityResponse | null>(null)
const loading = ref(false)
const error = ref('')
const expanded = ref<Set<string>>(new Set())

async function load() {
  if (!props.taskId) return
  loading.value = true
  error.value = ''
  try {
    data.value = await getTraceability(props.taskId)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
    error.value = detail || '追溯矩阵加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.taskId, load)
watch(
  () => props.active,
  (active) => {
    if (active && !data.value && !loading.value) load()
  }
)

const features = computed(() => data.value?.features || [])
const summary = computed(() => data.value?.summary)

function toggle(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function level(weight: number) {
  if (weight >= 1) return { key: 'exact', label: '精确' }
  if (weight >= 0.8) return { key: 'name', label: '名称' }
  if (weight > 0) return { key: 'text', label: '文本' }
  return { key: 'missing', label: '缺失' }
}

// Service mapping is informational: the review gate only checks API and DB.
function serviceLevel(weight: number) {
  return weight > 0 ? { key: 'name', label: '已关联' } : { key: 'neutral', label: '未标注' }
}

function pct(value: number) {
  return Math.round(value * 100) + '%'
}
</script>

<template>
  <div class="trace-panel">
    <div v-if="loading" class="state-block">正在计算追溯关系...</div>
    <div v-else-if="error" class="state-block error">
      <AlertTriangle :size="16" />
      <span>{{ error }}</span>
      <button class="retry" @click="load">重试</button>
    </div>

    <template v-else-if="summary">
      <div class="summary-row">
        <div class="stat">
          <span class="stat-value">{{ summary.feature_count }}</span>
          <span class="stat-label">功能模块</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ pct(summary.api_score) }}</span>
          <span class="stat-label">API 覆盖</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ pct(summary.db_score) }}</span>
          <span class="stat-label">数据表覆盖</span>
        </div>
        <div class="stat">
          <span class="stat-value" :class="{ warn: summary.missing_api.length + summary.missing_db.length > 0 }">
            {{ summary.missing_api.length + summary.missing_db.length }}
          </span>
          <span class="stat-label">未映射项</span>
        </div>
      </div>

      <p class="legend">
        <span class="legend-item"><i class="dot exact" />精确：feature_id 命中</span>
        <span class="legend-item"><i class="dot name" />名称：模块名命中</span>
        <span class="legend-item"><i class="dot text" />文本：仅正文提及</span>
        <span class="legend-item"><i class="dot missing" />缺失：无追溯</span>
      </p>

      <div class="table-wrap">
        <table class="matrix">
          <thead>
            <tr>
              <th class="col-feature">功能模块</th>
              <th class="col-cell">服务</th>
              <th class="col-cell">API</th>
              <th class="col-cell">数据表</th>
              <th class="col-cell">验收标准</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in features" :key="row.feature_id">
              <tr class="matrix-row" @click="toggle(row.feature_id)">
                <td>
                  <div class="feature-cell">
                    <component :is="expanded.has(row.feature_id) ? ChevronDown : ChevronRight" :size="14" class="chev" />
                    <span class="feature-name">{{ row.name }}</span>
                    <span v-if="row.priority" class="priority" :class="row.priority.toLowerCase()">{{ row.priority }}</span>
                  </div>
                  <code class="feature-id">{{ row.feature_id }}</code>
                </td>
                <td>
                  <span :class="['cell', serviceLevel(row.service.weight).key]">
                    <b>{{ serviceLevel(row.service.weight).label }}</b>
                    <em>{{ row.service.items.length }}</em>
                  </span>
                </td>
                <td>
                  <span :class="['cell', level(row.api.weight).key]">
                    <b>{{ level(row.api.weight).label }}</b>
                    <em>{{ row.api.items.length }}</em>
                  </span>
                </td>
                <td>
                  <span :class="['cell', level(row.db.weight).key]">
                    <b>{{ level(row.db.weight).label }}</b>
                    <em>{{ row.db.items.length }}</em>
                  </span>
                </td>
                <td>
                  <span class="count">{{ row.acceptance_criteria.length }}</span>
                </td>
              </tr>

              <tr v-if="expanded.has(row.feature_id)" class="detail-row">
                <td colspan="5">
                  <div class="detail-grid">
                    <section v-if="row.api.items.length">
                      <h4>API</h4>
                      <ul>
                        <li v-for="api in row.api.items" :key="api.method + api.path">
                          <code>{{ api.method }} {{ api.path }}</code>
                          <span>{{ api.description }}</span>
                        </li>
                      </ul>
                    </section>
                    <section v-if="row.db.items.length">
                      <h4>数据表</h4>
                      <ul>
                        <li v-for="table in row.db.items" :key="table.table_name">
                          <code>{{ table.table_name }}</code>
                          <span>{{ table.column_count }} 个字段 · {{ table.description }}</span>
                        </li>
                      </ul>
                    </section>
                    <section v-if="row.service.items.length">
                      <h4>服务</h4>
                      <ul>
                        <li v-for="service in row.service.items" :key="service.name">
                          <code>{{ service.name }}</code>
                          <span>{{ service.responsibility }}</span>
                        </li>
                      </ul>
                    </section>
                    <section v-if="row.acceptance_criteria.length" class="full">
                      <h4>验收标准</h4>
                      <ul>
                        <li v-for="(criterion, index) in row.acceptance_criteria" :key="index">
                          <span>{{ criterion }}</span>
                        </li>
                      </ul>
                    </section>
                    <p v-if="!row.api.items.length && !row.db.items.length && !row.acceptance_criteria.length" class="empty">
                      该模块没有可展开的明细。
                    </p>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>

    <div v-else class="state-block">暂无追溯数据。</div>
  </div>
</template>

<style scoped>
.trace-panel { padding: 4px 0 8px; }

.summary-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.stat {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-family: var(--font-mono);
}
.stat-value.warn { color: var(--danger); }
.stat-label { font-size: 11px; color: var(--text-muted); }

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 10px;
}
.legend-item { display: inline-flex; align-items: center; gap: 5px; }
.dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.dot.exact { background: var(--success); }
.dot.name { background: var(--info); }
.dot.text { background: var(--warning); }
.dot.missing { background: var(--danger); }

.table-wrap {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--bg-card);
}
.matrix { width: 100%; border-collapse: collapse; }
.matrix th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  padding: 10px 12px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
}
.col-feature { width: 38%; }
.col-cell { width: 15.5%; }

.matrix-row { cursor: pointer; transition: background var(--transition-fast); }
.matrix-row:hover { background: var(--bg-card-hover); }
.matrix-row td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-light);
  vertical-align: middle;
}
.feature-cell { display: flex; align-items: center; gap: 6px; }
.chev { color: var(--text-muted); flex-shrink: 0; }
.feature-name { font-size: 13px; font-weight: 600; }
.priority {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-family: var(--font-mono);
}
.priority.p0 { background: var(--danger-subtle); color: var(--danger); }
.priority.p1 { background: var(--warning-subtle); color: var(--warning); }
.feature-id {
  display: block;
  margin-top: 3px;
  margin-left: 20px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid transparent;
}
.cell b { font-weight: 600; }
.cell em { font-style: normal; font-family: var(--font-mono); opacity: 0.75; }
.cell.exact { background: var(--success-subtle); color: var(--success); border-color: var(--success-subtle); }
.cell.name { background: var(--info-subtle); color: var(--info); }
.cell.text { background: var(--warning-subtle); color: var(--warning); }
.cell.missing { background: var(--danger-subtle); color: var(--danger); }
.cell.neutral { background: var(--bg-primary); color: var(--text-muted); }
.count { font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); }

.detail-row td {
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  padding: 14px 16px 16px 32px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 24px;
}
.detail-grid section.full { grid-column: 1 / -1; }
.detail-grid h4 {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.detail-grid ul { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.detail-grid li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-word;
}
.detail-grid code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  padding: 1px 5px;
  flex-shrink: 0;
}
.detail-grid .empty { font-size: 12px; color: var(--text-muted); }

.state-block {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}
.state-block.error { color: var(--danger); flex-direction: column; }
.retry {
  margin-top: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  border-radius: var(--radius-sm);
  padding: 4px 12px;
  cursor: pointer;
}
.retry:hover { border-color: var(--text-muted); color: var(--text-primary); }

@media (max-width: 900px) {
  .summary-row { grid-template-columns: repeat(2, 1fr); }
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
