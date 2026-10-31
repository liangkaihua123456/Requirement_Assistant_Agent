<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Lock, Mail, User } from '@lucide/vue'
import { useAuth, authErrorMessage } from '@/composables/useAuth'

const router = useRouter()
const { register } = useAuth()

const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const submitting = ref(false)

async function handleSubmit() {
  error.value = ''
  if (password.value !== confirm.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  try {
    await register({
      username: username.value.trim(),
      password: password.value,
      email: email.value.trim() || null,
    })
    router.replace('/')
  } catch (e: any) {
    error.value = authErrorMessage(e, '注册失败，请重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page">
    <form class="card" @submit.prevent="handleSubmit">
      <h2>注册账号</h2>
      <p class="desc">创建你的 Agent 工作台账号</p>

      <label>
        <span><User :size="15" /> 用户名</span>
        <input v-model="username" type="text" autocomplete="username" placeholder="至少 3 个字符" :disabled="submitting" />
      </label>
      <label>
        <span><Mail :size="15" /> 邮箱（可选，用于找回密码）</span>
        <input v-model="email" type="email" autocomplete="email" placeholder="you@example.com" :disabled="submitting" />
      </label>
      <label>
        <span><Lock :size="15" /> 密码</span>
        <input v-model="password" type="password" autocomplete="new-password" placeholder="至少 6 位" :disabled="submitting" />
      </label>
      <label>
        <span><Lock :size="15" /> 确认密码</span>
        <input v-model="confirm" type="password" autocomplete="new-password" placeholder="再次输入密码" :disabled="submitting" />
      </label>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <button class="submit" type="submit" :disabled="submitting">
        注册并登录 <ArrowRight :size="16" />
      </button>
      <p class="foot">已有账号？<router-link to="/login">返回登录</router-link></p>
    </form>
  </div>
</template>

<style scoped>
.page { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; background: linear-gradient(165deg, #fff8e1 0%, #f4f7ff 48%, #fff 100%); }
.card { width: min(420px, 100%); padding: 36px 32px; border: 1px solid rgba(255,255,255,0.7); border-radius: 22px; background: #fff; box-shadow: 0 24px 60px rgba(48,62,120,0.12); }
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
