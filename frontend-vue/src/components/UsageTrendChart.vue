<script setup lang="ts">
import { computed, ref } from 'vue'
import type { UsageSeriesPoint } from '@/types'

const props = defineProps<{ series: UsageSeriesPoint[] }>()

const W = 1000
const H = 320
const PAD = { left: 66, right: 26, top: 18, bottom: 44 }

const COLORS = {
  input: '#246bfd',
  output: '#19a55a',
  cached: '#8b5cf6',
}

const svgRef = ref<SVGSVGElement | null>(null)
const hoverIndex = ref<number | null>(null)

const chart = computed(() => {
  const points = props.series
  const count = points.length
  if (!count) return null

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const baseline = PAD.top + innerH

  const rawMaxTokens = Math.max(1, ...points.map((p) => Math.max(p.cache_miss, p.output, p.cached)))
  // 刻度取整到 1/2/2.5/5×10^n，避免出现 613k、920k 这种读数。
  const niceMax = (value: number) => {
    const exp = Math.floor(Math.log10(Math.max(value, 1)))
    const base = Math.pow(10, exp)
    const norm = value / base
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10
    return step * base
  }
  const maxTokens = niceMax(rawMaxTokens)

  const x = (index: number) =>
    PAD.left + (count === 1 ? innerW / 2 : (index / (count - 1)) * innerW)
  const yTokens = (value: number) => PAD.top + (1 - value / maxTokens) * innerH

  // 单调三次插值（Fritsch–Carlson）：平滑但不过冲。
  // 从 0 突然跳到峰值的用量曲线用普通 Catmull-Rom 会鼓出假高点。
  const curve = (values: number[], y: (v: number) => number) => {
    const pts = values.map((value, index) => ({ x: x(index), y: y(value) }))
    if (!pts.length) return ''
    if (pts.length === 1) return `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`

    const n = pts.length
    const dx: number[] = []
    const slope: number[] = []
    for (let i = 0; i < n - 1; i += 1) {
      dx[i] = pts[i + 1].x - pts[i].x || 1
      slope[i] = (pts[i + 1].y - pts[i].y) / dx[i]
    }
    const tangent: number[] = new Array(n).fill(0)
    tangent[0] = slope[0]
    tangent[n - 1] = slope[n - 2]
    for (let i = 1; i < n - 1; i += 1) {
      tangent[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2
    }
    for (let i = 0; i < n - 1; i += 1) {
      if (slope[i] === 0) {
        tangent[i] = 0
        tangent[i + 1] = 0
        continue
      }
      const a = tangent[i] / slope[i]
      const b = tangent[i + 1] / slope[i]
      const s = a * a + b * b
      if (s > 9) {
        const tau = 3 / Math.sqrt(s)
        tangent[i] = tau * a * slope[i]
        tangent[i + 1] = tau * b * slope[i]
      }
    }

    let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`
    for (let i = 0; i < n - 1; i += 1) {
      const h = dx[i]
      const c1x = pts[i].x + h / 3
      const c1y = pts[i].y + (tangent[i] * h) / 3
      const c2x = pts[i + 1].x - h / 3
      const c2y = pts[i + 1].y - (tangent[i + 1] * h) / 3
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${pts[i + 1].x.toFixed(1)},${pts[i + 1].y.toFixed(1)}`
    }
    return d
  }

  const areaOf = (values: number[], y: (v: number) => number) =>
    `${curve(values, y)} L${x(count - 1).toFixed(1)},${baseline.toFixed(1)} L${x(0).toFixed(1)},${baseline.toFixed(1)} Z`

  const step = Math.max(1, Math.ceil(count / 9))
  const xLabels = points
    .map((point, index) => ({ x: x(index), text: point.date.slice(5), index }))
    .filter((item) => {
      if (item.index === count - 1) return true
      if (item.index % step !== 0) return false
      return count - 1 - item.index > step * 0.6
    })

  return {
    baseline,
    innerW,
    left: PAD.left,
    right: W - PAD.right,
    x,
    count,
    ticks: [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
      y: PAD.top + innerH * (1 - ratio),
      tokens: maxTokens * ratio,
    })),
    xLabels,
    missPath: curve(points.map((p) => p.cache_miss), yTokens),
    outputPath: curve(points.map((p) => p.output), yTokens),
    cachedPath: curve(points.map((p) => p.cached), yTokens),
    missArea: areaOf(points.map((p) => p.cache_miss), yTokens),
    outputArea: areaOf(points.map((p) => p.output), yTokens),
    cachedArea: areaOf(points.map((p) => p.cached), yTokens),
  }
})

const hover = computed(() => {
  const data = chart.value
  const index = hoverIndex.value
  if (!data || index == null) return null
  const point = props.series[index]
  if (!point) return null
  return { point, x: data.x(index), percent: (data.x(index) / W) * 100 }
})

const tooltipStyle = computed(() => {
  const h = hover.value
  if (!h) return {}
  const flip = h.percent > 62
  return {
    left: `${h.percent}%`,
    transform: flip
      ? 'translate(-100%, -50%) translateX(-14px)'
      : 'translate(0, -50%) translateX(14px)',
  }
})

function onMove(event: MouseEvent) {
  const data = chart.value
  const svg = svgRef.value
  if (!data || !svg) return
  const rect = svg.getBoundingClientRect()
  if (!rect.width) return
  const localX = ((event.clientX - rect.left) / rect.width) * W
  const ratio = (localX - PAD.left) / Math.max(1, data.innerW)
  const index = Math.round(ratio * (data.count - 1))
  hoverIndex.value = Math.min(data.count - 1, Math.max(0, index))
}

function axisTokens(value: number) {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + 'M'
  if (value >= 1_000) return Math.round(value / 1_000) + 'k'
  return String(Math.round(value))
}

function num(value: number) {
  return value.toLocaleString('en-US')
}
</script>

<template>
  <div class="chart-wrap">
    <svg
      v-if="chart"
      ref="svgRef"
      :viewBox="`0 0 ${W} ${H}`"
      class="chart"
      role="img"
      aria-label="Token 使用趋势"
      @mousemove="onMove"
      @mouseleave="hoverIndex = null"
    >
      <defs>
        <linearGradient id="g-miss" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="COLORS.input" stop-opacity="0.28" />
          <stop offset="100%" :stop-color="COLORS.input" stop-opacity="0.02" />
        </linearGradient>
        <linearGradient id="g-cached" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="COLORS.cached" stop-opacity="0.26" />
          <stop offset="100%" :stop-color="COLORS.cached" stop-opacity="0.02" />
        </linearGradient>
        <linearGradient id="g-output" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="COLORS.output" stop-opacity="0.22" />
          <stop offset="100%" :stop-color="COLORS.output" stop-opacity="0.02" />
        </linearGradient>
      </defs>

      <g class="grid">
        <g v-for="tick in chart.ticks" :key="tick.y">
          <line :x1="chart.left" :y1="tick.y" :x2="chart.right" :y2="tick.y" />
          <text :x="chart.left - 12" :y="tick.y + 4" text-anchor="end" class="axis-l">
            {{ axisTokens(tick.tokens) }}
          </text>
        </g>
      </g>

      <path :d="chart.cachedArea" fill="url(#g-cached)" />
      <path :d="chart.missArea" fill="url(#g-miss)" />
      <path :d="chart.outputArea" fill="url(#g-output)" />

      <path :d="chart.missPath" :stroke="COLORS.input" class="line" />
      <path :d="chart.cachedPath" :stroke="COLORS.cached" class="line" />
      <path :d="chart.outputPath" :stroke="COLORS.output" class="line" />

      <g class="x-axis">
        <text
          v-for="label in chart.xLabels"
          :key="label.index"
          :x="label.x"
          :y="chart.baseline + 24"
          text-anchor="middle"
        >{{ label.text }}</text>
      </g>

      <g v-if="hover">
        <line :x1="hover.x" :y1="chart.ticks[0].y" :x2="hover.x" :y2="chart.baseline" class="hover-line" />
      </g>
    </svg>

    <div v-if="hover" class="tip" :style="tooltipStyle">
      <div class="tip-date">{{ hover.point.date }}</div>
      <div class="tip-row"><i :style="{ background: COLORS.input }" />输入<span>{{ num(hover.point.cache_miss) }}</span></div>
      <div class="tip-row"><i :style="{ background: COLORS.output }" />输出<span>{{ num(hover.point.output) }}</span></div>
      <div class="tip-row"><i :style="{ background: COLORS.cached }" />缓存命中<span>{{ num(hover.point.cached) }}</span></div>
    </div>

    <div v-if="!chart" class="empty">该时间范围内还没有用量记录</div>
  </div>
</template>

<style scoped>
.chart-wrap { position: relative; width: 100%; }
.chart { display: block; width: 100%; height: auto; }

.grid line { stroke: var(--border-light); stroke-width: 1; }
.grid .axis-l { fill: var(--text-muted); font-size: 11px; font-family: var(--font-mono); }

.line { fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

.x-axis text { fill: var(--text-muted); font-size: 11px; font-family: var(--font-mono); }
.hover-line { stroke: var(--text-muted); stroke-width: 1; stroke-dasharray: 3 3; opacity: 0.7; }

.tip {
  position: absolute;
  top: 44%;
  z-index: 3;
  min-width: 186px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: var(--shadow-md);
  pointer-events: none;
}
.tip-date { font-size: 11px; font-weight: 650; color: var(--text-primary); margin-bottom: 5px; }
.tip-row {
  display: grid;
  grid-template-columns: 8px 1fr auto;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.9;
}
.tip-row i { width: 7px; height: 7px; border-radius: 50%; display: block; }
.tip-row span { color: var(--text-primary); font-family: var(--font-mono); }
.empty { padding: 60px 0; text-align: center; font-size: 12px; color: var(--text-muted); }
</style>
