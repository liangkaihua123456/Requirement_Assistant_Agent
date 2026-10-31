import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname)
  // 后端地址：默认 8000（与 README/start.bat 一致）。
  // 优先级：frontend-vue/.env.local 的 VITE_PROXY_TARGET
  //       > 进程环境变量 VITE_API_TARGET（远端部署习惯用）> 默认值
  const proxyTarget =
    env.VITE_PROXY_TARGET || process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      // 公网反代域名不固定时需放开，否则外网访问返回 403。
      allowedHosts: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
