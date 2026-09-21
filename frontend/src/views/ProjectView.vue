<script setup>
import { computed, inject, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Download, MagicStick, RefreshRight } from '@element-plus/icons-vue'
import { api, jsonOptions, notifyError } from '../api'

const route = useRoute()
const router = useRouter()
const projects = inject('projects')
const refreshProjects = inject('refreshProjects')
const project = computed(() => projects.value.find(item => item.id === route.params.id))
const run = ref(null)
const quality = ref(null)
const samples = ref([])
const page = ref(1)
const total = ref(0)
const filters = reactive({ review_status: '', validation_status: '', keyword: '' })
const limit = 20
const loading = ref(false)
const busy = ref(false)
const detail = ref(null)
const drawer = ref(false)
const messages = ref([])
const downloadUrl = ref('')
const exportForm = reactive({ format: 'sharegpt', file_type: 'jsonl' })
const augmentationDialog = ref(false)
const augmentationPreview = ref(null)
const augmentationLoading = ref(false)
const augmentationSources = ref([])
const augmentationPrompts = ref([])
const augmentationModels = ref([])
const augmentationForm = reactive({ strategies: ['rewrite', 'angle', 'scenario'], target_count: 100, keyword: '', source_document_ids: [], prompt_mode: 'template', prompt_id: '', custom_prompt: '', model_id: '' })
const augmentationStrategies = [
  { id: 'rewrite', name: '表达改写', description: '同一事实，不同问法和表达。' },
  { id: 'angle', name: '认知角度', description: '定义、原因、过程、比较、影响。' },
  { id: 'deepen', name: '难度深化', description: '增加约束与推理，不增加事实。' },
  { id: 'audience', name: '角色视角', description: '为不同受众组织解释。' },
  { id: 'scenario', name: '场景应用', description: '把知识落到具体任务中。' },
]
let timer = null
const activeStatuses = new Set(['created', 'importing', 'parsing', 'splitting', 'generating', 'augmenting', 'cleaning', 'validating'])
const statusNames = { created: '任务已创建', importing: '正在导入', parsing: '正在解析', splitting: '正在切分', generating: '正在生成', augmenting: '正在扩增', cleaning: '正在清洗', validating: '正在校验', ready_for_review: '等待审核', completed: '处理完成', failed: '构建失败', interrupted: '任务已中断' }
const progressPercent = computed(() => run.value?.total_items ? Math.min(100, Math.round(((run.value.completed_items + run.value.failed_items) / run.value.total_items) * 100)) : 0)
function sampleStatus(item) {
  if (item.is_deleted) return ['已删除', 'info']
  if (item.validation_status !== 'passed') return ['校验失败', 'danger']
  return { approved: ['已通过', 'success'], rejected: ['已拒绝', 'danger'], pending: ['待审核', 'warning'] }[item.review_status] || ['未知', 'info']
}
function excerpt(item) { return item.messages.find(message => message.role === 'user')?.content || item.messages[0]?.content || '空消息' }
async function loadSamples() {
  loading.value = true
  try {
    const query = new URLSearchParams({ page: String(page.value), size: String(limit) })
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value)
    const result = await api(`/api/projects/${route.params.id}/samples/search?${query}`)
    samples.value = result.items; total.value = result.total
  }
  catch (error) { notifyError(error, ElMessage) }
  finally { loading.value = false }
}
async function applyFilters() { page.value = 1; await loadSamples() }
async function clearFilters() {
  filters.review_status = ''; filters.validation_status = ''; filters.keyword = ''
  await applyFilters()
}
async function regenerate() {
  if (!detail.value) return
  busy.value = true
  try { await api(`/api/projects/${route.params.id}/chunks/${detail.value.chunk_id}/regenerate`, { method: 'POST' }); drawer.value = false; await reload(); ElMessage.success('已完成重新生成；新样本等待审核') }
  catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
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
async function loadQuality() {
  try { quality.value = await api(`/api/projects/${route.params.id}/quality-summary`) }
  catch (error) { notifyError(error, ElMessage) }
}
async function reload() { clearTimeout(timer); run.value = null; await refreshProjects(); await Promise.all([loadSamples(), loadRun(), loadQuality()]) }
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
  try { await api(run.value?.run_type === 'augmentation' ? `/api/runs/${run.value.id}/retry` : `/api/projects/${route.params.id}/retry`, { method: 'POST' }); await reload(); ElMessage.success(run.value?.run_type === 'augmentation' ? '失败扩增任务已开始重试' : '失败内容块已开始重试') }
  catch (error) { notifyError(error, ElMessage) }
}
function augmentationPayload(includeFingerprint = false) {
  const payload = { strategies: augmentationForm.strategies, target_count: augmentationForm.target_count, keyword: augmentationForm.keyword || null, source_document_ids: augmentationForm.source_document_ids, model_id: augmentationForm.model_id || null }
  if (augmentationForm.prompt_mode === 'custom') payload.custom_prompt = augmentationForm.custom_prompt
  else if (augmentationForm.prompt_id) payload.prompt_id = augmentationForm.prompt_id
  if (includeFingerprint) payload.fingerprint = augmentationPreview.value?.fingerprint
  return payload
}
async function openAugmentation() {
  augmentationLoading.value = true
  try {
    const [sources, prompts, models] = await Promise.all([api(`/api/projects/${route.params.id}/augmentation-options`), api('/api/prompts'), api('/api/models')])
    augmentationSources.value = sources; augmentationPrompts.value = prompts.filter(item => item.mode === 'augmentation'); augmentationModels.value = models
    if (!augmentationForm.prompt_id) augmentationForm.prompt_id = augmentationPrompts.value[0]?.id || ''
    augmentationPreview.value = null; augmentationDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { augmentationLoading.value = false }
}
async function previewAugmentation() {
  augmentationLoading.value = true
  try { augmentationPreview.value = await api(`/api/projects/${route.params.id}/augmentations/preview`, jsonOptions('POST', augmentationPayload())); }
  catch (error) { augmentationPreview.value = null; notifyError(error, ElMessage) }
  finally { augmentationLoading.value = false }
}
async function startAugmentation() {
  if (!augmentationPreview.value) { await previewAugmentation(); if (!augmentationPreview.value) return }
  augmentationLoading.value = true
  try { await api(`/api/projects/${route.params.id}/augmentations`, jsonOptions('POST', augmentationPayload(true))); augmentationDialog.value = false; await reload(); ElMessage.success('扩增任务已启动，结果会进入待审核') }
  catch (error) { notifyError(error, ElMessage) }
  finally { augmentationLoading.value = false }
}
async function exportSamples() {
  busy.value = true
  downloadUrl.value = ''
  try { const result = await api(`/api/projects/${route.params.id}/exports`, jsonOptions('POST', exportForm)); downloadUrl.value = result.download_url; ElMessage.success(`已导出 ${result.sample_count} 条样本`) }
  catch (error) { notifyError(error, ElMessage) }
  finally { busy.value = false }
}
function downloadExport() {
  window.open(downloadUrl.value, '_blank', 'noopener')
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
  <div class="project-actions"><el-button type="primary" :icon="MagicStick" @click="openAugmentation">扩展数据集</el-button><el-button :icon="RefreshRight" @click="reload">刷新</el-button><el-button v-if="run?.failed_items" type="warning" :icon="RefreshRight" @click="retry">{{ run?.run_type === 'augmentation' ? '重试扩增任务' : '重试失败内容块' }}</el-button><el-button type="danger" plain :icon="Delete" @click="trash">移入回收站</el-button></div>
  <section class="section-card progress-card">
    <div class="section-heading"><div><h2>构建进度</h2><span class="section-subtitle" role="status">{{ statusNames[run?.status] || '正在读取任务状态' }}</span></div><strong class="progress-number">{{ run?.completed_items || 0 }} <span>/ {{ run?.total_items || 0 }}</span></strong></div>
    <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
    <div class="progress-meta"><template v-if="run?.run_type === 'augmentation'"><span>有效新增 {{ run?.completed_items || 0 }} 条</span><span>已尝试 {{ run?.augmentation?.attempted || 0 }} 次</span><span>淘汰或失败 {{ run?.failed_items || 0 }} 次</span></template><template v-else><span>已成功 {{ run?.completed_items || 0 }} 个内容块</span><span>失败 {{ run?.failed_items || 0 }} 个</span><span>生成 {{ run?.sample_count || 0 }} 条样本</span></template></div>
    <el-alert v-if="run?.error_message" :title="run.error_message" type="error" :closable="false" show-icon class="run-alert" />
    <el-alert v-if="run?.status === 'interrupted'" title="任务曾中断，可重试剩余内容块；切分前中断需要重新上传。" type="warning" :closable="false" show-icon class="run-alert" />
    <div v-if="run?.failed_chunks?.length" class="failed-chunks"><p v-for="chunk in run.failed_chunks" :key="chunk.id">内容块 {{ chunk.id.slice(0, 8) }}：{{ chunk.error }}</p></div>
  </section>
  <section v-if="quality" class="section-card quality-card">
    <div class="section-heading"><div><h2>数据概览</h2><span class="section-subtitle">{{ quality.scope }}</span></div><el-button text type="primary" @click="loadQuality">更新统计</el-button></div>
    <div class="quality-metrics"><div><span>当前可导出</span><strong>{{ quality.exportable_count }}</strong><small>已审核且校验通过</small></div><div><span>扩增样本</span><strong>{{ quality.origins?.augmented || 0 }}</strong><small>原始 {{ quality.origins?.original || 0 }} 条</small></div><div><span>校验失败</span><strong>{{ quality.validations.failed || 0 }}</strong><small>待审核 {{ quality.reviews.pending || 0 }} 条</small></div><div><span>精确重复</span><strong>{{ quality.duplicates }}</strong><small>规范化内容哈希重复</small></div></div>
    <div class="quality-grid"><div class="quality-panel"><h3>常见校验问题</h3><el-empty v-if="!quality.issues.length" description="没有校验问题" :image-size="48" /><div v-else class="quality-list"><div v-for="issue in quality.issues" :key="issue.rule"><span>{{ issue.rule }}</span><b>{{ issue.count }}</b></div></div></div><div class="quality-panel"><h3>消息长度分布</h3><div class="length-bars"><div v-for="(count, label) in quality.message_lengths" :key="label"><span>{{ label }}</span><i><b :style="{ width: `${Math.min(100, count * 12)}%` }" /></i><em>{{ count }}</em></div></div></div><div class="quality-panel"><h3>来源文档占比</h3><div class="quality-list"><div v-for="source in quality.sources.slice(0, 5)" :key="source.name"><span>{{ source.name }}</span><b>{{ source.count }}</b></div></div></div></div>
  </section>
  <section class="section-card review-card">
    <div class="section-heading review-heading"><div><h2>样本审核</h2><span class="section-subtitle">{{ total }} 条可审核样本；已替代版本默认隐藏</span></div></div>
    <div class="review-filterbar">
      <div class="filter-controls">
        <el-select v-model="filters.review_status" clearable placeholder="全部审核状态"><el-option label="待审核" value="pending" /><el-option label="已通过" value="approved" /><el-option label="已拒绝" value="rejected" /></el-select>
        <el-select v-model="filters.validation_status" clearable placeholder="全部校验状态"><el-option label="校验通过" value="passed" /><el-option label="校验失败" value="failed" /></el-select>
        <el-input v-model="filters.keyword" clearable placeholder="搜索问题、回答或消息内容" @keyup.enter="applyFilters" />
        <el-button type="primary" @click="applyFilters">筛选</el-button>
        <el-button text :disabled="!filters.review_status && !filters.validation_status && !filters.keyword" @click="clearFilters">清除</el-button>
      </div>
      <div class="page-actions"><span>当前页 {{ samples.length }} 条</span><el-button type="success" plain :disabled="!samples.length" @click="bulk('approved')">通过本页</el-button><el-button plain :disabled="!samples.length" @click="bulk('rejected')">拒绝本页</el-button></div>
    </div>
    <el-empty v-if="!loading && !samples.length" :description="activeStatuses.has(run?.status) ? '正在生成样本，完成后会在这里显示' : '当前没有样本可审核'" />
    <el-table v-else v-loading="loading" :data="samples" class="samples-table" stripe @row-click="openDetail">
      <el-table-column label="样本内容" min-width="340"><template #default="{ row }"><div class="sample-title">{{ excerpt(row) }}</div><small class="sample-id">#{{ row.id.slice(0, 8) }} · {{ row.messages.length }} 条消息</small></template></el-table-column>
      <el-table-column label="校验" width="110"><template #default="{ row }"><el-tag :type="row.validation_status === 'passed' ? 'success' : 'danger'" effect="plain" round>{{ row.validation_status === 'passed' ? '通过' : '失败' }}</el-tag></template></el-table-column>
      <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="sampleStatus(row)[1]" effect="light" round>{{ sampleStatus(row)[0] }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
    </el-table>
    <div v-if="samples.length" class="table-pagination"><el-button :disabled="page === 1" @click="page--; loadSamples()">上一页</el-button><span>第 {{ page }} 页</span><el-button :disabled="page * limit >= total" @click="page++; loadSamples()">下一页</el-button></div>
  </section>
  <section class="section-card export-card"><div><h2>导出训练数据</h2><p>仅导出校验通过、审核通过且未删除的样本。</p></div><div class="export-controls"><el-select v-model="exportForm.format" aria-label="导出格式"><el-option label="ShareGPT" value="sharegpt" /><el-option label="Alpaca" value="alpaca" /></el-select><el-select v-model="exportForm.file_type" aria-label="文件类型"><el-option label="JSONL" value="jsonl" /><el-option label="JSON" value="json" /></el-select><el-button type="primary" :loading="busy" :icon="Download" @click="exportSamples">生成文件</el-button><el-button v-if="downloadUrl" link type="primary" @click="downloadExport">下载文件</el-button></div></section>
  <el-dialog v-model="augmentationDialog" class="augmentation-dialog" width="min(980px, calc(100% - 32px))" destroy-on-close>
    <template #header><div class="preview-dialog-title"><strong>扩展数据集</strong><span>基于已通过样本生成可追溯的新变体，生成结果统一等待审核。</span></div></template>
    <div class="augmentation-workbench">
      <div class="augmentation-controls">
        <div class="augmentation-block"><h3>选择种子</h3><el-select v-model="augmentationForm.source_document_ids" multiple clearable collapse-tags placeholder="全部已通过来源"><el-option v-for="source in augmentationSources" :key="source.id" :label="source.name" :value="source.id" /></el-select><el-input v-model="augmentationForm.keyword" clearable placeholder="按内容关键词缩小范围（可选）" /></div>
        <div class="augmentation-block"><h3>扩增方式</h3><el-checkbox-group v-model="augmentationForm.strategies" class="strategy-options"><el-checkbox v-for="strategy in augmentationStrategies" :key="strategy.id" :value="strategy.id"><span>{{ strategy.name }}</span><small>{{ strategy.description }}</small></el-checkbox></el-checkbox-group></div>
        <div class="augmentation-block compact-fields"><el-form label-position="top"><el-form-item label="目标新增数量"><el-input-number v-model="augmentationForm.target_count" :min="1" :max="1000" /></el-form-item><el-form-item label="生成模型"><el-select v-model="augmentationForm.model_id" clearable placeholder="工作区默认模型"><el-option v-for="model in augmentationModels" :key="model.id" :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item></el-form></div>
        <div class="augmentation-block">
          <el-segmented v-model="augmentationForm.prompt_mode" :options="[{ label: '使用模板', value: 'template' }, { label: '临时自定义', value: 'custom' }]" style=" margin-bottom: 10px" />
          <el-select v-if="augmentationForm.prompt_mode === 'template'" v-model="augmentationForm.prompt_id" placeholder="选择扩增模板">
            <el-option v-for="prompt in augmentationPrompts" :key="prompt.id" :label="prompt.name" :value="prompt.id" />
          </el-select>
          <el-input v-else v-model="augmentationForm.custom_prompt" type="textarea" :rows="3" placeholder="例如：保持专业术语，优先生成面向运维人员的案例式问题。" />
        </div>
      </div>
      <aside class="augmentation-ledger"><div><span>计划规模</span><strong>{{ augmentationPreview?.target_count || augmentationForm.target_count }}</strong><small>条待审核的新样本</small></div><div><span>合格种子</span><strong>{{ augmentationPreview?.eligible_count ?? '—' }}</strong><small>仅计算审核和校验均通过的样本</small></div><div v-if="augmentationPreview" class="strategy-ledger"><h3>策略分配</h3><p v-for="item in augmentationPreview.distribution" :key="item.id"><span>{{ item.name }}</span><b>{{ item.count }} 条</b></p></div><div class="augmentation-note"><b>补生规则</b><p>重复或校验失败会自动补生；最多尝试 {{ augmentationPreview?.max_attempts || augmentationForm.target_count * 2 }} 次。</p></div></aside>
    </div>
    <template #footer><div class="augmentation-footer"><span v-if="augmentationPreview">预计最多 {{ augmentationPreview.estimated_requests }} 次模型请求</span><span v-else>先检查种子和策略分配，不会调用模型</span><div><el-button @click="augmentationDialog = false">取消</el-button><el-button :loading="augmentationLoading" @click="previewAugmentation">检查计划</el-button><el-button type="primary" :loading="augmentationLoading" :disabled="!augmentationPreview" @click="startAugmentation">开始扩增</el-button></div></div></template>
  </el-dialog>
  <el-drawer v-model="drawer" :title="`样本 #${detail?.id?.slice(0, 8) || ''}`" size="min(680px, 100%)" class="sample-drawer">
    <template v-if="detail"><div class="drawer-status"><el-tag :type="sampleStatus(detail)[1]" round>{{ sampleStatus(detail)[0] }}</el-tag><span>来源内容块 #{{ detail.chunk_id.slice(0, 8) }}</span><span v-if="detail.parent_sample_id">扩增自样本 #{{ detail.parent_sample_id.slice(0, 8) }}</span></div>
      <div class="drawer-section"><h3>消息内容</h3><div v-for="(message, index) in messages" :key="index" class="message-card"><div class="message-head"><el-select v-model="message.role"><el-option label="system" value="system" /><el-option label="user" value="user" /><el-option label="assistant" value="assistant" /></el-select><el-button text type="danger" @click="messages.splice(index, 1)">移除</el-button></div><el-input v-model="message.content" type="textarea" :rows="3" /></div><el-button text type="primary" @click="messages.push({ role: 'user', content: '' })">＋ 添加消息</el-button><el-button type="primary" :loading="busy" @click="saveMessages">保存修改</el-button></div>
      <div class="drawer-section"><h3>来源内容</h3><pre class="source-preview">{{ detail.chunk_content || '无来源内容' }}</pre></div>
      <div class="drawer-section"><h3>校验结果</h3><el-alert v-if="!detail.issues.length" title="结构与内容校验通过" type="success" :closable="false" show-icon /><el-alert v-for="issue in detail.issues" :key="issue.rule" :title="`${issue.rule}：${issue.message}`" type="warning" :closable="false" class="issue-alert" /></div>
    </template>
    <template #footer><div v-if="detail" class="drawer-actions"><el-button :loading="busy" @click="regenerate">重新生成此内容块</el-button><el-button type="success" :icon="Check" :loading="busy" @click="review('approved')">通过</el-button><el-button :loading="busy" @click="review('rejected')">拒绝</el-button><el-button type="danger" plain :loading="busy" @click="toggleDeleted">{{ detail.is_deleted ? '恢复样本' : '软删除' }}</el-button></div></template>
  </el-drawer>
</template>
