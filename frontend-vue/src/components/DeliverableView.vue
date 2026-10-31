<script setup lang="ts">
import { ref } from 'vue'
import { PackageOpen, Download, Copy, Check, FileJson } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { TaskResult } from '@/types'

const props = defineProps<{ taskId: string }>()
const { getTaskResult } = useTaskApi()
const result = ref<TaskResult | null>(null)
const loading = ref(false)
const fetched = ref(false)
const copied = ref(false)

function download(kind: 'zip' | 'docx') {
  window.open(`/api/tasks/${props.taskId}/export/${kind}`, '_blank')
}

async function fetchResult() {
  loading.value = true
  try { result.value = await getTaskResult(props.taskId); fetched.value = true }
  catch { /* ignore */ }
  finally { loading.value = false }
}

async function copyResult() {
  if (!result.value) return
  await navigator.clipboard.writeText(JSON.stringify(result.value, null, 2))
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}
</script>

<template>
  <div class="panel card">
    <div class="panel-head">
      <PackageOpen :size="15" style="color:var(--success)" />
      <span>交付结果</span>
      <el-button class="btn-load" size="small" style="margin-left:8px" @click="download('zip')">
        <Download :size="12" style="margin-right:3px" /> ZIP
      </el-button>
      <el-button class="btn-load" size="small" @click="download('docx')">
        <Download :size="12" style="margin-right:3px" /> Word
      </el-button>
      <el-button v-if="!fetched" class="btn-load" size="small" :loading="loading" @click="fetchResult">
        <Download :size="12" style="margin-right:3px" /> 加载
      </el-button>
      <el-button v-if="fetched && result" text size="small" style="margin-left:8px" @click="copyResult">
        <Check v-if="copied" :size="12" /><Copy v-else :size="12" />
        {{ copied ? '已复制' : '复制' }}
      </el-button>
    </div>

    <div v-if="fetched && result">
      <el-collapse>
        <el-collapse-item title="需求澄清结果" name="clarified">
          <pre><code>{{ JSON.stringify(result.deliverable.clarified_requirement, null, 2) }}</code></pre>
        </el-collapse-item>
        <el-collapse-item title="PRD 产品方案" name="prd">
          <pre><code>{{ JSON.stringify(result.deliverable.prd_doc, null, 2) }}</code></pre>
        </el-collapse-item>
        <el-collapse-item title="技术设计方案" name="tech">
          <pre><code>{{ JSON.stringify(result.deliverable.technical_design, null, 2) }}</code></pre>
        </el-collapse-item>
        <el-collapse-item title="代码骨架" name="scaffold">
          <pre><code>{{ JSON.stringify(result.deliverable.code_scaffold, null, 2) }}</code></pre>
        </el-collapse-item>
        <el-collapse-item title="评审报告" name="review">
          <pre><code>{{ JSON.stringify(result.deliverable.review_result, null, 2) }}</code></pre>
        </el-collapse-item>
      </el-collapse>

      <div v-if="result.exported_files && Object.keys(result.exported_files).length" class="export-box">
        <h4>导出文件</h4>
        <ul>
          <li v-for="(path, name) in result.exported_files" :key="name">
            <FileJson :size="12" /> {{ name }}: {{ path }}
          </li>
        </ul>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-hint">点击「加载」查看任务完整交付物</div>
  </div>
</template>

<style scoped>
.panel { padding: 16px; margin-bottom: 12px; }
.panel-head { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; margin-bottom: 10px; }

.btn-load {
  margin-left: auto;
  background: var(--success-subtle);
  border: none;
  color: var(--success);
  font-weight: 600;
  font-size: 11px;
  border-radius: var(--radius-sm);
}
.btn-load:hover { opacity: 0.8; }

:deep(pre) { margin: 0; background: var(--bg-primary); border-radius: var(--radius-sm); padding: 12px; max-height: 300px; overflow-y: auto; }
:deep(code) { font-size: 10px; line-height: 1.6; color: var(--text-secondary); }

.export-box { margin-top: 12px; padding: 10px 12px; background: var(--bg-primary); border-radius: var(--radius-sm); }
.export-box h4 { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.export-box ul { list-style: none; }
.export-box li { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); display: flex; align-items: center; gap: 5px; margin-bottom: 2px; }

.empty-hint { font-size: 12px; color: var(--text-muted); padding: 8px 0; }

:deep(.el-collapse) { border: none; --el-collapse-header-height: 36px; }
:deep(.el-collapse-item__header) { color: var(--text-secondary); font-size: 12px; font-weight: 500; border-bottom: 1px solid var(--border); background: transparent; padding: 0 6px; height: 34px; line-height: 34px; }
:deep(.el-collapse-item__header:hover) { color: var(--text-primary); }
:deep(.el-collapse-item__wrap) { background: transparent; border: none; }
:deep(.el-collapse-item__content) { padding: 6px 0; }
</style>
