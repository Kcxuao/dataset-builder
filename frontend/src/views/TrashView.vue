<script setup>
import { inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshRight, Delete } from '@element-plus/icons-vue'
import { api, notifyError } from '../api'

const router = useRouter()
const refreshProjects = inject('refreshProjects')
const projects = ref([])
async function load() { try { projects.value = await api('/api/projects?trash=true') } catch (error) { notifyError(error, ElMessage) } }
async function restore(project) {
  try { await api(`/api/projects/${project.id}/restore`, { method: 'POST' }); await refreshProjects(); await load(); ElMessage.success('数据集已恢复'); router.push(`/projects/${project.id}`) }
  catch (error) { notifyError(error, ElMessage) }
}
onMounted(load)
</script>

<template>
  <section class="section-card"><div class="section-heading"><div><h2>已移除的数据集</h2><span class="section-subtitle">来源、样本和导出记录仍保留在工作区</span></div></div><el-empty v-if="!projects.length" description="回收站是空的" :image-size="112" /><div v-else class="trash-list"><div v-for="project in projects" :key="project.id" class="trash-row"><div class="trash-symbol"><el-icon><Delete /></el-icon></div><div><strong>{{ project.name }}</strong><span>{{ project.sample_count }} 条样本 · {{ new Date(project.deleted_at).toLocaleString('zh-CN') }} 移入</span></div><el-button type="primary" plain :icon="RefreshRight" @click="restore(project)">恢复</el-button></div></div></section>
</template>
