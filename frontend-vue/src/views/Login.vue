<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, Lock, Sparkles, User } from '@lucide/vue'
import { useAuth, authErrorMessage } from '@/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { login } = useAuth()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const error = ref('')
const submitting = ref(false)

const highlights = ['需求澄清', '方案与工程交付', '评审后打包']

async function handleSubmit() {
  error.value = ''
  submitting.value = true
  try {
    await login(username.value.trim(), password.value)
    const redirect =
      typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
        ? route.query.redirect
        : '/'
    router.replace(redirect)
  } catch (e: any) {
    error.value = authErrorMessage(e, '登录失败，请重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="orb orb-blue" />
    <div class="orb orb-violet" />

    <section class="login-card">
      <div class="brand-panel">
        <div class="brand-mark" aria-hidden="true">A</div>
        <p class="kicker"><Sparkles :size="14" /> Agent Studio</p>
        <h1>智能需求交付</h1>
        <p class="lead">把业务需求交给智能体团队，从澄清、方案到评审打包，在同一工作台完成。</p>
        <ul>
          <li v-for="item in highlights" :key="item">{{ item }}</li>
        </ul>
      </div>

      <form class="form-panel" @submit.prevent="handleSubmit">
        <p class="form-kicker">欢迎回来</p>
        <h2>登录工作台</h2>
        <p class="form-desc">使用账号密码进入需求交付平台。</p>

        <label>
          <span>用户名</span>
          <div class="field">
            <User :size="16" />
            <input
              v-model="username"
              type="text"
              name="username"
              autocomplete="username"
              placeholder="请输入用户名"
              :disabled="submitting"
            />
          </div>
        </label>

        <label>
          <span>密码</span>
          <div class="field">
            <Lock :size="16" />
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              name="password"
              autocomplete="current-password"
              placeholder="请输入密码"
              :disabled="submitting"
            />
            <button type="button" class="toggle" tabindex="-1" @click="showPassword = !showPassword">
              <EyeOff v-if="showPassword" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </label>

        <p v-if="error" class="error" role="alert">{{ error }}</p>

        <button class="submit" type="submit" :disabled="submitting">
          进入工作台
          <ArrowRight :size="16" />
        </button>

        <p class="hint">
          <router-link to="/register" class="hint-link">注册账号</router-link>
          <span aria-hidden="true">·</span>
          <router-link to="/forgot-password" class="hint-link">忘记密码？</router-link>
        </p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 32px 20px;
  overflow: hidden;
  background:
    radial-gradient(720px 320px at 12% 0%, rgba(255, 214, 102, 0.55), transparent 62%),
    linear-gradient(165deg, #fff8e1 0%, #f4f7ff 48%, #fff 100%);
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(8px);
  pointer-events: none;
}
.orb-blue {
  width: 280px;
  height: 280px;
  right: 8%;
  bottom: -80px;
  background: rgba(91, 140, 255, 0.18);
}
.orb-violet {
  width: 220px;
  height: 220px;
  left: 6%;
  top: 8%;
  background: rgba(109, 77, 255, 0.12);
}

.login-card {
  position: relative;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  width: min(960px, 100%);
  min-height: 560px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 28px;
  background: #fff;
  box-shadow: 0 30px 80px rgba(48, 62, 120, 0.12);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 48px 44px;
  color: #fff;
  background:
    radial-gradient(420px 240px at 100% 0%, rgba(255, 226, 140, 0.35), transparent 60%),
    linear-gradient(160deg, #3157e6 0%, #5b4dff 58%, #7a4dff 100%);
}
.brand-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58px;
  height: 58px;
  margin-bottom: auto;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.16);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.28);
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.04em;
}
.kicker {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  opacity: 0.86;
}
.brand-panel h1 {
  font-size: 36px;
  line-height: 1.15;
  letter-spacing: -0.04em;
}
.lead {
  max-width: 360px;
  margin-top: 14px;
  color: rgba(255, 255, 255, 0.86);
  font-size: 14px;
  line-height: 1.7;
}
.brand-panel ul {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 28px;
  list-style: none;
}
.brand-panel li {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 12px;
  font-weight: 600;
}

.form-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 52px 48px;
}
.form-kicker {
  color: #3157e6;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.form-panel h2 {
  margin-top: 8px;
  font-size: 28px;
  letter-spacing: -0.03em;
}
.form-desc {
  margin: 8px 0 28px;
  color: var(--text-secondary);
  font-size: 14px;
}

label {
  display: block;
  margin-bottom: 16px;
}
label span {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 650;
}
.field {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 50px;
  padding: 0 14px;
  border: 1px solid #e4e8f2;
  border-radius: 14px;
  background: #f8f9fc;
  color: #8b93a7;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.field:focus-within {
  border-color: #6d86f5;
  background: #fff;
  box-shadow: 0 0 0 4px rgba(49, 87, 230, 0.12);
  color: #3157e6;
}
.field input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 14px;
}
.field input::placeholder { color: #b0b6c4; }
.toggle {
  display: flex;
  border: none;
  background: transparent;
  color: #8b93a7;
  cursor: pointer;
}

.error {
  margin: -2px 0 14px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff0f2;
  color: #d23b55;
  font-size: 13px;
}

.submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 50px;
  margin-top: 6px;
  border: none;
  border-radius: 14px;
  background: linear-gradient(90deg, #3157e6, #6d4dff);
  color: #fff;
  font: inherit;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 12px 24px rgba(77, 92, 255, 0.28);
}
.submit:hover { filter: brightness(1.05); }
.submit:disabled { opacity: 0.7; cursor: default; }

.hint {
  margin-top: 18px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}
.hint strong { color: var(--text-secondary); font-weight: 700; }

@media (max-width: 820px) {
  .login-card { grid-template-columns: 1fr; min-height: 0; }
  .brand-panel { min-height: 240px; padding: 28px 24px; }
  .brand-panel h1 { font-size: 28px; }
  .form-panel { padding: 28px 22px 32px; }
}

.hint-link {
  color: #3157e6;
  text-decoration: none;
  font-weight: 600;
}
.hint-link:hover { text-decoration: underline; }
.hint { display: flex; gap: 10px; justify-content: center; align-items: center; }
</style>
