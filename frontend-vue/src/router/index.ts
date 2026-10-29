import { createRouter, createWebHistory } from 'vue-router'
import { isAuthenticated } from '@/composables/useAuth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/components/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/MainContent.vue'),
        },
        {
          path: 'create',
          name: 'create',
          component: () => import('@/views/CreateTask.vue'),
        },
        {
          path: 'history',
          name: 'history',
          component: () => import('@/views/TaskHistory.vue'),
        },
        {
          path: 'stats',
          name: 'stats',
          component: () => import('@/views/UsageStats.vue'),
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/ModelSettings.vue'),
        },
        {
          path: 'task/:id',
          name: 'detail',
          component: () => import('@/views/TaskDetail.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.meta.public) {
    if (isAuthenticated()) return { name: 'dashboard' }
    return true
  }
  if (!isAuthenticated()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
