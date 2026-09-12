import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

// 无头环境里看不到控制台，把最后一个未捕获错误挂到 window 上便于自测取用
window.addEventListener('error', (e) => { window.__lastError = String(e.message || e.error) })
window.addEventListener('unhandledrejection', (e) => { window.__lastError = String(e.reason) })

createApp(App).mount('#app')
