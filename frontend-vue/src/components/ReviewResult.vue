<script setup lang="ts">
import { computed } from 'vue'
import { ShieldCheck, ShieldX, AlertTriangle, Lightbulb, Gauge } from '@lucide/vue'
import type { ReviewResult as ReviewType } from '@/types'

const props = defineProps<{ review: ReviewType }>()

const DIMENSIONS = [
  { key: 'completeness_score', label: '完整性', weight: 0.3 },
  { key: 'consistency_score', label: '一致性', weight: 0.25 },
  { key: 'feasibility_score', label: '可实现性', weight: 0.2 },
  { key: 'testability_score', label: '可测试性', weight: 0.15 },
  { key: 'security_score', label: '安全性', weight: 0.1 },
] as const

const ISSUE_GROUPS = [
  { key: 'solution', label: '方案侧' },
  { key: 'engineer', label: '技术侧' },
  { key: 'none', label: '其他' },
] as const

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

const overall = computed(() => Number(props.review.overall_score || 0))

const scoreColor = computed(() => {
  if (overall.value >= 8) return 'var(--success)'
  if (overall.value >= 6) return 'var(--warning)'
  return 'var(--danger)'
})

const dimensions = computed(() => {
  const source = props.review as unknown as Record<string, unknown>
  return DIMENSIONS.map((dimension) => ({
    ...dimension,
    value: Number(source[dimension.key] ?? 0),
  })).filter((dimension) => dimension.value > 0)
})

const formula = computed(() => {
  if (!dimensions.value.length) return ''
  const totalWeight = dimensions.value.reduce((sum, item) => sum + item.weight, 0)
  const terms = dimensions.value.map((item) => `${item.value}×${item.weight.toFixed(2)}`)
  const result = dimensions.value.reduce((sum, item) => sum + item.value * item.weight, 0) / totalWeight
  const normalize = dimensions.value.length < DIMENSIONS.length ? '，按已有维度归一' : ''
  return `(${terms.join(' + ')}) ÷ ${totalWeight.toFixed(2)}${normalize} = ${result.toFixed(1)}`
})

const issueGroups = computed(() =>
  ISSUE_GROUPS.map((group) => ({
    ...group,
    items: props.review.issues
      .filter((issue) => (issue.target || 'none') === group.key)
      .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)),
  })).filter((group) => group.items.length > 0)
)

const resolvedCount = computed(
  () => (props.review.issue_reviews || []).filter((item) => item.resolved).length
)

function barColor(value: number) {
  if (value >= 8) return 'var(--success)'
  if (value >= 6) return 'var(--accent)'
  if (value >= 4) return 'var(--warning)'
  return 'var(--danger)'
}
</script>

<template>
  <div class="panel card">
    <div class="panel-head">
      <ShieldCheck v-if="review.passed" :size="16" style="color:var(--success)" />
      <ShieldX v-else :size="16" style="color:var(--danger)" />
      <span>智能评审</span>
      <span :class="['badge', review.passed ? 'pass' : 'fail']">
        {{ review.passed ? '通过' : '未通过' }}
      </span>
    </div>

    <!-- Scores -->
    <div class="scores">
      <div class="score-box">
        <span class="score-num" :style="{ color: scoreColor }">{{ overall.toFixed(1) }}</span>
        <span class="score-label">综合评分</span>
      </div>
      <div class="score-box">
        <span class="score-num-sm">{{ Number(review.prd_score || 0).toFixed(1) }}</span>
        <span class="score-label">PRD 评分</span>
      </div>
      <div class="score-box">
        <span class="score-num-sm">{{ Number(review.tech_score || 0).toFixed(1) }}</span>
        <span class="score-label">技术评分</span>
      </div>
    </div>

    <!-- Rubric -->
    <div v-if="dimensions.length" class="rubric">
      <div class="rubric-head">
        <span class="sect-title"><Gauge :size="13" style="color:var(--accent)" /> 评分维度</span>
        <span class="rubric-formula">{{ formula }}</span>
      </div>
      <div v-for="dimension in dimensions" :key="dimension.key" class="dimension-row">
        <span class="dimension-label">{{ dimension.label }}</span>
        <span class="dimension-weight">{{ dimension.weight.toFixed(2) }}</span>
        <div class="dimension-track">
          <div
            class="dimension-fill"
            :style="{ width: dimension.value * 10 + '%', background: barColor(dimension.value) }"
          />
        </div>
        <span class="dimension-value">{{ dimension.value.toFixed(1) }}</span>
      </div>
    </div>

    <p v-if="review.summary" class="summary">{{ review.summary }}</p>

    <!-- Issues by target -->
    <div v-if="issueGroups.length" class="section">
      <div class="sect-title">
        <AlertTriangle :size="13" style="color:var(--warning)" />
        问题 ({{ review.issues.length }})
        <span v-if="resolvedCount" class="resolved-count">已解决 {{ resolvedCount }} 项</span>
      </div>
      <div v-for="group in issueGroups" :key="group.key" class="issue-group">
        <span class="group-label">{{ group.label }} · {{ group.items.length }}</span>
        <div v-for="(issue, idx) in group.items" :key="group.key + idx" class="issue-item">
          <div class="issue-head">
            <span :class="'sev sev-' + issue.severity">{{ issue.severity }}</span>
            <span :class="['origin', issue.origin === 'carried' ? 'carried' : 'new']">
              {{ issue.origin === 'carried' ? '旧问题' : '新问题' }}
            </span>
            <span class="issue-desc">{{ issue.description }}</span>
          </div>
          <div v-if="issue.suggestion" class="issue-sugg">
            <Lightbulb :size="11" /> {{ issue.suggestion }}
          </div>
        </div>
      </div>
    </div>

    <!-- Suggestions -->
    <div v-if="review.suggestions.length" class="section">
      <div class="sect-title" style="color:var(--info)">建议</div>
      <ul class="sugg-list">
        <li v-for="(suggestion, idx) in review.suggestions" :key="idx">{{ suggestion }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.panel { padding: 18px; margin-bottom: 16px; }
.panel-head { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; margin-bottom: 14px; }
.badge { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; margin-left: auto; }
.badge.pass { background: var(--success-subtle); color: var(--success); }
.badge.fail { background: var(--danger-subtle); color: var(--danger); }

/* ── Scores ──────────────────────────────── */
.scores { display: flex; gap: 24px; margin-bottom: 14px; }
.score-box { display: flex; flex-direction: column; }
.score-num { font-size: 26px; font-weight: 800; line-height: 1; }
.score-num-sm { font-size: 18px; font-weight: 700; line-height: 1; color: var(--text-primary); }
.score-label { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

/* ── Rubric ──────────────────────────────── */
.rubric {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: 14px;
}
.rubric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.rubric-head .sect-title { margin-bottom: 0; }
.rubric-formula {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  text-align: right;
  word-break: break-word;
}
.dimension-row {
  display: grid;
  grid-template-columns: 62px 34px 1fr 34px;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.dimension-row:last-child { margin-bottom: 0; }
.dimension-label { font-size: 11px; color: var(--text-secondary); }
.dimension-weight { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.dimension-track {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}
.dimension-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
.dimension-value {
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  text-align: right;
}

.summary {
  font-size: 12px; color: var(--text-secondary); line-height: 1.6;
  padding: 8px 10px;
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  margin-bottom: 14px;
  white-space: pre-wrap;
}

/* ── Issues ──────────────────────────────── */
.section { margin-top: 12px; }
.sect-title { display: flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.resolved-count {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 600;
  color: var(--success);
  background: var(--success-subtle);
  border-radius: 4px;
  padding: 1px 6px;
}
.issue-group { margin-bottom: 10px; }
.group-label {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}
.issue-item { margin-bottom: 6px; }
.issue-head { display: flex; gap: 6px; align-items: flex-start; }
.sev {
  font-size: 9px; font-weight: 700; text-transform: uppercase;
  padding: 1px 5px; border-radius: 3px; flex-shrink: 0; margin-top: 2px;
}
.sev-critical { background: var(--danger-subtle); color: var(--danger); }
.sev-high { background: var(--warning-subtle); color: var(--warning); }
.sev-medium { background: var(--info-subtle); color: var(--info); }
.sev-low { background: var(--bg-primary); color: var(--text-muted); }
.origin {
  font-size: 9px; font-weight: 700;
  padding: 1px 5px; border-radius: 3px;
  flex-shrink: 0; margin-top: 2px;
}
.origin.carried { background: var(--warning-subtle); color: var(--warning); }
.origin.new { background: var(--info-subtle); color: var(--info); }
.issue-desc { font-size: 12px; color: var(--text-primary); line-height: 1.5; }
.issue-sugg {
  font-size: 11px; color: var(--info);
  display: flex; align-items: center; gap: 3px;
  margin-top: 3px; padding-left: 54px;
}

.sugg-list { padding-left: 18px; }
.sugg-list li { font-size: 12px; color: var(--text-secondary); margin-bottom: 3px; }
</style>
