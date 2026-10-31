<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  AlertTriangle,
  ImagePlus,
  Loader2,
  RefreshCw,
  ScanText,
  Wand2,
  X,
} from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { ExtractedRequirement, ExtractStatus, ExtractApplyPayload } from '@/types'

const emit = defineEmits<{ (e: 'apply', payload: ExtractApplyPayload): void }>()

const { extractImage, getExtractStatus } = useTaskApi()

const status = ref<ExtractStatus | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const busy = ref(false)
const errorMsg = ref('')
const result = ref<ExtractedRequirement | null>(null)
const editedText = ref('')
const previewUrl = ref('')
const fileName = ref('')
const elapsed = ref(0)
let timer: number | undefined

const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/tiff']
const maxBytes = computed(() => status.value?.limits.max_bytes ?? 10 * 1024 * 1024)
const maxMB = computed(() => Math.round(maxBytes.value / 1024 / 1024))
const enabled = computed(() => status.value?.enabled !== false)

const channelLabel = computed(() => {
  if (!status.value) return ''
  if (status.value.vision_ready) return `视觉模型 ${status.value.vision_model}`
  if (status.value.ocr_ready) return '本地 OCR'
  return '通道不可用'
})

const sourceLabel = computed(() => {
  if (!result.value) return ''
  if (result.value.source === 'vision') return '视觉模型识别'
  if (result.value.source === 'ocr') return '本地 OCR 识别'
  return '未识别到内容'
})

onMounted(async () => {
  window.addEventListener('paste', onPaste)
  try {
    status.value = await getExtractStatus()
  } catch {
    // 状态接口失败不阻塞上传，后端会给出具体错误
    status.value = null
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  stopTimer()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

function onPaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        event.preventDefault()
        void handleFile(file)
      }
      return
    }
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

function reset() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
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
  const code = (error as { code?: string })?.code
  if (code === 'ECONNABORTED') return '识别超时，请换一张更清晰的图片或稍后重试'
  return '识别请求失败，请确认后端服务正常后重试'
}

async function handleFile(file: File) {
  if (busy.value) return
  if (!ACCEPTED.includes(file.type)) {
    ElMessage.warning('仅支持 JPG、PNG、WEBP、BMP 图片')
    return
  }
  if (file.size > maxBytes.value) {
    ElMessage.warning(`图片超过 ${maxMB.value}MB，请压缩后重试`)
    return
  }

  reset()
  fileName.value = file.name || '剪贴板图片'
  previewUrl.value = URL.createObjectURL(file)
  busy.value = true
  startTimer()

  try {
    const data = await extractImage(file)
    result.value = data
    editedText.value = data.text
    if (!data.ok) {
      errorMsg.value = data.warnings.join('；') || '未识别到文字，请改用更清晰的图片'
    }
  } catch (error) {
    errorMsg.value = describeError(error)
  } finally {
    busy.value = false
    stopTimer()
  }
}

function fallbackFeatures(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 1)
    .slice(0, 12)
}

function applyStructured() {
  const text = editedText.value.trim()
  if (!text) {
    ElMessage.warning('识别结果为空，请先手动补充内容')
    return
  }
  const current = result.value
  emit('apply', {
    mode: 'structured',
    goal: current?.goal?.trim() || text.slice(0, 180),
    features: current?.features?.length ? current.features : fallbackFeatures(text),
    constraints: current?.constraints ?? [],
    audience: current?.audience || '',
    text,
  })
  ElMessage.success('已填入结构化输入，可继续修改')
}

function applyFree() {
  const text = editedText.value.trim()
  if (!text) {
    ElMessage.warning('识别结果为空，请先手动补充内容')
    return
  }
  emit('apply', { mode: 'free', goal: '', features: [], constraints: [], audience: '', text })
  ElMessage.success('已填入自由输入，可继续修改')
}

function reRun() {
  if (!fileInput.value) return
  fileInput.value.click()
}
</script>

<template>
  <section v-if="enabled" class="intake">
    <div class="intake-head">
      <span class="intake-icon"><ScanText :size="17" /></span>
      <div class="intake-copy">
        <h3>从图片提取需求</h3>
        <p>需求截图、聊天记录、手写笔记都可以，识别后可编辑再提交</p>
      </div>
      <span v-if="channelLabel" class="channel" :class="{ warn: !status?.vision_ready && !status?.ocr_ready }">
        {{ channelLabel }}
      </span>
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
        accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff"
        hidden
        @change="onInputChange"
      />
      <template v-if="busy">
        <Loader2 :size="20" class="spin" />
        <span>正在识别… {{ elapsed.toFixed(1) }}s</span>
        <span class="drop-hint">通常 1–3 秒，图片较大时会稍慢</span>
      </template>
      <template v-else>
        <ImagePlus :size="20" />
        <span>点击选择、拖入图片，或按 Ctrl+V 粘贴截图</span>
        <span class="drop-hint">支持 JPG / PNG / WEBP / BMP，不超过 {{ maxMB }}MB</span>
      </template>
    </div>

    <div v-if="errorMsg" class="notice error">
      <AlertTriangle :size="14" />
      <span>{{ errorMsg }}</span>
    </div>

    <div v-if="result" class="result">
      <div class="result-bar">
        <img v-if="previewUrl" :src="previewUrl" class="thumb" alt="上传的图片" />
        <div class="result-meta">
          <span class="source" :class="result.source">{{ sourceLabel }}</span>
          <span class="meta-text">
            {{ result.image.width }}×{{ result.image.height }} · {{ result.elapsed_ms }}ms
            <template v-if="result.confidence"> · 置信度 {{ Math.round(result.confidence * 100) }}%</template>
          </span>
          <span v-if="fileName" class="meta-name">{{ fileName }}</span>
        </div>
        <button class="icon-btn" title="重新选择图片" @click.stop="reRun">
          <RefreshCw :size="14" />
        </button>
        <button class="icon-btn" title="清空识别结果" @click.stop="reset">
          <X :size="14" />
        </button>
      </div>

      <ul v-if="result.warnings.length" class="warnings">
        <li v-for="(warning, index) in result.warnings" :key="index">{{ warning }}</li>
      </ul>

      <textarea
        v-model="editedText"
        class="result-text"
        rows="7"
        placeholder="识别结果会显示在这里，可直接修改后填入表单"
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
.channel.warn { color: var(--warning); background: var(--warning-subtle); }

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
.thumb { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; border: 1px solid var(--border); }
.result-meta { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.source { padding: 2px 8px; border-radius: 5px; font-size: 10px; font-weight: 600; background: var(--bg-overlay); color: var(--text-secondary); }
.source.vision { background: var(--accent-subtle); color: var(--accent); }
.source.ocr { background: var(--success-subtle); color: var(--success); }
.source.none { background: var(--warning-subtle); color: var(--warning); }
.meta-text, .meta-name { font-size: 11px; color: var(--text-muted); }
.meta-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; flex-shrink: 0;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary); cursor: pointer;
}
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
