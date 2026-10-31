<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, KeyRound, User } from '@lucide/vue'
import { useAuth, authErrorMessage } from '@/composables/useAuth'

const router = useRouter()
const { forgotPassword } = useAuth()

const account = ref('')
const error = ref('')
const message = ref('')
const devToken = ref('')
const submitting = ref(false)

async function handleSubmit() {
  error.value = ''
  message.value = ''
  devToken.value = ''
  if (!account.value.trim()) {
    error.value = '请输入用户名或邮箱'
    return
  }
  submitting.value = true
  try {
    const data = await forgotPassword(account.value.trim())
    message.value = data.message
    if (data.reset_token) devToken.value = data.reset_token
  } catch (e: any) {
    error.value = authErrorMessage(e, '提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

function goReset() {
  router.push({ name: 'reset-password', query: devToken.value ? { token: devToken.value } : {} })
}
</script>

<template>
  <div class="page">
    <form class="card" @submit.prevent="handleSubmit">
      <h2>找回密码</h2>
      <p class="desc">输入你的用户名或邮箱</p>

      <label>
        <span><User :size="15" /> 用户名 / 邮箱</span>
        <input v-model="account" type="text" placeholder="请输入用户名或邮箱" :disabled="submitting" />
      </label>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div v-if="message" class="ok" role="status">
        <p>{{ message }}</p>
        <div v-if="devToken" class="dev">
          <p class="dev-title">开发环境重置令牌：</p>
          <code>{{ devToken }}</code>
        </div>
        <button v-if="message" type="button" class="link-btn" @click="goReset">
          继续重置密码 <ArrowRight :size="15" />
        </button>
      </div>

      <button class="submit" type="submit" :disabled="submitting">
        <KeyRound :size="16" /> 获取重置方式
      </button>
      <p class="foot"><router-link to="/login">返回登录</router-link></p>
    </form>
  </div>
</template>

<style scoped>
.page { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; background: linear-gradient(165deg, #fff8e1 0%, #f4f7ff 48%, #fff 100%); }
.card { width: min(440px, 100%); padding: 36px 32px; border: 1px solid rgba(255,255,255,0.7); border-radius: 22px; background: #fff; box-shadow: 0 24px 60px rgba(48,62,120,0.12); }
.card h2 { margin: 0; font-size: 24px; letter-spacing: -0.02em; }
.desc { margin: 6px 0 24px; color: #6b7280; font-size: 14px; }
label { display: block; margin-bottom: 14px; }
label span { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: 13px; font-weight: 650; color: #374151; }
input { width: 100%; height: 44px; padding: 0 14px; box-sizing: border-box; border: 1px solid #e4e8f2; border-radius: 12px; background: #f8f9fc; font: inherit; font-size: 14px; color: #111827; }
input:focus { outline: none; border-color: #6d86f5; background: #fff; box-shadow: 0 0 0 4px rgba(49,87,230,0.12); }
.error { margin: 4px 0 12px; padding: 10px 12px; border-radius: 10px; background: #fff0f2; color: #d23b55; font-size: 13px; }
.ok { margin: 4px 0 14px; padding: 12px; border-radius: 12px; background: #f0f7ff; color: #2b6cb0; font-size: 13px; }
.ok p { margin: 0 0 8px; }
.dev-title { font-weight: 600; margin: 6px 0 4px; }
code { display: block; padding: 8px 10px; border-radius: 8px; background: #0f172a; color: #a5f3fc; word-break: break-all; font-size: 12px; }
.link-btn { margin-top: 10px; display: inline-flex; align-items: center; gap: 6px; border: none; background: transparent; color: #3157e6; font-weight: 650; cursor: pointer; font-size: 13px; }
.submit { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; height: 46px; margin-top: 6px; border: none; border-radius: 12px; background: linear-gradient(90deg, #3157e6, #6d4dff); color: #fff; font: inherit; font-size: 15px; font-weight: 700; cursor: pointer; }
.submit:disabled { opacity: 0.7; cursor: default; }
.foot { margin-top: 16px; text-align: center; font-size: 13px; color: #6b7280; }
.foot a { color: #3157e6; font-weight: 600; text-decoration: none; }
</style>
