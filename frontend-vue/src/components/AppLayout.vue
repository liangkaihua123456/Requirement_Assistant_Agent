<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { LogOut, Menu } from '@lucide/vue'
import Sidebar from './Sidebar.vue'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const route = useRoute()
const { logout } = useAuth()
const sidebarCollapsed = ref(false)

const pageTitles: Record<string, string> = {
  dashboard: '仪表盘',
  create: '创建任务',
  history: '历史任务',
  detail: '任务详情',
  stats: '使用统计',
  settings: '模型配置',
}

const currentTitle = computed(() => {
  const name = (route.name as string) || 'dashboard'
  return pageTitles[name] || name
})

function handleLogout() {
  logout()
  router.replace({ name: 'login' })
}

function navigate(name: string) {
  if (['create', 'history', 'dashboard', 'stats', 'settings'].includes(name)) {
    router.push({ name })
  }
}
</script>

<template>
  <div class="app-shell">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <button class="icon-btn" @click="sidebarCollapsed = !sidebarCollapsed">
          <Menu :size="20" />
        </button>
        <span class="header-brand">
          <span class="brand-icon" aria-hidden="true">A</span>
          <span class="brand-copy">
            <strong>Agent</strong>
            <small>需求交付</small>
          </span>
        </span>
        <span class="header-sep">/</span>
        <span class="header-page">{{ currentTitle }}</span>
      </div>
      <div class="header-right">
        <span class="status-dot" title="API 已连接"></span>
        <span class="header-status">API v1.0</span>
        <button class="logout-btn" type="button" @click="handleLogout">
          <LogOut :size="14" />
          退出
        </button>
      </div>
    </header>

    <div class="app-body">
      <!-- Sidebar -->
      <aside :class="['app-sidebar', { collapsed: sidebarCollapsed }]">
        <Sidebar :collapsed="sidebarCollapsed" @navigate="navigate" />
      </aside>

      <!-- Main Content -->
      <main :class="['app-main', { 'app-main-warm': route.name === 'create' }]">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}

/* ── Header ──────────────────────────────── */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 68px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.86);
  border-bottom: 1px solid rgba(214, 222, 236, 0.9);
  backdrop-filter: blur(16px);
  flex-shrink: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.icon-btn:hover {
  background: var(--bg-overlay);
  color: var(--text-primary);
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-primary);
}
.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.05;
}
.brand-copy strong {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.03em;
}
.brand-copy small {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.brand-icon {
  color: #fff;
  display: flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  background: linear-gradient(145deg, #5b8cff 0%, #6d4dff 100%);
  box-shadow: 0 8px 16px rgba(77, 92, 255, 0.28);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.04em;
}

.header-sep {
  color: var(--border);
  font-size: 18px;
  font-weight: 100;
}

.header-page {
  color: var(--text-secondary);
  font-size: 14px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 4px var(--success-subtle);
}

.header-status {
  font-size: 12px;
  color: var(--text-muted);
}
.logout-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  padding: 4px 8px 4px 6px;
  border: none;
  border-left: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.logout-btn:hover { color: var(--text-primary); }

/* ── Body ─────────────────────────────────── */
.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Sidebar ──────────────────────────────── */
.app-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), #f7f9fd 100%);
  border-right: 1px solid rgba(214, 222, 236, 0.9);
  transition: width var(--transition-base);
  overflow-y: auto;
  overflow-x: hidden;
}
.app-sidebar.collapsed {
  width: 64px;
}

/* ── Main ─────────────────────────────────── */
.app-main {
  flex: 1;
  overflow-y: auto;
  padding: 36px 44px 56px;
  max-width: none;
  margin: 0;
  width: 100%;
}
.app-main-warm {
  background: var(--bg-primary);
}

.app-main > :deep(*) {
  max-width: 1180px;
  margin-left: auto;
  margin-right: auto;
}

@media (max-width: 760px) {
  .app-header { padding: 0 14px; }
  .header-sep, .header-page, .header-status { display: none; }
  .app-sidebar { width: 64px; }
  .app-main { padding: 24px 16px 40px; }
}

/* ── Page Transition ──────────────────────── */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
