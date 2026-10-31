<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Loader2, Save, Settings2, X } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import type { RoutingConfigResponse } from '@/types'

interface RoleForm {
  role: string
  label: string
  model: string
  api_base: string
  api_key: string
  max_tokens: number
  reasoning_effort: string
  api_key_masked: string
  api_key_set: boolean
  effective_model: string
  is_override: boolean
  testing: boolean
  test_ok: boolean | null
  test_text: string
}

const {
  getRoutingConfig,
  saveRoutingConfig,
  testRouting,
} = useTaskApi()

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const config = ref<RoutingConfigResponse | null>(null)
const roles = ref<RoleForm[]>([])

const testingAll = ref(false)
const bulk = ref({ model: '', api_base: '', api_key: '' })

const globalConfig = computed(() => config.value?.global)

function currentSnapshot() {
  return JSON.stringify(
    roles.value.map((item) => [
      item.model,
      item.api_base,
      item.api_key,
      item.max_tokens,
      item.reasoning_effort,
    ])
  )
}

const baseline = ref('')
const dirty = computed(() => baseline.value !== '' && currentSnapshot() !== baseline.value)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getRoutingConfig()
    config.value = data
    roles.value = data.roles.map((item) => ({
      role: item.role,
      label: item.label,
      model: item.model,
      api_base: item.api_base,
      api_key: '',
      max_tokens: item.max_tokens,
      reasoning_effort: item.reasoning_effort,
      api_key_masked: item.api_key_masked,
      api_key_set: item.api_key_set,
      effective_model: item.effective_model,
      is_override: item.is_override,
      testing: false,
      test_ok: null,
      test_text: '',
    }))
    baseline.value = currentSnapshot()
  } catch {
    error.value = '配置加载失败，请确认后端已启动'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await saveRoutingConfig(
      roles.value.map((item) => ({
        role: item.role,
        model: item.model.trim(),
        api_base: item.api_base.trim(),
        api_key: item.api_key.trim(),
        max_tokens: Number(item.max_tokens) || 0,
        reasoning_effort: item.reasoning_effort,
      }))
    )
    ElMessage.success('已保存，配置即时生效')
    await load()
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function testRole(item: RoleForm) {
  item.testing = true
  item.test_ok = null
  item.test_text = ''
  try {
    const result = await testRouting(item.role)
    item.test_ok = result.ok
    item.test_text = result.ok
      ? `${result.model} · ${result.elapsed_seconds}s`
      : result.error || '调用失败'
  } catch {
    item.test_ok = false
    item.test_text = '请求失败'
  } finally {
    item.testing = false
  }
}

async function testAll() {
  if (testingAll.value || !roles.value.length) return
  testingAll.value = true
  let ok = 0
  let failed = 0
  try {
    for (const item of roles.value) {
      await testRole(item)
      if (item.test_ok) ok += 1
      else failed += 1
    }
  } finally {
    testingAll.value = false
  }
  if (failed) ElMessage.warning(`测试完成：${ok} 个成功，${failed} 个失败`)
  else ElMessage.success(`全部 ${ok} 个角色连接正常`)
}

function applyBulk() {
  const model = bulk.value.model.trim()
  const apiBase = bulk.value.api_base.trim()
  const apiKey = bulk.value.api_key.trim()
  if (!model && !apiBase && !apiKey) {
    ElMessage.warning('请至少填写一项')
    return
  }
  for (const item of roles.value) {
    if (model) item.model = model
    if (apiBase) item.api_base = apiBase
    if (apiKey) item.api_key = apiKey
  }
  ElMessage.success('已填充到所有角色，保存后生效')
}

onMounted(() => {
  load()
})
</script>

<template>
  <div class="settings-page animate-in">
    <div class="page-header">
      <div>
        <div class="eyebrow"><Settings2 :size="13" /> Model Routing</div>
        <h1>模型配置</h1>
        <p>为每个角色指定模型与供应商，保存后立即生效</p>
      </div>
      <div class="header-actions">
        <button class="ghost-btn" :disabled="testingAll || loading" @click="testAll">
          <Loader2 v-if="testingAll" :size="14" class="spinning" />
          测试全部
        </button>
        <button class="save-btn" :disabled="saving || loading" @click="save">
          <Loader2 v-if="saving" :size="14" class="spinning" />
          <Save v-else :size="14" />
          保存配置
        </button>
      </div>
    </div>

    <div v-if="error" class="state-block error">{{ error }}</div>

    <template v-else>
      <div class="notice card">
        <strong>填写规则</strong>
        <span>模型留空表示沿用全局模型；API Key 留空表示保留已保存的值；Max Tokens 填 0 表示继承全局。测试按钮使用已保存的配置。</span>
      </div>

      <div class="bulk card">
        <div class="bulk-head">
          <h3>批量填充</h3>
          <span>把同一组参数写入全部角色，留空的项不覆盖。填充后需保存生效。</span>
        </div>
        <div class="bulk-grid">
          <input v-model="bulk.model" placeholder="模型，如 deepseek-flash" />
          <input v-model="bulk.api_base" placeholder="API Base，如 https://api.deepseek.com/v1" />
          <input v-model="bulk.api_key" type="password" placeholder="API Key" />
          <button class="ghost-btn primary" @click="applyBulk">应用到全部</button>
        </div>
      </div>

      <div v-if="globalConfig" class="global card">
        <div class="global-head">
          <h3>全局默认</h3>
          <span class="global-tag">只读 · 由 .env 提供</span>
        </div>
        <div class="global-grid">
          <div><span>模型</span><strong>{{ globalConfig.model }}</strong></div>
          <div><span>API Base</span><strong class="mono">{{ globalConfig.api_base }}</strong></div>
          <div><span>Max Tokens</span><strong>{{ globalConfig.max_tokens }}</strong></div>
        </div>
      </div>

      <div v-if="loading && !roles.length" class="state-block">正在加载配置...</div>

      <div v-else class="role-grid">
        <div v-for="item in roles" :key="item.role" class="role-card card">
          <div class="role-head">
            <div class="role-title">
              <h3>{{ item.label }}</h3>
              <code>{{ item.role }}</code>
            </div>
            <span :class="['badge', item.is_override ? 'custom' : 'inherit']">
              {{ item.is_override ? item.effective_model : '继承 · ' + item.effective_model }}
            </span>
          </div>

          <div class="field-grid">
            <label class="field">
              <span>模型</span>
              <input v-model="item.model" :placeholder="`留空继承 ${globalConfig?.model || ''}`" />
            </label>
            <label class="field">
              <span>Max Tokens</span>
              <input v-model.number="item.max_tokens" type="number" min="0" placeholder="0 表示继承" />
            </label>
            <label class="field span-2">
              <span>API Base</span>
              <input v-model="item.api_base" :placeholder="`留空继承 ${globalConfig?.api_base || ''}`" />
            </label>
            <label class="field span-2">
              <span>API Key</span>
              <input
                v-model="item.api_key"
                type="password"
                :placeholder="item.api_key_set ? `已配置 ${item.api_key_masked}，留空不修改` : '留空继承全局'"
              />
            </label>
            <label class="field span-2">
              <span>推理强度</span>
              <select v-model="item.reasoning_effort">
                <option value="">不指定</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
          </div>

          <div class="role-foot">
            <button class="test-btn" :disabled="item.testing" @click="testRole(item)">
              <Loader2 v-if="item.testing" :size="12" class="spinning" />
              测试连接
            </button>
            <span
              v-if="item.test_text"
              :class="['test-result', item.test_ok ? 'ok' : 'fail']"
              :title="item.test_text"
            >
              <component :is="item.test_ok ? Check : X" :size="12" />
              {{ item.test_text }}
            </span>
          </div>
        </div>
      </div>
    </template>

    <div v-if="dirty" class="save-bar">
      <span>有未保存的修改</span>
      <button class="save-btn" :disabled="saving" @click="save">
        <Loader2 v-if="saving" :size="14" class="spinning" />
        <Save v-else :size="14" />
        保存配置
      </button>
    </div>
  </div>
</template>

<style scoped>
.settings-page { padding-bottom: 88px; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.bulk { padding: 16px 20px; margin-bottom: 18px; }
.bulk-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.bulk-head h3 { font-size: 14px; font-weight: 650; }
.bulk-head span { font-size: 11px; color: var(--text-muted); }
.bulk-grid { display: grid; grid-template-columns: 1fr 1.5fr 1.2fr auto; gap: 10px; }
.bulk-grid input {
  height: 34px; padding: 0 10px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-primary);
  font-size: 12px; font-family: var(--font-sans); outline: none;
}
.bulk-grid input:focus { border-color: var(--accent); }
.save-bar {
  position: fixed; right: 24px; bottom: 24px;
  display: flex; align-items: center; gap: 14px;
  padding: 10px 16px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
  z-index: 20;
}
.save-bar span { font-size: 12px; color: var(--text-secondary); }
.page-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 20px;
}
.page-header h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 4px; }
.page-header p { font-size: 14px; color: var(--text-secondary); }
.eyebrow {
  display: flex; align-items: center; gap: 6px; margin-bottom: 7px;
  color: var(--accent); font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
}
.save-btn {
  display: inline-flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 16px; border: 1px solid var(--accent-dark);
  border-radius: 8px; background: var(--accent-dark); color: #fff;
  font-size: 13px; font-weight: 600; font-family: var(--font-sans); cursor: pointer;
}
.save-btn:hover { background: var(--accent); }
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.notice {
  padding: 12px 16px; margin-bottom: 16px;
  display: flex; gap: 8px; align-items: baseline;
  font-size: 12px; color: var(--text-secondary);
  background: var(--accent-subtle); border-color: var(--accent-subtle);
}
.notice strong { color: var(--accent); font-weight: 700; white-space: nowrap; }

.global { padding: 16px 20px; margin-bottom: 18px; }
.global-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.global-head h3 { font-size: 14px; font-weight: 650; }
.global-tag { font-size: 10px; color: var(--text-muted); }
.global-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.global-grid div { display: flex; flex-direction: column; gap: 2px; }
.global-grid span { font-size: 11px; color: var(--text-muted); }
.global-grid strong { font-size: 13px; font-weight: 600; }

/* ── Buttons ─────────────────────────────── */
.ghost-btn {
  display: inline-flex; align-items: center; gap: 5px;
  height: 30px; padding: 0 11px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 12px; font-family: var(--font-sans); cursor: pointer;
}
.ghost-btn:hover { border-color: var(--accent); color: var(--accent); }
.ghost-btn:disabled { opacity: 0.5; cursor: wait; }
.ghost-btn.primary { border-color: var(--accent); color: var(--accent); }

.role-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.role-card { padding: 16px 18px 14px; }
.role-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 10px; margin-bottom: 12px;
}
.role-title { display: flex; align-items: baseline; gap: 8px; }
.role-title h3 { font-size: 14px; font-weight: 650; }
.role-title code { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.badge {
  font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;
  white-space: nowrap; max-width: 55%; overflow: hidden; text-overflow: ellipsis;
}
.badge.inherit { background: var(--bg-primary); color: var(--text-muted); }
.badge.custom { background: var(--accent-subtle); color: var(--accent); }

.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field.span-2 { grid-column: 1 / -1; }
.field > span { font-size: 11px; color: var(--text-muted); }
.field input,
.field select {
  width: 100%; height: 34px; padding: 0 10px;
  border: 1px solid var(--border); border-radius: 6px;
  background: #fafbfc; color: var(--text-primary);
  font-size: 12px; font-family: var(--font-sans); outline: none;
  transition: border-color var(--transition-fast);
}
.field input:focus,
.field select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-subtle);
}

.role-foot { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.test-btn {
  display: inline-flex; align-items: center; gap: 5px;
  height: 28px; padding: 0 10px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 11px; font-family: var(--font-sans); cursor: pointer;
}
.test-btn:hover { border-color: var(--accent); color: var(--accent); }
.test-btn:disabled { opacity: 0.5; cursor: wait; }
.test-result {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; max-width: 70%; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.test-result.ok { color: var(--success); }
.test-result.fail { color: var(--danger); }

.mono { font-family: var(--font-mono); font-size: 11px; }
.spinning { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.state-block { padding: 40px 0; text-align: center; font-size: 13px; color: var(--text-muted); }
.state-block.error { color: var(--danger); }

@media (max-width: 900px) {
  .role-grid, .global-grid { grid-template-columns: 1fr; }
  .page-header { flex-direction: column; gap: 12px; }
}
</style>
