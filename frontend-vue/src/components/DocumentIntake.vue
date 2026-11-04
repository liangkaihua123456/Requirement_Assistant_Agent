<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { AlertTriangle, FileText, Loader2, RefreshCw, Wand2, X } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { ExtractedDocument, ExtractApplyPayload } from '@/types'

const emit = defineEmits<{ (e: 'apply', payload: ExtractApplyPayload): void }>()

const { extractDocument } = useTaskApi()

const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const busy = ref(false)
const errorMsg = ref('')
const result = ref<ExtractedDocument | null>(null)
const editedText = ref('')
const fileName = ref('')
const elapsed = ref(0)
let timer: number | undefined

const ACCEPTED = ['.pdf', '.docx']
const MAX_MB = 20
const maxBytes = MAX_MB * 1024 * 1024

const kindLabel = computed(() => {
  if (!result.value) return ''
  return result.value.kind === 'pdf' ? 'PDF' : 'Word'
})

const metaText = computed(() => {
  if (!result.value) return ''
  const parts = [`${result.value.chars} 字`, `${result.value.elapsed_ms}ms`]
  if (result.value.pages) parts.unshift(`${result.value.pages} 页`)
  return parts.join(' · ')
})

onBeforeUnmount(stopTimer)

function startTimer() {
  elapsed.value = 0
  stopTimer()
  timer = window.setInterval(() => {
    elapsed.value = Math.round((elapsed.value + 0.1) * 10) / 10
  }, 100)
}

function stopTimer() {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

function pickFile() {
  if (busy.value) return
  fileInput.value?.click()
}

function onInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (file) void handleFile(file)
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (busy.value) return
  const file = event.dataTransfer?.files?.[0]
  if (file) void handleFile(file)
}

function reset() {
  result.value = null
  editedText.value = ''
  errorMsg.value = ''
  fileName.value = ''
  stopTimer()
}

function describeError(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: string }).message)
  }
  return '文档解析失败，请确认文件未加密且格式正确'
}

function hasExtension(name: string) {
  const lower = name.toLowerCase()
  return ACCEPTED.some((ext) => lower.endsWith(ext))
}

async function handleFile(file: File) {
  if (busy.value) return
  if (!hasExtension(file.name)) {
    ElMessage.warning('仅支持 PDF 与 DOCX 文件')
    return
  }
  if (file.size > maxBytes) {
    ElMessage.warning(`文档超过 ${MAX_MB}MB，请拆分后重试`)
    return
  }

  reset()
  fileName.value = file.name
  busy.value = true
  startTimer()

  try {
    const data = await extractDocument(file)
    result.value = data
    editedText.value = data.text
    if (!data.ok || !data.text) {
      errorMsg.value = data.warnings.join('；') || '未提取到文本'
    }
  } catch (error) {
    errorMsg.value = describeError(error)
  } finally {
    busy.value = false
    stopTimer()
  }
}

function lines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 1)
}

function applyStructured() {
  const text = editedText.value.trim()
  if (!text) {
    ElMessage.warning('内容为空，请先补充文本')
    return
  }
  const list = lines(text)
  emit('apply', {
    mode: 'structured',
    goal: list[0]?.slice(0, 180) || text.slice(0, 180),
    features: list.slice(1, 13),
    constraints: [],
    audience: '',
    text,
  })
  ElMessage.success('已填入结构化输入，可继续修改')
}

function applyFree() {
  const text = editedText.value.trim()
  if (!text) {
    ElMessage.warning('内容为空，请先补充文本')
    return
  }
  emit('apply', { mode: 'free', goal: '', features: [], constraints: [], audience: '', text })
  ElMessage.success('已填入自由输入，可继续修改')
}

function reRun() {
  fileInput.value?.click()
}
</script>

<template>
  <section class="intake">
    <div class="intake-head">
      <span class="intake-icon"><FileText :size="17" /></span>
      <div class="intake-copy">
        <h3>从文档提取需求</h3>
        <p>上传 PDF 或 Word，自动提取全文，可编辑后填入需求</p>
      </div>
      <span class="channel">PDF / DOCX</span>
    </div>

    <div
      class="dropzone"
      :class="{ dragging, busy }"
      @click="pickFile"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.docx"
        hidden
        @change="onInputChange"
      />
      <template v-if="busy">
        <Loader2 :size="20" class="spin" />
        <span>正在解析… {{ elapsed.toFixed(1) }}s</span>
        <span class="drop-hint">页数较多时会稍慢</span>
      </template>
      <template v-else>
        <FileText :size="20" />
        <span>点击选择或拖入文档</span>
        <span class="drop-hint">支持 PDF / DOCX，不超过 {{ MAX_MB }}MB；扫描版 PDF 需先做文字识别</span>
      </template>
    </div>

    <div v-if="errorMsg" class="notice error">
      <AlertTriangle :size="14" />
      <span>{{ errorMsg }}</span>
    </div>

    <div v-if="result" class="result">
      <div class="result-bar">
        <span class="source">{{ kindLabel }}</span>
        <span class="meta-text">{{ metaText }}</span>
        <span v-if="fileName" class="meta-name">{{ fileName }}</span>
        <button class="icon-btn" title="重新选择文档" @click.stop="reRun">
          <RefreshCw :size="14" />
        </button>
        <button class="icon-btn" title="清空结果" @click.stop="reset">
          <X :size="14" />
        </button>
      </div>

      <ul v-if="result.warnings.length" class="warnings">
        <li v-for="(warning, index) in result.warnings" :key="index">{{ warning }}</li>
      </ul>

      <textarea
        v-model="editedText"
        class="result-text"
        rows="8"
        placeholder="提取的文本会显示在这里，可直接修改后填入表单"
      />

      <div class="result-actions">
        <button class="primary" @click="applyStructured">
          <Wand2 :size="14" /> 填入结构化输入
        </button>
        <button class="ghost" @click="applyFree">填入自由输入</button>
        <button class="ghost" @click="reset">清空</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.intake {
  margin-bottom: 18px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, #ffffff 0%, #f8faff 100%);
}
.intake-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.intake-icon {
  display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; flex-shrink: 0;
  border-radius: 10px; color: var(--accent); background: var(--accent-subtle);
}
.intake-copy { flex: 1; min-width: 0; }
.intake-copy h3 { font-size: 13px; font-weight: 650; }
.intake-copy p { font-size: 11px; color: var(--text-muted); }
.channel {
  flex-shrink: 0; padding: 3px 9px; border-radius: 20px;
  font-size: 10px; font-weight: 600;
  color: var(--accent); background: var(--accent-subtle);
}

.dropzone {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 5px; padding: 20px 16px;
  border: 1.5px dashed #cfd8e6; border-radius: 10px;
  background: #fbfcfe; color: var(--text-secondary);
  font-size: 12.5px; text-align: center; cursor: pointer;
  transition: all var(--transition-fast);
}
.dropzone:hover, .dropzone.dragging { border-color: var(--accent); background: var(--accent-subtle); color: var(--accent); }
.dropzone.busy { cursor: wait; border-style: solid; border-color: #dbe4f4; }
.dropzone svg { color: var(--accent); }
.drop-hint { font-size: 11px; color: var(--text-muted); }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.notice { display: flex; align-items: flex-start; gap: 6px; margin-top: 10px; font-size: 11.5px; line-height: 1.6; }
.notice.error { padding: 8px 10px; border-radius: 8px; color: var(--danger); background: var(--danger-subtle); }

.result { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }
.result-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.result-meta { flex: 1; min-width: 0; }
.source { padding: 2px 8px; border-radius: 5px; font-size: 10px; font-weight: 600; background: var(--accent-subtle); color: var(--accent); }
.meta-text, .meta-name { font-size: 11px; color: var(--text-muted); }
.meta-name { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; flex-shrink: 0; margin-left: auto;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary); cursor: pointer;
}
.icon-btn + .icon-btn { margin-left: 0; }
.icon-btn:hover { border-color: var(--accent); color: var(--accent); }

.warnings {
  margin: 0 0 8px; padding: 8px 10px 8px 24px;
  border-radius: 8px; background: var(--warning-subtle);
  color: #8a5d00; font-size: 11.5px; line-height: 1.7;
}
.result-text {
  width: 100%; padding: 11px 13px;
  border: 1px solid var(--border); border-radius: 10px;
  background: #fff; color: var(--text-primary);
  font-family: var(--font-sans); font-size: 13px; line-height: 1.7;
  resize: vertical;
}
.result-text:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-subtle); }

.result-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.result-actions button {
  display: inline-flex; align-items: center; gap: 5px;
  height: 30px; padding: 0 12px;
  border-radius: 7px; font-size: 12px; font-family: var(--font-sans);
  cursor: pointer; transition: all var(--transition-fast);
}
.result-actions .primary { border: 1px solid var(--accent-dark); background: var(--accent-dark); color: #fff; font-weight: 600; }
.result-actions .primary:hover { background: var(--accent); }
.result-actions .ghost { border: 1px solid var(--border); background: var(--bg-card); color: var(--text-secondary); }
.result-actions .ghost:hover { border-color: var(--accent); color: var(--accent); }
</style>
