import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'
import DashboardView from './views/DashboardView.vue'
import CreateView from './views/CreateView.vue'
import ProjectView from './views/ProjectView.vue'
import ModelsView from './views/ModelsView.vue'
import PromptsView from './views/PromptsView.vue'
import SettingsView from './views/SettingsView.vue'
import TrashView from './views/TrashView.vue'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: DashboardView },
    { path: '/create', component: CreateView },
    { path: '/projects/:id', component: ProjectView },
    { path: '/models', component: ModelsView },
    { path: '/prompts', component: PromptsView },
    { path: '/settings', component: SettingsView },
    { path: '/trash', component: TrashView },
  ],
})

createApp(App).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
