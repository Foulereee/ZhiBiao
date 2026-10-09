import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  root: 'renderer',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './renderer/src'),
    },
  },
  server: {
    port: 15168,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 默认代理到本地后端；指向远程服务器时设置环境变量 VITE_API_TARGET
        // 例（PowerShell）: $env:VITE_API_TARGET='http://39.106.251.153'; npm run electron:dev
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, './dist'),
    emptyOutDir: true,
  },
});
