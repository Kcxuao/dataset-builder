<script setup>
import { computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, Collection, Delete, Plus } from '@element-plus/icons-vue'
import { api, notifyError } from '../api'

const router = useRouter()
const projects = inject('projects')
const refreshProjects = inject('refreshProjects')
const totalSamples = computed(() => projects.value.reduce((sum, item) => sum + item.sample_count, 0))
const waiting = computed(() => projects.value.filter(item => item.run_status === 'ready_for_review').length)
const statusName = (status) => ({ ready_for_review: '等待审核', failed: '构建失败', generating: '正在生成', parsing: '正在解析' })[status] || (status ? '处理中' : '未开始')
async function trash(project) {
  try {
    await ElMessageBox.confirm(`将“${project.name}”移入回收站？来源、样本和导出记录都会保留。`, '移入回收站', { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' })
    await api(`/api/projects/${project.id}`, { method: 'DELETE' })
    await refreshProjects()
    ElMessage.success('数据集已移入回收站')
  } catch (error) { if (error !== 'cancel') notifyError(error, ElMessage) }
}
</script>

<template>
  <section class="hero-card">
    <div><span class="hero-kicker">BUILD BETTER DATA / 构建更好的数据</span><h2>把原始内容<br /><em>变成可用的训练样本。</em></h2><p>导入、生成、审核、导出，都在一个清晰的工作流里。</p><el-button class="hero-button" size="large" :icon="Plus" @click="router.push('/create')">创建数据集</el-button></div>
    <div class="hero-art" aria-hidden="true"><span class="art-node">原始文档</span><span class="art-line"></span><span class="art-node art-node-accent">训练样本</span><span class="art-orbit"></span></div>
  </section>
  <div class="metric-grid">
    <div class="metric-card"><span>数据集总数</span><strong>{{ projects.length }}</strong><small>当前工作区</small></div>
    <div class="metric-card"><span>样本总数</span><strong>{{ totalSamples }}</strong><small>包含所有审核状态</small></div>
    <div class="metric-card"><span>等待审核</span><strong>{{ waiting }}</strong><small>个数据集已完成生成</small></div>
  </div>
  <section class="section-card dashboard-list">
    <div class="section-heading"><div><p class="eyebrow">YOUR DATASETS</p><h2>最近的数据集</h2></div><el-button text type="primary" :icon="ArrowRight" @click="router.push('/create')">新建数据集</el-button></div>
    <el-empty v-if="!projects.length" description="还没有数据集，先导入一份文档" :image-size="104"><el-button type="primary" @click="router.push('/create')">开始创建</el-button></el-empty>
    <div v-else class="dataset-list">
      <div v-for="project in projects" :key="project.id" class="dataset-row">
        <div class="dataset-icon"><el-icon><Collection /></el-icon></div>
        <button class="dataset-main" type="button" @click="router.push(`/projects/${project.id}`)"><strong>{{ project.name }}</strong><span>{{ project.sample_count }} 条样本 · {{ statusName(project.run_status) }}</span></button>
        <el-tag :type="project.run_status === 'failed' ? 'danger' : project.run_status === 'ready_for_review' ? 'success' : 'info'" effect="light" round>{{ statusName(project.run_status) }}</el-tag>
        <el-button text type="danger" :icon="Delete" aria-label="移入回收站" @click="trash(project)" />
        <el-button text :icon="ArrowRight" aria-label="查看数据集" @click="router.push(`/projects/${project.id}`)" />
      </div>
    </div>
  </section>
</template>
