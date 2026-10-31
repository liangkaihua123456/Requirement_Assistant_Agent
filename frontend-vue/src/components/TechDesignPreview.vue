<script setup lang="ts">
import { ref } from 'vue'
import { marked } from 'marked'
import { Code, ChevronDown, ChevronRight } from '@lucide/vue'
import type { TechnicalDesign } from '@/types'

defineProps<{ design: TechnicalDesign }>()
const expanded = ref(true)

function renderMarkdown(text: string): string { return marked(text) as string }

function buildDesignMarkdown(d: TechnicalDesign): string {
  let md = '# 技术设计方案\n\n'
  md += `## 架构概述\n${d.architecture_overview}\n\n`
  if (d.architecture_style) md += `**架构风格**: ${d.architecture_style}\n\n`
  if (d.services?.length) {
    md += '## 服务组件\n'
    for (const svc of d.services) { md += `### ${svc.name}\n${svc.responsibility}\n`; if (svc.tech_stack?.length) md += `\n**技术栈**: ${svc.tech_stack.join(', ')}\n`; md += '\n' }
  }
  const db = d.db_schema
  if (db) {
    md += '## 数据库设计\n'
    md += `**数据库类型**: ${db.database_type || 'PostgreSQL'}\n\n`
    for (const t of db.tables || []) {
      md += `### ${t.table_name}\n${t.description}\n\n`
      if (t.columns?.length) {
        md += '| 列名 | 类型 | 可空 | 描述 |\n|------|------|------|------|\n'
        for (const c of t.columns) md += `| ${c.name} | ${c.type} | ${c.nullable} | ${c.description || ''} |\n`
        md += '\n'
      }
      if (t.indexes?.length) md += `**索引**: ${t.indexes.join(', ')}\n\n`
    }
    if (db.relationships?.length) md += `**表间关系**: ${db.relationships.join(', ')}\n\n`
  }
  if (d.api_endpoints?.length) {
    md += '## API 设计\n'
    for (const a of d.api_endpoints) {
      md += `### ${a.auth_required ? '🔒' : '🔓'} \`${a.method}\` ${a.path}\n${a.description}\n`
      if (a.request_body) md += `\n**请求**: ${a.request_body}\n`
      if (a.response_body) md += `**响应**: ${a.response_body}\n`
      md += '\n'
    }
  }
  if (d.tech_risks?.length) { md += '## 技术风险\n'; for (const r of d.tech_risks) { md += `### ${r.risk} (${r.impact})\n`; if (r.mitigation) md += `**缓解**: ${r.mitigation}\n`; md += '\n' } }
  return md
}
</script>

<template>
  <div class="panel card">
    <div v-if="design._degraded" class="degraded-banner">
      该设计由系统按 PRD 自动降级生成（模型输出未能解析）。请复核接口与数据表，必要时点击「二次优化」。
    </div>
    <div class="panel-head" @click="expanded = !expanded" style="cursor:pointer; user-select:none">
      <Code :size="15" style="color:var(--accent)" />
      <span>技术设计方案</span>
      <span class="chip">{{ design.api_endpoints?.length || 0 }} APIs</span>
      <component :is="expanded ? ChevronDown : ChevronRight" :size="15" style="color:var(--text-muted); margin-left:auto" />
    </div>
    <div v-if="expanded" class="md-body" v-html="renderMarkdown(buildDesignMarkdown(design))" />
  </div>
</template>

<style scoped>
.degraded-banner {
  margin-bottom: 12px;
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--warning-subtle);
  color: var(--warning);
  font-size: 12px;
  line-height: 1.6;
}
.panel { padding: 16px; margin-bottom: 12px; }
.panel-head { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.chip {
  font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 4px;
  background: var(--accent-subtle); color: var(--accent);
}

.md-body { font-size: 13px; line-height: 1.7; color: var(--text-primary); }
.md-body :deep(h1) { font-size: 18px; margin: 13px 0 10px; }
.md-body :deep(h2) { font-size: 15px; margin: 12px 0 8px; padding-bottom: 5px; border-bottom: 1px solid var(--border); }
.md-body :deep(h3) { font-size: 13px; margin: 8px 0 6px; color: var(--accent); }
.md-body :deep(p), .md-body :deep(li) { font-size: 13px; color: var(--text-secondary); margin-bottom: 3px; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 22px; }
.md-body :deep(strong) { font-weight: 600; color: var(--text-primary); }
.md-body :deep(code) { background: var(--bg-primary); padding: 1px 5px; border-radius: 3px; font-family: var(--font-mono); font-size: 0.78rem; color: var(--accent); }
.md-body :deep(table) { border-collapse: collapse; width: 100%; margin: 10px 0; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 6px 10px; font-size: 12px; text-align: left; }
.md-body :deep(th) { background: var(--bg-primary); font-weight: 600; }
</style>
