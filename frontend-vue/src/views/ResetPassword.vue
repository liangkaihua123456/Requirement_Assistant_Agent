<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, KeyRound, Lock } from '@lucide/vue'
import { useAuth, authErrorMessage } from '@/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { resetPassword } = useAuth()

const token = ref(typeof route.query.token === 'string' ? route.query.token : '')
const password = ref('')
const confirm = ref('')
const error = ref('')
const submitting = ref(false)

async function handleSubmit() {
  error.value = ''
  if (!token.value.trim()) { error.value = '请填写重置令牌'; return }
  if (password.value !== confirm.value) { error.value = '两次输入的密码不一致'; return }
  submitting.value = true
  try {
    await resetPassword(token.value.trim(), password.value)
    router.replace('/login')
  } catch (e: any) {
    error.value = authErrorMessage(e, '重置失败，请重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page">
    <form class="card" @submit.prevent="handleSubmit">
      <h2>设置新密码</h2>
      <p class="desc">粘贴重置令牌并设置新密码</p>

      <label>
        <span><KeyRound :size="15" /> 重置令牌</span>
        <input v-model="token" type="text" placeholder="粘贴邮件中的重置令牌" :disabled="submitting" />
      </label>
      <label>
        <span><Lock :size="15" /> 新密码</span>
        <input v-model="password" type="password" autocomplete="new-password" placeholder="至少 6 位" :disabled="submitting" />
      </label>
      <label>
        <span><Lock :size="15" /> 确认新密码</span>
        <input v-model="confirm" type="password" autocomplete="new-password" placeholder="再次输入新密码" :disabled="submitting" />
      </label>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <button class="submit" type="submit" :disabled="submitting">
        重置密码 <ArrowRight :size="16" />
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
.submit { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; height: 46px; margin-top: 6px; border: none; border-radius: 12px; background: linear-gradient(90deg, #3157e6, #6d4dff); color: #fff; font: inherit; font-size: 15px; font-weight: 700; cursor: pointer; }
.submit:disabled { opacity: 0.7; cursor: default; }
.foot { margin-top: 16px; text-align: center; font-size: 13px; color: #6b7280; }
.foot a { color: #3157e6; font-weight: 600; text-decoration: none; }
</style>
