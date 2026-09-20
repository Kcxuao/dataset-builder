<script setup>
import { computed, inject, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Download, RefreshRight } from '@element-plus/icons-vue'
import { api, jsonOptions, notifyError } from '../api'

const route = useRoute()
const router = useRouter()
const projects = inject('projects')
const refreshProjects = inject('refreshProjects')
const project = computed(() => projects.value.find(item => item.id === route.params.id))
const run = ref(null)
const samples = ref([])
const page = ref(1)
const limit = 20
const loading = ref(false)
const busy = ref(false)
const detail = ref(null)
const drawer = ref(false)
const messages = ref([])
const downloadUrl = ref('')
const exportForm = reactive({ format: 'sharegpt', file_type: 'jsonl' })
let timer = null
const activeStatuses = new Set(['created', 'importing', 'parsing', 'splitting', 'generating', 'cleaning', 'validating'])
const statusNames = { created: '任务已创建', importing: '正在导入', parsing: '正在解析', splitting: '正在切分', generating: '正在生成', cleaning: '正在清洗', validating: '正在校验', ready_for_review: '等待审核', completed: '处理完成', failed: '构建失败', interrupted: '任务已中断' }
const progressPercent = computed(() => run.value?.total_items ? Math.min(100, Math.round(((run.value.completed_items + run.value.failed_items) / run.value.total_items) * 100)) : 0)
function sampleStatus(item) {
  if (item.is_deleted) return ['已删除', 'info']
  if (item.validation_status !== 'passed') return ['校验失败', 'danger']
  return { approved: ['已通过', 'success'], rejected: ['已拒绝', 'danger'], pending: ['待审核', 'warning'] }[item.review_status] || ['未知', 'info']
}
function excerpt(item) { return item.messages.find(message => message.role === 'user')?.content || item.messages[0]?.content || '空消息' }
async function loadSamples() {
  loading.value = true
  try { samples.value = await api(`/api/projects/${route.params.id}/samples?limit=${limit}&offset=${(page.value - 1) * limit}`) }
  catch (error) { notifyError(error, ElMessage) }
  finally { loading.value = false }
}
async function loadRun() {
  if (!project.value?.run_id) return
  try {
    const previous = run.value?.status
    run.value = await api(`/api/runs/${project.value.run_id}`)
    if (previous && activeStatuses.has(previous) && !activeStatuses.has(run.value.status)) { await loadSamples(); await refreshProjects() }
    if (activeStatuses.has(run.value.status)) timer = setTimeout(loadRun, 1300)
  } catch (error) { notifyError(error, ElMessage) }
}
async function reload() { clearTimeout(timer); run.value = null; await refreshProjects(); await Promise.all([loadSamples(), loadRun()]) }
async function openDetail(item) {
  try { detail.value = await api(`/api/samples/${item.id}`); messages.value = detail.value.messages.map(message => ({ ...message })); drawer.value = true }
  catch (error) { notifyError(error, ElMessage) }
}
async function saveMessages() {
  busy.value = true
  try {
    detail.value = await api(`/api/samples/${detail.value.id}/messages`, jsonOptions('PUT', { messages: messages.value }))
    await loadSamples(); ElMessage.success('修改已保存，样本已重置为待审核')
  } catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
}
async function review(status) {
  busy.value = true
  try { detail.value = await api(`/api/samples/${detail.value.id}/review`, jsonOptions('PATCH', { status })); await loadSamples(); ElMessage.success('审核状态已更新') }
  catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
}
async function toggleDeleted() {
  busy.value = true
  try { detail.value = await api(`/api/samples/${detail.value.id}/deleted`, jsonOptions('PATCH', { is_deleted: !detail.value.is_deleted })); await loadSamples(); ElMessage.success('样本状态已更新') }
  catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
}
async function bulk(action) {
  if (!samples.value.length) return
  try {
    if (action === 'delete') await ElMessageBox.confirm(`将本页 ${samples.value.length} 条样本软删除？`, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const result = await api(`/api/projects/${route.params.id}/samples/bulk`, jsonOptions('PATCH', { sample_ids: samples.value.map(item => item.id), action }))
    ElMessage({ type: result.skipped.length ? 'warning' : 'success', message: `已更新 ${result.updated_ids.length} 条，跳过 ${result.skipped.length} 条${result.skipped[0] ? `：${result.skipped[0].reason}` : ''}` })
    await loadSamples()
    if (detail.value) detail.value = await api(`/api/samples/${detail.value.id}`)
  } catch (error) { if (error !== 'cancel') notifyError(error, ElMessage) }
}
async function retry() {
  try { await api(`/api/projects/${route.params.id}/retry`, { method: 'POST' }); await reload(); ElMessage.success('失败内容块已开始重试') }
  catch (error) { notifyError(error, ElMessage) }
}
async function exportSamples() {
  busy.value = true
  try { const result = await api(`/api/projects/${route.params.id}/exports`, jsonOptions('POST', exportForm)); downloadUrl.value = result.download_url; ElMessage.success(`已导出 ${result.sample_count} 条样本`) }
  catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
}
async function trash() {
  try {
    await ElMessageBox.confirm(`将“${project.value?.name || '此数据集'}”移入回收站？`, '移入回收站', { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' })
    await api(`/api/projects/${route.params.id}`, { method: 'DELETE' }); await refreshProjects(); router.push('/'); ElMessage.success('数据集已移入回收站')
  } catch (error) { if (error !== 'cancel') notifyError(error, ElMessage) }
}
watch(() => route.params.id, reload)
onMounted(reload)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="project-actions"><el-button :icon="RefreshRight" @click="reload">刷新</el-button><el-button v-if="run?.failed_items" type="warning" :icon="RefreshRight" @click="retry">重试失败内容块</el-button><el-button type="danger" plain :icon="Delete" @click="trash">移入回收站</el-button></div>
  <section class="section-card progress-card">
    <div class="section-heading"><div><p class="eyebrow">BUILD PROGRESS</p><h2>{{ statusNames[run?.status] || '等待进度' }}</h2></div><strong class="progress-number">{{ run?.completed_items || 0 }} <span>/ {{ run?.total_items || 0 }}</span></strong></div>
    <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
    <div class="progress-meta"><span>已成功 {{ run?.completed_items || 0 }} 个内容块</span><span>失败 {{ run?.failed_items || 0 }} 个</span><span>生成 {{ run?.sample_count || 0 }} 条样本</span></div>
    <el-alert v-if="run?.error_message" :title="run.error_message" type="error" :closable="false" show-icon class="run-alert" />
    <el-alert v-if="run?.status === 'interrupted'" title="任务曾中断，可重试剩余内容块；切分前中断需要重新上传。" type="warning" :closable="false" show-icon class="run-alert" />
    <div v-if="run?.failed_chunks?.length" class="failed-chunks"><p v-for="chunk in run.failed_chunks" :key="chunk.id">内容块 {{ chunk.id.slice(0, 8) }}：{{ chunk.error }}</p></div>
  </section>
  <section class="section-card review-card">
    <div class="section-heading review-heading"><div><p class="eyebrow">REVIEW QUEUE</p><h2>样本审核</h2><span class="section-subtitle">当前页 {{ samples.length }} 条 · 可批量处理</span></div><div class="bulk-toolbar"><el-button size="small" type="success" plain :disabled="!samples.length" @click="bulk('approved')">本页通过</el-button><el-button size="small" plain :disabled="!samples.length" @click="bulk('rejected')">本页拒绝</el-button><el-button size="small" plain :disabled="!samples.length" @click="bulk('pending')">待审核</el-button><el-button size="small" type="danger" plain :disabled="!samples.length" @click="bulk('delete')">删除</el-button><el-button size="small" plain :disabled="!samples.length" @click="bulk('restore')">恢复</el-button></div></div>
    <el-table v-loading="loading" :data="samples" class="samples-table" stripe @row-click="openDetail">
      <el-table-column label="样本内容" min-width="340"><template #default="{ row }"><div class="sample-title">{{ excerpt(row) }}</div><small class="sample-id">#{{ row.id.slice(0, 8) }} · {{ row.messages.length }} 条消息</small></template></el-table-column>
      <el-table-column label="校验" width="110"><template #default="{ row }"><el-tag :type="row.validation_status === 'passed' ? 'success' : 'danger'" effect="plain" round>{{ row.validation_status === 'passed' ? '通过' : '失败' }}</el-tag></template></el-table-column>
      <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="sampleStatus(row)[1]" effect="light" round>{{ sampleStatus(row)[0] }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
    </el-table>
    <div class="table-pagination"><el-button :disabled="page === 1" @click="page--; loadSamples()">上一页</el-button><span>第 {{ page }} 页</span><el-button :disabled="samples.length < limit" @click="page++; loadSamples()">下一页</el-button></div>
  </section>
  <section class="section-card export-card"><div><p class="eyebrow">FINAL STEP</p><h2>导出训练数据</h2><p>仅导出校验通过、审核通过且未删除的样本。</p></div><div class="export-controls"><el-select v-model="exportForm.format"><el-option label="ShareGPT" value="sharegpt" /><el-option label="Alpaca" value="alpaca" /></el-select><el-select v-model="exportForm.file_type"><el-option label="JSONL" value="jsonl" /><el-option label="JSON" value="json" /></el-select><el-button type="primary" :loading="busy" :icon="Download" @click="exportSamples">生成文件</el-button><el-button v-if="downloadUrl" link type="primary" @click="window.open(downloadUrl, '_blank')">下载文件</el-button></div></section>
  <el-drawer v-model="drawer" :title="`样本 #${detail?.id?.slice(0, 8) || ''}`" size="min(680px, 100%)" class="sample-drawer">
    <template v-if="detail"><div class="drawer-status"><el-tag :type="sampleStatus(detail)[1]" round>{{ sampleStatus(detail)[0] }}</el-tag><span>来源内容块 #{{ detail.chunk_id.slice(0, 8) }}</span></div>
      <div class="drawer-section"><h3>消息内容</h3><div v-for="(message, index) in messages" :key="index" class="message-card"><div class="message-head"><el-select v-model="message.role"><el-option label="system" value="system" /><el-option label="user" value="user" /><el-option label="assistant" value="assistant" /></el-select><el-button text type="danger" @click="messages.splice(index, 1)">移除</el-button></div><el-input v-model="message.content" type="textarea" :rows="3" /></div><el-button text type="primary" @click="messages.push({ role: 'user', content: '' })">＋ 添加消息</el-button><el-button type="primary" :loading="busy" @click="saveMessages">保存修改</el-button></div>
      <div class="drawer-section"><h3>来源内容</h3><pre class="source-preview">{{ detail.chunk_content || '无来源内容' }}</pre></div>
      <div class="drawer-section"><h3>校验结果</h3><el-alert v-if="!detail.issues.length" title="结构与内容校验通过" type="success" :closable="false" show-icon /><el-alert v-for="issue in detail.issues" :key="issue.rule" :title="`${issue.rule}：${issue.message}`" type="warning" :closable="false" class="issue-alert" /></div>
    </template>
    <template #footer><div v-if="detail" class="drawer-actions"><el-button type="success" :icon="Check" :loading="busy" @click="review('approved')">通过</el-button><el-button :loading="busy" @click="review('rejected')">拒绝</el-button><el-button :loading="busy" @click="review('pending')">待审核</el-button><el-button type="danger" plain :loading="busy" @click="toggleDeleted">{{ detail.is_deleted ? '恢复样本' : '软删除' }}</el-button></div></template>
  </el-drawer>
</template>
