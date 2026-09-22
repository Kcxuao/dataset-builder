<script setup>
import { computed, nextTick, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, Collection, DataAnalysis, Delete, Menu, Plus, Setting, Tickets } from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { api, notifyError } from './api'

const router = useRouter()
const route = useRoute()
const projects = ref([])
const mobileMenu = ref(false)
const mobileMenuButton = ref(null)
const mobileMenuClose = ref(null)
const busy = ref(false)
const projectsLoaded = ref(false)
let projectsRequest = null
const headings = {
  '/': ['工作台', '从文档到可审核的训练数据'],
  '/create': ['新建数据集', '导入源文件并开始生成'],
  '/models': ['模型配置', '管理兼容 OpenAI 接口的模型'],
  '/prompts': ['提示词配置', '为不同生成任务准备稳定的提示词'],
  '/settings': ['处理设置', '设定之后创建任务的默认参数'],
  '/trash': ['回收站', '恢复暂时移除的数据集'],
}
const heading = computed(() => route.path.startsWith('/projects/')
  ? [projects.value.find(item => item.id === route.params.id)?.name || '数据集', '查看进度、审核样本并导出']
  : headings[route.path] || headings['/'])

async function loadProjects({ initial = false } = {}) {
  if (projectsRequest) return projectsRequest
  if (initial && !projectsLoaded.value) busy.value = true
  projectsRequest = api('/api/projects')
  try { projects.value = await projectsRequest }
  catch (error) { notifyError(error, ElMessage) }
  finally {
    projectsRequest = null
    projectsLoaded.value = true
    if (initial) busy.value = false
  }
}
function navigate(path) { mobileMenu.value = false; router.push(path) }
async function openMobileMenu() { mobileMenu.value = true; await nextTick(); mobileMenuClose.value?.focus() }
function closeMobileMenu() { mobileMenu.value = false; mobileMenuButton.value?.focus() }
function closeMenuOnEscape(event) { if (event.key === 'Escape' && mobileMenu.value) closeMobileMenu() }
provide('refreshProjects', loadProjects)
provide('projects', projects)
watch(() => route.fullPath, () => { mobileMenu.value = false })
onMounted(() => loadProjects({ initial: true }))
</script>

<template>
  <div class="app-shell" @keydown="closeMenuOnEscape">
    <aside id="workspace-sidebar" class="sidebar" :class="{ 'sidebar-open': mobileMenu }">
      <button class="brand" type="button" @click="navigate('/')">
        <span class="brand-symbol">D<span class="brand-spark">✦</span></span>
        <span><strong>Dataset Builder</strong><small>训练数据工作台</small></span>
      </button>
      <button ref="mobileMenuClose" class="mobile-menu-close" type="button" aria-label="关闭菜单"
        @click="closeMobileMenu">关闭</button>
      <div class="nav-caption">工作空间</div>
      <nav class="main-nav" aria-label="工作空间导航">
        <button :class="{ active: route.path === '/' }" @click="navigate('/')"><el-icon>
            <DataAnalysis />
          </el-icon>总览</button>
        <button :class="{ active: route.path === '/create' }" @click="navigate('/create')"><el-icon>
            <Plus />
          </el-icon>新建数据集</button>
      </nav>
      <div class="nav-caption nav-caption-projects">数据集 <span>{{ projects.length }}</span></div>
      <div class="project-nav" :aria-busy="busy">
        <div v-if="busy && !projects.length" class="nav-skeleton" aria-label="正在加载数据集">
          <span v-for="index in 3" :key="index"><i /><b /></span>
        </div>
        <button v-for="project in projects" :key="project.id"
          :class="{ active: route.path === `/projects/${project.id}` }" @click="navigate(`/projects/${project.id}`)">
          <el-icon>
            <Collection />
          </el-icon><span>{{ project.name }}</span><el-icon class="nav-arrow">
            <ArrowRight />
          </el-icon>
        </button>
        <p v-if="!projects.length && !busy" class="nav-empty">还没有数据集</p>
      </div>
      <div class="sidebar-footer">
        <div class="nav-caption">配置与管理</div>
        <nav class="main-nav" aria-label="配置导航">
          <button :class="{ active: route.path === '/models' }" @click="navigate('/models')"><el-icon>
              <Setting />
            </el-icon>模型配置</button>
          <button :class="{ active: route.path === '/prompts' }" @click="navigate('/prompts')"><el-icon>
              <Tickets />
            </el-icon>提示词配置</button>
          <button :class="{ active: route.path === '/settings' }" @click="navigate('/settings')"><el-icon>
              <Setting />
            </el-icon>处理设置</button>
          <button :class="{ active: route.path === '/trash' }" @click="navigate('/trash')"><el-icon>
              <Delete />
            </el-icon>回收站</button>
        </nav>
        <div class="sidebar-credit"><span class="status-dot"></span> 本地工作区</div>
      </div>
    </aside>
    <div v-if="mobileMenu" class="mobile-backdrop" @click="closeMobileMenu"></div>
    <el-config-provider :locale="zhCn">
      <div class="main-area">
        <header class="topbar">
        <button ref="mobileMenuButton" class="mobile-menu-button" type="button" aria-label="打开菜单"
          aria-controls="workspace-sidebar" :aria-expanded="mobileMenu" @click="openMobileMenu"><el-icon>
            <Menu />
          </el-icon></button>
        <div class="breadcrumbs">工作空间 <span>/</span> {{ heading[0] }}</div>
        <div class="topbar-right"><el-button type="primary" :icon="Plus" aria-label="新建数据集"
            @click="navigate('/create')">新建数据集</el-button></div>
        </header>
        <main class="content">
          <div class="page-intro">
            <div>
              <h1>{{ heading[0] }}</h1>
              <p>{{ heading[1] }}</p>
            </div>
          </div>
          <router-view />
        </main>
      </div>
    </el-config-provider>
  </div>
</template>
