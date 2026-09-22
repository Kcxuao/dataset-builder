import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('./views/DashboardView.vue') },
    { path: '/create', component: () => import('./views/CreateView.vue') },
    { path: '/projects/:id', component: () => import('./views/ProjectView.vue') },
    { path: '/models', component: () => import('./views/ModelsView.vue') },
    { path: '/prompts', component: () => import('./views/PromptsView.vue') },
    { path: '/settings', component: () => import('./views/SettingsView.vue') },
    { path: '/trash', component: () => import('./views/TrashView.vue') },
  ],
})

createApp(App).use(router).mount('#app')
