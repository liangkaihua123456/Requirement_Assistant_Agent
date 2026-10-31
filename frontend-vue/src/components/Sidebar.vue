<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { LayoutDashboard, PlusCircle, History, BarChart3, Settings2 } from '@lucide/vue'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ navigate: [name: string] }>()

const route = useRoute()

const navItems = computed(() => [
  { key: 'dashboard', label: '仪表盘', icon: LayoutDashboard, active: route.name === 'dashboard' },
  { key: 'create', label: '创建任务', icon: PlusCircle, active: route.name === 'create' },
  { key: 'history', label: '历史任务', icon: History, active: route.name === 'history' || route.name === 'detail' },
  { key: 'stats', label: '使用统计', icon: BarChart3, active: route.name === 'stats' },
  { key: 'settings', label: '模型配置', icon: Settings2, active: route.name === 'settings' },
])
</script>

<template>
  <div class="sidebar">
    <nav class="sidebar-nav">
      <div
        v-for="item in navItems"
        :key="item.key"
        :class="['nav-item', { active: item.active }]"
        @click="emit('navigate', item.key)"
        :title="collapsed ? item.label : ''"
      >
        <component :is="item.icon" :size="18" class="nav-icon" />
        <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
      </div>
    </nav>

    <div class="sidebar-footer">
      <div v-if="!collapsed" class="footer-info">
        <span class="footer-dot" />
        <span class="footer-text">Agent 运行中</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 18px 12px;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 42px;
  padding: 9px 12px;
  border-radius: 10px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 14px;
  font-weight: 500;
  user-select: none;
}
.nav-item:hover {
  background: var(--bg-overlay);
  color: var(--text-primary);
}
.nav-item.active {
  background: linear-gradient(90deg, #edf3ff, #f6f3ff);
  color: #3157e6;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(79, 110, 247, 0.16);
}

.nav-icon { flex-shrink: 0; }
.nav-label { white-space: nowrap; overflow: hidden; }

/* ── Footer ──────────────────────────────── */
.sidebar-footer {
  margin-top: auto;
  padding: 16px 0 0 0;
  border-top: 1px solid var(--border-light);
}
.footer-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
}
.footer-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}
.footer-text {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
