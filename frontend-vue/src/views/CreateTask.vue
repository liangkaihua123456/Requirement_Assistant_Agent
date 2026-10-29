<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Component } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, BookOpen, Check, ChevronDown, ChevronRight, FileText, GraduationCap, LayoutDashboard, Receipt, Send, ShieldCheck, ShoppingBag, Sparkles, Stethoscope, Users } from '@lucide/vue'
import { useTaskApi } from '@/composables/useTaskApi'
import { useTaskStore } from '@/stores/task'
import ImageIntake from '@/components/ImageIntake.vue'
import type { ExtractApplyPayload, PreflightResult, RequirementTemplate } from '@/types'

const router = useRouter()
const { createTask, listTemplates, createTemplate, runPreflight } = useTaskApi()
const store = useTaskStore()

const mode = ref<'structured' | 'free'>('structured')
const goal = ref('')
const features = ref('')
const constraints = ref('')
const nonFunctional = ref('')
const audience = ref('')
const userInput = ref('')
const showPreview = ref(false)
const submitting = ref(false)
const savedTemplates = ref<RequirementTemplate[]>([])
const selectedTemplate = ref<number | ''>('')
const preflight = ref<PreflightResult | null>(null)
const checking = ref(false)

async function loadTemplates() {
  try {
    savedTemplates.value = await listTemplates()
  } catch {
    // Templates are optional.
  }
}

function applyTemplate(id: number | '') {
  if (id === '') return
  const template = savedTemplates.value.find((item) => item.id === id)
  if (!template) return
  userInput.value = template.content
  mode.value = 'free'
}

async function checkModels() {
  checking.value = true
  preflight.value = null
  try {
    preflight.value = await runPreflight()
    if (preflight.value.ok) ElMessage.success('核心角色模型均可用')
    else ElMessage.warning(`以下角色不可用：${preflight.value.failed_roles.join('、')}`)
  } catch {
    ElMessage.error('预检失败，请确认后端已启动')
  } finally {
    checking.value = false
  }
}

onMounted(loadTemplates)

interface Template {
  label: string
  category: string
  icon: Component
  tone: string
  text: string
  goal: string
  features: string[]
}

const templates: Template[] = [
  {
    label: '用户登录系统',
    category: '认证与安全',
    icon: ShieldCheck,
    tone: 'blue',
    text: '设计一个用户认证系统，支持邮箱注册登录、JWT 令牌认证、密码加密存储、密码重置功能，需要提供完整的 RESTful API，高并发支持。',
    goal: '设计一个用户认证系统，为业务系统提供统一的注册、登录与凭证管理能力，满足高并发场景。',
    features: ['邮箱注册与登录', 'JWT 令牌签发与校验', '密码加密存储', '密码重置流程', '登录失败风控与审计'],
  },
  {
    label: '电商平台',
    category: '交易平台',
    icon: ShoppingBag,
    tone: 'orange',
    text: '设计一个 B2C 电商平台，包括商品管理（CRUD）、购物车模块、订单管理、支付对接（支付宝/微信）、用户评价系统、后台管理面板。',
    goal: '构建一个面向消费者的 B2C 电商平台，完成从商品浏览到下单支付的完整交易闭环。',
    features: ['商品管理', '购物车', '订单管理', '支付对接（支付宝/微信）', '用户评价', '后台管理面板'],
  },
  {
    label: '在线教育',
    category: '内容与学习',
    icon: GraduationCap,
    tone: 'green',
    text: '设计一个在线教育平台，支持视频课程发布和播放、作业提交与批改、学习进度跟踪、在线考试系统、师生互动讨论区。',
    goal: '构建一个在线教育平台，支撑课程发布、学习过程跟踪与教学互动。',
    features: ['视频课程发布与播放', '作业提交与批改', '学习进度跟踪', '在线考试', '师生讨论区'],
  },
  {
    label: '项目管理工具',
    category: '团队协作',
    icon: LayoutDashboard,
    tone: 'violet',
    text: '设计一个团队项目管理工具，支持看板视图、任务分配与跟踪、甘特图时间线、团队协作讨论、文件共享和版本管理。',
    goal: '为中小团队提供项目协作工具，统一任务、排期与文档协作。',
    features: ['看板视图', '任务分配与跟踪', '甘特图时间线', '团队讨论', '文件共享与版本管理'],
  },
  {
    label: '医疗问诊系统',
    category: '医疗健康',
    icon: Stethoscope,
    tone: 'rose',
    text: '设计一个在线医疗问诊系统，支持患者预约挂号、图文与视频问诊、电子病历、处方开具、医生排班，以及问诊记录查询。',
    goal: '构建在线医疗问诊系统，连接患者与医生，覆盖预约、问诊与病历留存。',
    features: ['预约挂号', '图文与视频问诊', '电子病历', '处方开具', '医生排班', '问诊记录查询'],
  },
  {
    label: '财税系统',
    category: '财务税务',
    icon: Receipt,
    tone: 'teal',
    text: '设计一个中小企业财税系统，支持发票识别入账、收支流水、增值税测算、三大报表、报税清单整理，并在人工确认后提交申报。',
    goal: '为中小企业提供财税管理工具，完成票据入账、报表生成与报税准备。',
    features: ['发票识别入账', '收支流水', '增值税测算', '三大报表', '报税清单整理', '人工确认后提交申报'],
  },
]

const workflowSteps = ['需求澄清', '方案设计', '工程实现', '智能评审', '交付打包']

function toBullets(value: string) {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => (line.startsWith('-') ? line : `- ${line}`))
    .join('\n')
}

const composedInput = computed(() => {
  const blocks: string[] = []
  const push = (title: string, body: string) => {
    const text = body.trim()
    if (text) blocks.push(`【${title}】\n${text}`)
  }
  push('产品目标', goal.value)
  push('核心功能', toBullets(features.value))
  push('约束条件', toBullets(constraints.value))
  push('非功能需求', toBullets(nonFunctional.value))
  push('目标用户', audience.value)
  return blocks.join('\n\n')
})

const payload = computed(() => (mode.value === 'structured' ? composedInput.value : userInput.value.trim()))
const charCount = computed(() => (mode.value === 'structured' ? composedInput.value.length : userInput.value.length))
const canSubmit = computed(() => payload.value.length > 0)

async function saveTemplate() {
  const content = payload.value
  if (!content) {
    ElMessage.warning('请先填写需求内容')
    return
  }
  let name = ''
  try {
    const result = await ElMessageBox.prompt('模板名称', '保存为模板', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：电商下单流程',
      inputValidator: (value: string) => (value?.trim() ? true : '名称不能为空'),
    })
    name = result.value.trim()
  } catch {
    return
  }
  try {
    const template = await createTemplate(name, content)
    savedTemplates.value.unshift(template)
    ElMessage.success('模板已保存')
  } catch {
    ElMessage.error('保存模板失败')
  }
}

function useTemplate(template: Template) {
  mode.value = 'structured'
  goal.value = template.goal
  features.value = template.features.join('\n')
  constraints.value = ''
  nonFunctional.value = ''
  audience.value = ''
}

function applyExtraction(payload: ExtractApplyPayload) {
  if (payload.mode === 'free') {
    mode.value = 'free'
    userInput.value = payload.text
    return
  }
  mode.value = 'structured'
  if (payload.goal) goal.value = payload.goal
  if (payload.features.length) features.value = payload.features.join('\n')
  if (payload.constraints.length) constraints.value = payload.constraints.join('\n')
  if (payload.audience) audience.value = payload.audience
}

async function handleSubmit() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  try {
    const resp = await createTask(payload.value)
    store.setTaskId(resp.task_id)
    store.setTaskStatus('queued')
    ElMessage.success('任务已创建，正在启动协作流程')
    router.push({ name: 'detail', params: { id: resp.task_id } })
  } catch {
    ElMessage.error('创建失败，请检查后端服务是否运行')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="create-page animate-in">
    <div class="page-header">
      <div>
        <div class="eyebrow"><Sparkles :size="13" /> Agent Studio</div>
        <h1>创建任务</h1>
        <p>描述你的业务需求，AI 智能体团队将自动完成全流程交付</p>
      </div>
    </div>

    <div class="composer-grid">
      <div class="input-card card">
        <div class="card-heading">
          <span class="heading-icon"><FileText :size="18" /></span>
          <div>
            <h2>描述你的需求</h2>
            <p>目标、核心功能、约束越明确，交付越少返工</p>
          </div>
        </div>

        <div class="mode-switch">
          <button :class="['mode-btn', { active: mode === 'structured' }]" @click="mode = 'structured'">
            结构化输入
          </button>
          <button :class="['mode-btn', { active: mode === 'free' }]" @click="mode = 'free'">
            自由输入
          </button>
        </div>

        <ImageIntake @apply="applyExtraction" />

        <div class="tool-row">
          <el-select
            v-model="selectedTemplate"
            placeholder="从模板填充"
            size="small"
            clearable
            style="width: 190px"
            @change="applyTemplate"
          >
            <el-option
              v-for="t in savedTemplates"
              :key="t.id"
              :label="t.name"
              :value="t.id"
            />
          </el-select>
          <button class="ghost-btn" @click="saveTemplate">保存为模板</button>
          <button class="ghost-btn" :disabled="checking" @click="checkModels">
            {{ checking ? '检查中…' : '检查模型可用性' }}
          </button>
          <span v-if="preflight" :class="['preflight-tag', preflight.ok ? 'ok' : 'fail']">
            {{ preflight.ok ? '模型可用' : '不可用：' + preflight.failed_roles.join('、') }}
          </span>
        </div>

        <template v-if="mode === 'structured'">
          <label class="field">
            <span class="field-label">产品目标 <em>必填</em></span>
            <el-input
              v-model="goal"
              type="textarea"
              :rows="3"
              placeholder="一句话说明要解决的问题和业务价值，例如：为中小餐饮门店提供扫码点单能力，减少人工记单错误。"
              class="custom-textarea"
              :disabled="submitting"
            />
          </label>

          <div class="field-grid">
            <label class="field">
              <span class="field-label">核心功能 <em>一行一条</em></span>
              <el-input
                v-model="features"
                type="textarea"
                :rows="6"
                placeholder="扫码进入菜单&#10;选规格加购物车&#10;在线支付&#10;商家接单与改库存"
                class="custom-textarea"
                :disabled="submitting"
              />
            </label>
            <div class="field-stack">
              <label class="field">
                <span class="field-label">约束条件</span>
                <el-input
                  v-model="constraints"
                  type="textarea"
                  :rows="2"
                  placeholder="技术栈、合规、预算、上线时间等"
                  class="custom-textarea"
                  :disabled="submitting"
                />
              </label>
              <label class="field">
                <span class="field-label">非功能需求</span>
                <el-input
                  v-model="nonFunctional"
                  type="textarea"
                  :rows="2"
                  placeholder="并发量、响应时间、可用性、审计要求等"
                  class="custom-textarea"
                  :disabled="submitting"
                />
              </label>
            </div>
          </div>

          <label class="field">
            <span class="field-label">目标用户</span>
            <el-input
              v-model="audience"
              placeholder="例如：门店店长与顾客"
              class="custom-single"
              :disabled="submitting"
            />
          </label>
        </template>

        <template v-else>
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="10"
            placeholder="例如：我想开发一个在线教育平台，支持视频课程、直播教学、作业提交和成绩管理..."
            class="custom-textarea"
            :disabled="submitting"
          />
        </template>

        <div v-if="mode === 'structured'" class="preview-block">
          <button class="preview-toggle" @click="showPreview = !showPreview">
            <component :is="showPreview ? ChevronDown : ChevronRight" :size="13" />
            预览提交内容
            <span class="preview-count">{{ composedInput.length }} 字</span>
          </button>
          <pre v-if="showPreview" class="preview-body">{{ composedInput || '尚未填写内容' }}</pre>
        </div>

        <div class="input-footer">
          <span class="char-count">{{ charCount }} 字 · 建议 50 字以上</span>
          <el-button class="submit-btn" :loading="submitting" :disabled="!canSubmit" @click="handleSubmit">
            <Send :size="15" /> 提交需求
          </el-button>
        </div>
      </div>

      <aside class="workflow-card card">
        <div class="workflow-title"><Users :size="18" /> 智能体协作流程</div>
        <p class="workflow-desc">提交后，系统会自动组织多角色智能体完成以下步骤。</p>
        <div class="workflow-list">
          <div v-for="(step, index) in workflowSteps" :key="step" class="workflow-step">
            <span class="step-index">{{ index + 1 }}</span>
            <span>{{ step }}</span>
            <Check :size="14" />
          </div>
        </div>
        <div class="workflow-tip"><BookOpen :size="15" /> 可在任务详情中实时查看过程并参与审批</div>
      </aside>
    </div>

    <div class="section-head">
      <div><h3 class="section-title">从模板快速开始</h3><p>选择常见场景后仍可继续编辑需求</p></div>
    </div>
    <div class="template-grid">
      <div
        v-for="tpl in templates" :key="tpl.label"
        :class="['tpl-card', 'card', `tpl-${tpl.tone}`]"
        @click="useTemplate(tpl)"
      >
        <span class="tpl-icon"><component :is="tpl.icon" :size="20" /></span>
        <div class="tpl-copy">
          <span class="tpl-category">{{ tpl.category }}</span>
          <span class="tpl-name">{{ tpl.label }}</span>
          <span class="tpl-preview">{{ tpl.goal.substring(0, 48) }}...</span>
        </div>
        <ArrowRight :size="17" class="tpl-arrow" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-row { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.ghost-btn {
  height: 32px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 12px; cursor: pointer;
}
.ghost-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.ghost-btn:disabled { opacity: 0.5; cursor: wait; }
.preflight-tag { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.preflight-tag.ok { background: var(--success-subtle); color: var(--success); }
.preflight-tag.fail { background: var(--danger-subtle); color: var(--danger); }
.page-header { margin-bottom: 26px; }
.page-header h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 4px; }
.page-header p { font-size: 14px; color: var(--text-secondary); }
.eyebrow { display: flex; align-items: center; gap: 6px; margin-bottom: 7px; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.composer-grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; margin-bottom: 34px; }
.input-card { padding: 24px; }
.card-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.card-heading h2 { font-size: 16px; font-weight: 650; }
.card-heading p { margin-top: 2px; font-size: 12px; color: var(--text-muted); }
.heading-icon { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 12px; color: var(--accent); background: var(--accent-subtle); }

.mode-switch {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  margin-bottom: 16px;
  border-radius: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
}
.mode-btn {
  padding: 5px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.mode-btn.active { background: var(--bg-card); color: var(--accent); box-shadow: var(--shadow-sm); }

.field { display: block; margin-bottom: 14px; }
.field-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.field-label em {
  font-style: normal;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 6px;
}
.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.field-grid .field { margin-bottom: 0; }
.field-stack { display: flex; flex-direction: column; gap: 14px; }

.custom-textarea :deep(.el-textarea__inner) {
  background: #fafbfc;
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.7;
  border-radius: 12px;
  padding: 15px 16px;
  resize: vertical;
  transition: border-color var(--transition-fast);
}
.custom-textarea :deep(.el-textarea__inner):focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-subtle);
}

.custom-single :deep(.el-input__wrapper) {
  height: 44px;
  padding: 4px 16px;
  background: #fafbfc;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: none;
}
.custom-single :deep(.el-input__wrapper.is-focus) {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-subtle);
}
.custom-single :deep(.el-input__inner) { font-size: 14px; }

.preview-block { margin-bottom: 12px; }
.preview-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  font-family: var(--font-sans);
  cursor: pointer;
}
.preview-toggle:hover { color: var(--accent); }
.preview-count { color: var(--text-muted); margin-left: 4px; }
.preview-body {
  margin-top: 8px;
  padding: 12px 14px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}
.char-count { font-size: 11px; color: var(--text-muted); }

.submit-btn {
  height: 36px;
  padding: 0 18px;
  font-weight: 600;
  font-size: 13px;
  gap: 6px;
  border-radius: 8px;
  background: var(--accent-dark);
  border: 1px solid var(--accent-dark);
  color: #fff;
}
.submit-btn:hover { background: var(--accent); border-color: var(--accent); }
.submit-btn:disabled { opacity: 0.4; }
.workflow-card { padding: 22px; background: linear-gradient(160deg, #fff 45%, #f3f7ff 100%); }
.workflow-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 650; }
.workflow-title svg { color: var(--accent); }
.workflow-desc { margin: 8px 0 18px; font-size: 12px; line-height: 1.7; color: var(--text-secondary); }
.workflow-list { display: flex; flex-direction: column; }
.workflow-step { position: relative; display: grid; grid-template-columns: 28px 1fr 16px; align-items: center; gap: 9px; min-height: 42px; font-size: 13px; color: var(--text-secondary); }
.workflow-step:not(:last-child)::after { position: absolute; top: 34px; bottom: -8px; left: 13px; width: 1px; content: ''; background: #dce6fb; }
.step-index { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; color: var(--accent); background: var(--accent-subtle); font-size: 11px; font-weight: 700; }
.workflow-step > svg { color: var(--success); }
.workflow-tip { display: flex; gap: 7px; margin-top: 17px; padding: 11px; border-radius: 10px; background: rgba(255,255,255,.72); color: var(--text-muted); font-size: 11px; line-height: 1.55; }

/* ── Templates ───────────────────────────── */
.section-head { margin-bottom: 12px; }
.section-title { font-size: 16px; font-weight: 650; }
.section-head p { margin-top: 2px; font-size: 12px; color: var(--text-muted); }
.template-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.tpl-card {
  display: flex; align-items: center; gap: 13px;
  min-width: 0;
  padding: 16px;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.tpl-card:hover { border-color: #bdcdf3; transform: translateY(-2px); }
.tpl-icon { display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; flex-shrink: 0; border-radius: 13px; background: var(--accent-subtle); color: var(--accent); }
.tpl-orange .tpl-icon { color: #d97706; background: #fff4e5; }
.tpl-green .tpl-icon { color: var(--success); background: var(--success-subtle); }
.tpl-violet .tpl-icon { color: #7955d9; background: #f2efff; }
.tpl-rose .tpl-icon { color: #d9486b; background: #fff0f4; }
.tpl-teal .tpl-icon { color: #0f8f86; background: #e7f8f6; }
.tpl-copy { display: flex; flex: 1; min-width: 0; flex-direction: column; }
.tpl-category { font-size: 10px; color: var(--text-muted); }
.tpl-name { font-size: 13px; font-weight: 600; }
.tpl-preview {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tpl-arrow { flex-shrink: 0; color: var(--text-muted); }
.tpl-card:hover .tpl-arrow { color: var(--accent); transform: translateX(2px); }

@media (max-width: 900px) {
  .composer-grid { grid-template-columns: 1fr; }
  .workflow-card { display: none; }
  .field-grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) { .page-header h1 { font-size: 24px; } .template-grid { grid-template-columns: 1fr; } .input-card { padding: 18px; } }
</style>
