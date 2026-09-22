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
const augmentationForm = reactive({ strategies: ['rewrite', 'angle', 'scenario'], target_count: 100, keyword: '', source_document_ids: [], prompt_mode: 'template', prompt_id: '', custom_prompt: '', multi_turn: false, model_id: '' })
const augmentationStrategies = [
  { id: 'rewrite', name: '表达改写', description: '同一事实，不同问法和表达。' },
  { id: 'angle', name: '认知角度', description: '定义、原因、过程、比较、影响。' },
  { id: 'deepen', name: '难度深化', description: '增加约束与推理，不增加事实。' },
  { id: 'audience', name: '角色视角', description: '为不同受众组织解释。' },
  { id: 'scenario', name: '场景应用', description: '把知识落到具体任务中。' },
]
const distillationDialog = ref(false)
const distillationPreview = ref(null)
const distillationLoading = ref(false)
const distillationSources = ref([])
const distillationPrompts = ref([])
const distillationModels = ref([])
const distillationForm = reactive({ target_count: 100, keyword: '', source_document_ids: [], prompt_mode: 'template', prompt_id: '', custom_prompt: '', model_id: '' })
const comparisonDialog = ref(false)
const comparisonLoading = ref(false)
const comparisonItems = ref([])
const comparisonTotal = ref(0)
const comparisonIndex = ref(0)
const currentComparison = computed(() => comparisonItems.value[comparisonIndex.value] || null)
const versionDialog = ref(false)
const versionLoading = ref(false)
const versions = ref([])
const versionForm = reactive({ name: '', description: '', dataset_type: 'sft' })
const versionCompare = reactive({ base_id: '', target_id: '' })
const versionDiff = ref(null)
const trainingPackageDialog = ref(false)
const trainingPackageLoading = ref(false)
const trainingPackageVersion = ref(null)
const trainingPackageForm = reactive({ model_name_or_path: '', template: 'qwen', finetuning_type: 'lora', cutoff_len: 2048, num_train_epochs: 3, learning_rate: '1e-4', per_device_train_batch_size: 2, gradient_accumulation_steps: 8, output_dir_name: 'sft-output', pref_beta: 0.1, pref_loss: 'sigmoid' })
const preferenceDialog = ref(false)
const preferenceLoading = ref(false)
const preferences = ref([])
const preferenceTotal = ref(0)
const preferenceEditing = ref(null)
const preferenceForm = reactive({ prompt: '', chosen: '', rejected: '' })
const templatePresets = ['qwen', 'llama3', 'deepseek', 'chatml', 'gemma', 'mistral']
let timer = null
const activeStatuses = new Set(['created', 'importing', 'parsing', 'splitting', 'generating', 'augmenting', 'distilling', 'cleaning', 'validating'])
const statusNames = { created: '任务已创建', importing: '正在导入', parsing: '正在解析', splitting: '正在切分', generating: '正在生成', augmenting: '正在扩增', distilling: '正在蒸馏', cleaning: '正在清洗', validating: '正在校验', ready_for_review: '等待审核', completed: '处理完成', failed: '构建失败', interrupted: '任务已中断' }
const progressPercent = computed(() => run.value?.total_items ? Math.min(100, Math.round(((run.value.completed_items + run.value.failed_items) / run.value.total_items) * 100)) : 0)
function sampleStatus(item) {
  if (item.is_deleted) return ['已删除', 'info']
  if (item.validation_status !== 'passed') return ['校验失败', 'danger']
  return { approved: ['已通过', 'success'], rejected: ['已拒绝', 'danger'], pending: ['待审核', 'warning'] }[item.review_status] || ['未知', 'info']
}
function excerpt(item) { return item.messages.find(message => message.role === 'user')?.content || item.messages[0]?.content || '空消息' }
function comparisonTurns(item) {
  if (!item) return []
  const sourceAnswers = item.source_messages.filter(message => message.role === 'assistant')
  const turns = []
  let user = ''
  let answerIndex = 0
  for (const message of item.candidate_messages) {
    if (message.role === 'user') user = message.content
    if (message.role === 'assistant') {
      turns.push({
        user,
        original: sourceAnswers[answerIndex]?.content || '',
        teacher: message.content,
      })
      answerIndex += 1
    }
  }
  return turns
}
function diffParts(value, comparison) {
  if (!value) return []
  if (value === comparison) return [{ text: value, changed: false }]
  let start = 0
  const maxStart = Math.min(value.length, comparison.length)
  while (start < maxStart && value[start] === comparison[start]) start += 1
  let end = 0
  const maxEnd = Math.min(value.length - start, comparison.length - start)
  while (end < maxEnd && value[value.length - 1 - end] === comparison[comparison.length - 1 - end]) end += 1
  const parts = []
  if (start) parts.push({ text: value.slice(0, start), changed: false })
  parts.push({ text: value.slice(start, end ? value.length - end : value.length), changed: true })
  if (end) parts.push({ text: value.slice(value.length - end), changed: false })
  return parts.filter(part => part.text)
}
function formatVersionDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '刚刚' }
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
  const isBackgroundRun = ['augmentation', 'distillation'].includes(run.value?.run_type)
  const label = run.value?.run_type === 'distillation' ? '蒸馏' : '扩增'
  try { await api(isBackgroundRun ? `/api/runs/${run.value.id}/retry` : `/api/projects/${route.params.id}/retry`, { method: 'POST' }); await reload(); ElMessage.success(isBackgroundRun ? `失败${label}任务已开始重试` : '失败内容块已开始重试') }
  catch (error) { notifyError(error, ElMessage) }
}
function augmentationPayload(includeFingerprint = false) {
  const payload = { strategies: augmentationForm.strategies, target_count: augmentationForm.target_count, keyword: augmentationForm.keyword || null, source_document_ids: augmentationForm.source_document_ids, multi_turn: augmentationForm.multi_turn, model_id: augmentationForm.model_id || null }
  if (augmentationForm.prompt_mode === 'custom') payload.custom_prompt = augmentationForm.custom_prompt
  else if (augmentationForm.prompt_id) payload.prompt_id = augmentationForm.prompt_id
  if (includeFingerprint) payload.fingerprint = augmentationPreview.value?.fingerprint
  return payload
}
function syncAugmentationPromptMode() {
  const prompt = augmentationPrompts.value.find(item => item.id === augmentationForm.prompt_id)
  augmentationForm.multi_turn = Boolean(prompt?.multi_turn)
  augmentationPreview.value = null
}
async function openAugmentation() {
  augmentationLoading.value = true
  try {
    const [sources, prompts, models] = await Promise.all([api(`/api/projects/${route.params.id}/augmentation-options`), api('/api/prompts'), api('/api/models')])
    augmentationSources.value = sources; augmentationPrompts.value = prompts.filter(item => item.mode === 'augmentation'); augmentationModels.value = models
    if (!augmentationForm.prompt_id) augmentationForm.prompt_id = augmentationPrompts.value[0]?.id || ''
    syncAugmentationPromptMode()
    augmentationPreview.value = null; augmentationDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { augmentationLoading.value = false }
}
function distillationPayload(includeFingerprint = false) {
  const payload = { target_count: distillationForm.target_count, keyword: distillationForm.keyword || null, source_document_ids: distillationForm.source_document_ids, model_id: distillationForm.model_id || null }
  if (distillationForm.prompt_mode === 'custom') payload.custom_prompt = distillationForm.custom_prompt
  else if (distillationForm.prompt_id) payload.prompt_id = distillationForm.prompt_id
  if (includeFingerprint) payload.fingerprint = distillationPreview.value?.fingerprint
  return payload
}
async function openDistillation() {
  distillationLoading.value = true
  try {
    const [sources, prompts, models] = await Promise.all([api(`/api/projects/${route.params.id}/augmentation-options`), api('/api/prompts'), api('/api/models')])
    distillationSources.value = sources; distillationPrompts.value = prompts.filter(item => item.mode === 'distillation'); distillationModels.value = models
    if (!distillationForm.prompt_id) distillationForm.prompt_id = distillationPrompts.value[0]?.id || ''
    distillationPreview.value = null; distillationDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { distillationLoading.value = false }
}
async function previewDistillation() {
  distillationLoading.value = true
  try { distillationPreview.value = await api(`/api/projects/${route.params.id}/distillations/preview`, jsonOptions('POST', distillationPayload())); ElMessage.success('蒸馏计划已检查，尚未调用模型') }
  catch (error) { notifyError(error, ElMessage) }
  finally { distillationLoading.value = false }
}
async function startDistillation() {
  distillationLoading.value = true
  try { await api(`/api/projects/${route.params.id}/distillations`, jsonOptions('POST', distillationPayload(true))); distillationDialog.value = false; await reload(); ElMessage.success('教师独立作答已启动，结果会进入待审核') }
  catch (error) { notifyError(error, ElMessage) }
  finally { distillationLoading.value = false }
}
async function openComparisonReview() {
  comparisonLoading.value = true
  try {
    const result = await api(`/api/projects/${route.params.id}/distillations/review-queue?limit=200`)
    comparisonItems.value = result.items
    comparisonTotal.value = result.total
    comparisonIndex.value = 0
    comparisonDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { comparisonLoading.value = false }
}
async function decideComparison(decision) {
  if (!currentComparison.value) return
  comparisonLoading.value = true
  try {
    const result = await api(`/api/samples/${currentComparison.value.id}/distillation-review`, jsonOptions('PATCH', { decision }))
    const labels = { adopt_teacher: '已采用教师回答', keep_original: '已保留原回答', keep_both: '已保留两个版本' }
    comparisonItems.value.splice(comparisonIndex.value, 1)
    comparisonTotal.value = Math.max(0, comparisonTotal.value - 1)
    if (comparisonIndex.value >= comparisonItems.value.length) comparisonIndex.value = Math.max(0, comparisonItems.value.length - 1)
    await Promise.all([loadSamples(), loadQuality()])
    ElMessage.success(result.preference_pair_id ? `${labels[decision]}，已生成 DPO 偏好对` : `${labels[decision]}${result.preference_skip_reason ? `；${result.preference_skip_reason}` : ''}`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { comparisonLoading.value = false }
}
async function loadPreferences() {
  preferenceLoading.value = true
  try {
    const result = await api(`/api/projects/${route.params.id}/preference-pairs?size=200`)
    preferences.value = result.items; preferenceTotal.value = result.total; preferenceDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { preferenceLoading.value = false }
}
async function createPreference() {
  preferenceLoading.value = true
  try {
    const payload = {
      context_messages: [{ role: 'user', content: preferenceForm.prompt }],
      chosen_response: { role: 'assistant', content: preferenceForm.chosen },
      rejected_response: { role: 'assistant', content: preferenceForm.rejected },
    }
    const path = preferenceEditing.value ? `/api/preference-pairs/${preferenceEditing.value}` : `/api/projects/${route.params.id}/preference-pairs`
    await api(path, jsonOptions(preferenceEditing.value ? 'PUT' : 'POST', payload))
    preferenceForm.prompt = ''; preferenceForm.chosen = ''; preferenceForm.rejected = ''
    preferenceEditing.value = null
    await loadPreferences(); await loadQuality(); ElMessage.success('偏好对已保存，等待审核')
  } catch (error) { notifyError(error, ElMessage) }
  finally { preferenceLoading.value = false }
}
function editPreference(item) {
  preferenceEditing.value = item.id
  preferenceForm.prompt = item.context_messages.at(-1)?.content || ''
  preferenceForm.chosen = item.chosen_response.content
  preferenceForm.rejected = item.rejected_response.content
}
async function deletePreference(item) {
  preferenceLoading.value = true
  try {
    await api(`/api/preference-pairs/${item.id}/deleted`, jsonOptions('PATCH', { is_deleted: true }))
    await loadPreferences(); await loadQuality(); ElMessage.success('偏好对已移入删除状态')
  } catch (error) { notifyError(error, ElMessage) }
  finally { preferenceLoading.value = false }
}
async function reviewPreference(item, status) {
  preferenceLoading.value = true
  try {
    await api(`/api/preference-pairs/${item.id}/review`, jsonOptions('PATCH', { status }))
    await loadPreferences(); await loadQuality(); ElMessage.success('偏好对审核状态已更新')
  } catch (error) { notifyError(error, ElMessage) }
  finally { preferenceLoading.value = false }
}
async function openVersions() {
  versionLoading.value = true
  try {
    versions.value = await api(`/api/projects/${route.params.id}/versions`)
    if (!versionCompare.target_id) versionCompare.target_id = versions.value[0]?.id || ''
    if (!versionCompare.base_id) versionCompare.base_id = versions.value[1]?.id || versions.value[0]?.id || ''
    versionDiff.value = null
    versionDialog.value = true
  } catch (error) { notifyError(error, ElMessage) }
  finally { versionLoading.value = false }
}
async function createVersion() {
  versionLoading.value = true
  try {
    const created = await api(`/api/projects/${route.params.id}/versions`, jsonOptions('POST', versionForm))
    versions.value.unshift(created)
    versionForm.name = ''; versionForm.description = ''
    versionCompare.target_id = created.id
    if (!versionCompare.base_id) versionCompare.base_id = versions.value[1]?.id || created.id
    ElMessage.success(`版本 ${created.name} 已创建`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { versionLoading.value = false }
}
async function compareVersions() {
  if (!versionCompare.base_id || !versionCompare.target_id || versionCompare.base_id === versionCompare.target_id) return
  versionLoading.value = true
  try {
    const query = new URLSearchParams(versionCompare)
    versionDiff.value = await api(`/api/projects/${route.params.id}/versions/compare?${query}`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { versionLoading.value = false }
}
async function exportVersion(version) {
  versionLoading.value = true
  try {
    const payload = { ...exportForm, format: version.dataset_type === 'dpo' ? 'sharegpt_preference' : exportForm.format }
    const result = await api(`/api/versions/${version.id}/exports`, jsonOptions('POST', payload))
    downloadUrl.value = result.download_url
    ElMessage.success(`版本 ${version.name} 已导出 ${result.sample_count} 条样本`)
    downloadExport()
  } catch (error) { notifyError(error, ElMessage) }
  finally { versionLoading.value = false }
}
function openTrainingPackage(version) {
  trainingPackageVersion.value = version
  const stage = version.dataset_type === 'dpo' ? 'dpo' : 'sft'
  trainingPackageForm.output_dir_name = `${version.name.replace(/[^A-Za-z0-9._-]/g, '-').replace(/^-+/, '') || stage}-output`.slice(0, 100)
  trainingPackageDialog.value = true
}
async function buildTrainingPackage() {
  if (!trainingPackageVersion.value || !trainingPackageForm.model_name_or_path.trim()) return
  trainingPackageLoading.value = true
  try {
    const payload = {
      ...trainingPackageForm,
      learning_rate: Number(trainingPackageForm.learning_rate)
    }
    const response = await api(`/api/versions/${trainingPackageVersion.value.id}/training-packages/llamafactory`, jsonOptions('POST', payload))
    const blobUrl = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = blobUrl
    anchor.download = `llamafactory-${trainingPackageVersion.value.name}.zip`
    anchor.click()
    URL.revokeObjectURL(blobUrl)
    ElMessage.success(`训练包已生成，共 ${response.headers.get('X-Sample-Count') || trainingPackageVersion.value.sample_count} 条样本`)
    trainingPackageDialog.value = false
  } catch (error) { notifyError(error, ElMessage) }
  finally { trainingPackageLoading.value = false }
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
  <div class="project-actions"><el-button type="primary" :icon="MagicStick"
      @click="openAugmentation">扩展数据集</el-button><el-button plain :icon="MagicStick"
      @click="openDistillation">教师答案蒸馏</el-button><el-button plain :icon="Check"
      @click="openComparisonReview">蒸馏对比审核</el-button><el-button plain @click="loadPreferences">DPO 偏好数据</el-button><el-button plain @click="openVersions">版本快照</el-button><el-button
      :icon="RefreshRight" @click="reload">刷新</el-button><el-button v-if="run?.failed_items" type="warning"
      :icon="RefreshRight" @click="retry">{{ run?.run_type === 'augmentation' ? '重试扩增任务' : run?.run_type ===
        'distillation' ? '重试蒸馏任务' : '重试失败内容块' }}</el-button><el-button type="danger" plain :icon="Delete"
      @click="trash">移入回收站</el-button></div>
  <section class="section-card progress-card">
    <div class="section-heading">
      <div>
        <h2>构建进度</h2><span class="section-subtitle" role="status">{{ statusNames[run?.status] || '正在读取任务状态' }}</span>
      </div><strong class="progress-number">{{ run?.completed_items || 0 }} <span>/ {{ run?.total_items || 0
          }}</span></strong>
    </div>
    <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
    <div class="progress-meta"><template v-if="run?.run_type === 'augmentation'"><span>有效新增 {{ run?.completed_items || 0
          }} 条</span><span>已尝试 {{ run?.augmentation?.attempted || 0 }} 次</span><span>淘汰或失败 {{ run?.failed_items || 0 }}
          次</span></template><template v-else-if="run?.run_type === 'distillation'"><span>已生成 {{ run?.completed_items ||
            0 }} 条教师候选</span><span>已处理 {{ run?.distillation?.attempted || 0 }} 条原样本</span><span>失败或过滤 {{ run?.failed_items
            || 0 }} 条</span></template><template v-else><span>已成功 {{ run?.completed_items || 0 }} 个内容块</span><span>失败 {{
            run?.failed_items || 0 }} 个</span><span>生成 {{ run?.sample_count || 0 }} 条样本</span></template>
    </div>
    <el-alert v-if="run?.error_message" :title="run.error_message" type="error" :closable="false" show-icon
      class="run-alert" />
    <el-alert v-if="run?.status === 'interrupted'" title="任务曾中断，可重试剩余内容块；切分前中断需要重新上传。" type="warning" :closable="false"
      show-icon class="run-alert" />
    <div v-if="run?.run_type === 'distillation' && run?.distillation?.errors?.length" class="failed-chunks">
      <p v-for="(item, index) in run.distillation.errors" :key="index">{{ item.status === 'filtered' ? '规则过滤' : '处理失败'
        }}：{{
          item.message }}</p>
    </div>
    <div v-if="run?.failed_chunks?.length" class="failed-chunks">
      <p v-for="chunk in run.failed_chunks" :key="chunk.id">内容块 {{ chunk.id.slice(0, 8) }}：{{ chunk.error }}</p>
    </div>
  </section>
  <section v-if="quality" class="section-card quality-card">
    <div class="section-heading">
      <div>
        <h2>数据概览</h2><span class="section-subtitle">{{ quality.scope }}</span>
      </div><el-button text type="primary" @click="loadQuality">更新统计</el-button>
    </div>
    <div class="quality-metrics">
      <div><span>当前可导出</span><strong>{{ quality.exportable_count }}</strong><small>已审核且校验通过</small></div>
      <div><span>扩增样本</span><strong>{{ quality.origins?.augmented || 0 }}</strong><small>原始 {{ quality.origins?.original
        || 0 }} 条</small></div>
      <div><span>蒸馏候选</span><strong>{{ quality.origins?.distilled || 0 }}</strong><small>教师独立作答待审核</small></div>
      <div><span>精确重复</span><strong>{{ quality.duplicates }}</strong><small>规范化内容哈希重复</small></div>
    </div>
    <div class="quality-grid">
      <div class="quality-panel">
        <h3>常见校验问题</h3><el-empty v-if="!quality.issues.length" description="没有校验问题" :image-size="48" />
        <div v-else class="quality-list">
          <div v-for="issue in quality.issues" :key="issue.rule"><span>{{ issue.rule }}</span><b>{{ issue.count }}</b>
          </div>
        </div>
      </div>
      <div class="quality-panel">
        <h3>消息长度分布</h3>
        <div class="length-bars">
          <div v-for="(count, label) in quality.message_lengths" :key="label"><span>{{ label }}</span><i><b
                :style="{ width: `${Math.min(100, count * 12)}%` }" /></i><em>{{ count }}</em></div>
        </div>
      </div>
      <div class="quality-panel">
        <h3>来源文档占比</h3>
        <div class="quality-list">
          <div v-for="source in quality.sources.slice(0, 5)" :key="source.name"><span>{{ source.name }}</span><b>{{
            source.count }}</b></div>
        </div>
      </div>
    </div>
  </section>
  <section class="section-card review-card">
    <div class="section-heading review-heading">
      <div>
        <h2>样本审核</h2><span class="section-subtitle">{{ total }} 条可审核样本；已替代版本默认隐藏</span>
      </div>
    </div>
    <div class="review-filterbar">
      <div class="filter-controls">
        <el-select v-model="filters.review_status" clearable placeholder="全部审核状态"><el-option label="待审核"
            value="pending" /><el-option label="已通过" value="approved" /><el-option label="已拒绝"
            value="rejected" /></el-select>
        <el-select v-model="filters.validation_status" clearable placeholder="全部校验状态"><el-option label="校验通过"
            value="passed" /><el-option label="校验失败" value="failed" /></el-select>
        <el-input v-model="filters.keyword" clearable placeholder="搜索问题、回答或消息内容" @keyup.enter="applyFilters" />
        <el-button type="primary" @click="applyFilters">筛选</el-button>
        <el-button text :disabled="!filters.review_status && !filters.validation_status && !filters.keyword"
          @click="clearFilters">清除</el-button>
      </div>
      <div class="page-actions"><span>当前页 {{ samples.length }} 条</span><el-button type="success" plain
          :disabled="!samples.length" @click="bulk('approved')">通过本页</el-button><el-button plain
          :disabled="!samples.length" @click="bulk('rejected')">拒绝本页</el-button></div>
    </div>
    <el-empty v-if="!loading && !samples.length"
      :description="activeStatuses.has(run?.status) ? '正在生成样本，完成后会在这里显示' : '当前没有样本可审核'" />
    <el-table v-else v-loading="loading" :data="samples" class="samples-table" stripe @row-click="openDetail">
      <el-table-column label="样本内容" min-width="340"><template #default="{ row }">
          <div class="sample-title">{{ excerpt(row) }}</div><small class="sample-id">#{{ row.id.slice(0, 8) }} · {{
            row.messages.length }} 条消息</small>
          <div class="mobile-sample-tags"><el-tag :type="row.validation_status === 'passed' ? 'success' : 'danger'"
              effect="plain" round>{{ row.validation_status === 'passed' ? '校验通过' : '校验失败' }}</el-tag><el-tag
              :type="sampleStatus(row)[1]" effect="light" round>{{ sampleStatus(row)[0] }}</el-tag></div>
        </template></el-table-column>
      <el-table-column label="校验" width="110"><template #default="{ row }"><el-tag
            :type="row.validation_status === 'passed' ? 'success' : 'danger'" effect="plain" round>{{
              row.validation_status === 'passed' ? '通过' : '失败' }}</el-tag></template></el-table-column>
      <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="sampleStatus(row)[1]"
            effect="light" round>{{ sampleStatus(row)[0] }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary"
            @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
    </el-table>
    <div v-if="samples.length" class="table-pagination"><el-button :disabled="page === 1"
        @click="page--; loadSamples()">上一页</el-button><span>第 {{ page }} 页</span><el-button
        :disabled="page * limit >= total" @click="page++; loadSamples()">下一页</el-button></div>
  </section>
  <section class="section-card export-card">
    <div>
      <h2>导出训练数据</h2>
      <p>仅导出校验通过、审核通过且未删除的样本。</p>
    </div>
    <div class="export-controls"><el-select v-model="exportForm.format" aria-label="导出格式"><el-option label="ShareGPT"
          value="sharegpt" /><el-option label="Alpaca" value="alpaca" /></el-select><el-select
        v-model="exportForm.file_type" aria-label="文件类型"><el-option label="JSONL" value="jsonl" /><el-option
          label="JSON" value="json" /></el-select><el-button type="primary" :loading="busy" :icon="Download"
        @click="exportSamples">生成文件</el-button><el-button v-if="downloadUrl" link type="primary"
        @click="downloadExport">下载文件</el-button></div>
  </section>
  <el-dialog v-model="augmentationDialog" class="augmentation-dialog" width="min(980px, calc(100% - 32px))"
    destroy-on-close>
    <template #header>
      <div class="preview-dialog-title"><strong>扩展数据集</strong><span>基于已通过样本生成可追溯的新变体，生成结果统一等待审核。</span></div>
    </template>
    <div class="augmentation-workbench">
      <div class="augmentation-controls">
        <div class="augmentation-block">
          <h3>选择种子</h3><el-select v-model="augmentationForm.source_document_ids" multiple clearable collapse-tags
            placeholder="全部已通过来源"><el-option v-for="source in augmentationSources" :key="source.id" :label="source.name"
              :value="source.id" /></el-select><el-input v-model="augmentationForm.keyword" clearable
            placeholder="按内容关键词缩小范围（可选）" />
        </div>
        <div class="augmentation-block">
          <h3>扩增方式</h3><el-checkbox-group v-model="augmentationForm.strategies" class="strategy-options"><el-checkbox
              v-for="strategy in augmentationStrategies" :key="strategy.id" :value="strategy.id"><span>{{ strategy.name
                }}</span><small>{{ strategy.description }}</small></el-checkbox></el-checkbox-group>
        </div>
        <div class="augmentation-block compact-fields"><el-form label-position="top"><el-form-item
              label="目标新增数量"><el-input-number v-model="augmentationForm.target_count" class="plan-count-input"
                :min="1" :max="1000" controls-position="right" /></el-form-item><el-form-item label="生成模型"><el-select v-model="augmentationForm.model_id"
                clearable placeholder="工作区默认模型"><el-option v-for="model in augmentationModels" :key="model.id"
                  :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item></el-form>
        </div>
        <div class="augmentation-block">
          <el-segmented v-model="augmentationForm.prompt_mode"
            :options="[{ label: '使用模板', value: 'template' }, { label: '临时自定义', value: 'custom' }]"
            style=" margin-bottom: 10px" />
          <el-select v-if="augmentationForm.prompt_mode === 'template'" v-model="augmentationForm.prompt_id"
            placeholder="选择扩增模板" @change="syncAugmentationPromptMode">
            <el-option v-for="prompt in augmentationPrompts" :key="prompt.id" :label="prompt.name" :value="prompt.id" />
          </el-select>
          <el-input v-else v-model="augmentationForm.custom_prompt" type="textarea" :rows="3"
            placeholder="例如：保持专业术语，优先生成面向运维人员的案例式问题。" />
          <el-switch v-model="augmentationForm.multi_turn" inline-prompt active-text="多轮" inactive-text="单轮"
            style="margin-top: 12px" @change="augmentationPreview = null" />
          <p class="field-hint">多轮扩增会保留完整追问链路为一条待审核样本。</p>
        </div>
      </div>
      <aside class="augmentation-ledger">
        <div><span>计划规模</span><strong>{{ augmentationPreview?.target_count || augmentationForm.target_count
            }}</strong><small>条待审核的新样本</small></div>
        <div><span>合格种子</span><strong>{{ augmentationPreview?.eligible_count ?? '—'
            }}</strong><small>仅计算审核和校验均通过的样本</small></div>
        <div v-if="augmentationPreview" class="strategy-ledger">
          <h3>策略分配</h3>
          <p v-for="item in augmentationPreview.distribution" :key="item.id"><span>{{ item.name }}</span><b>{{
            item.count
              }} 条</b></p>
        </div>
        <div class="augmentation-note"><b>补生规则</b>
          <p>重复或校验失败会自动补生；最多尝试 {{ augmentationPreview?.max_attempts || augmentationForm.target_count * 2 }} 次。</p>
        </div>
      </aside>
    </div>
    <template #footer>
      <div class="augmentation-footer"><span v-if="augmentationPreview">预计最多 {{ augmentationPreview.estimated_requests
          }} 次模型请求</span><span v-else>先检查种子和策略分配，不会调用模型</span>
        <div><el-button @click="augmentationDialog = false">取消</el-button><el-button :loading="augmentationLoading"
            @click="previewAugmentation">检查计划</el-button><el-button type="primary" :loading="augmentationLoading"
            :disabled="!augmentationPreview" @click="startAugmentation">开始扩增</el-button></div>
      </div>
    </template>
  </el-dialog>
  <el-dialog v-model="distillationDialog" class="augmentation-dialog" width="min(900px, calc(100% - 32px))"
    destroy-on-close>
    <template #header>
      <div class="preview-dialog-title"><strong>教师答案蒸馏</strong><span>教师不读取旧回答，根据来源和原问题独立作答；审核通过后才替代原样本。</span></div>
    </template>
    <div class="augmentation-workbench">
      <div class="augmentation-controls">
        <div class="augmentation-block">
          <h3>选择原始样本</h3><el-select v-model="distillationForm.source_document_ids" multiple clearable collapse-tags
            placeholder="全部已通过来源"><el-option v-for="source in distillationSources" :key="source.id" :label="source.name"
              :value="source.id" /></el-select><el-input v-model="distillationForm.keyword" clearable
            placeholder="按样本内容关键词缩小范围（可选）" />
        </div>
        <div class="augmentation-block compact-fields"><el-form label-position="top"><el-form-item
              label="升级数量"><el-input-number v-model="distillationForm.target_count" class="plan-count-input"
                :min="1" :max="1000" controls-position="right" /></el-form-item><el-form-item label="教师模型"><el-select v-model="distillationForm.model_id"
                clearable placeholder="工作区默认模型"><el-option v-for="model in distillationModels" :key="model.id"
                  :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item></el-form>
        </div>
        <div class="augmentation-block"><el-segmented v-model="distillationForm.prompt_mode"
            :options="[{ label: '使用模板', value: 'template' }, { label: '临时自定义', value: 'custom' }]"
            style="margin-bottom: 10px" /><el-select v-if="distillationForm.prompt_mode === 'template'"
            v-model="distillationForm.prompt_id" placeholder="选择蒸馏模板"><el-option v-for="prompt in distillationPrompts"
              :key="prompt.id" :label="prompt.name" :value="prompt.id" /></el-select><el-input v-else
            v-model="distillationForm.custom_prompt" type="textarea" :rows="3"
            placeholder="例如：严格依据来源，保留专业术语并给出清晰、完整的回答。" />
          <p class="field-hint">教师不会看到旧回答。多轮样本会逐轮生成，并使用新教师回答继续后续对话。</p>
        </div>
      </div>
      <aside class="augmentation-ledger">
        <div><span>计划升级</span><strong>{{ distillationPreview?.target_count || distillationForm.target_count
            }}</strong><small>条待审核候选</small></div>
        <div><span>合格原样本</span><strong>{{ distillationPreview?.eligible_count ?? '—'
            }}</strong><small>仅取审核和校验均通过的未替代样本</small></div>
        <div class="augmentation-note"><b>替代规则</b>
          <p>候选通过人工审核后，原样本才会标记为已替代，可随时追溯来源。</p>
        </div>
      </aside>
    </div>
    <template #footer>
      <div class="augmentation-footer"><span v-if="distillationPreview">预计 {{ distillationPreview.estimated_requests }}
          次教师调用</span><span v-else>先检查可升级样本，不会调用模型</span>
        <div><el-button @click="distillationDialog = false">取消</el-button><el-button :loading="distillationLoading"
            @click="previewDistillation">检查计划</el-button><el-button type="primary" :loading="distillationLoading"
            :disabled="!distillationPreview" @click="startDistillation">开始升级</el-button></div>
      </div>
    </template>
  </el-dialog>
  <el-dialog v-model="comparisonDialog" class="comparison-dialog" width="min(1280px, calc(100% - 28px))"
    destroy-on-close>
    <template #header>
      <div class="comparison-title">
        <div><strong>蒸馏对比审核</strong><span>依据来源判断哪一个回答更适合进入训练集</span></div><b v-if="currentComparison">{{ comparisonIndex
          + 1 }} / {{ comparisonTotal }}</b>
      </div>
    </template>
    <div v-loading="comparisonLoading" class="comparison-shell">
      <el-empty v-if="!currentComparison" description="没有待审核的蒸馏候选" :image-size="70" />
      <template v-else>
        <div class="comparison-grid">
          <section class="comparison-source">
            <header><span>事实依据</span><small>Source Chunk</small></header>
            <pre>{{ currentComparison.chunk_content || '来源内容不可用' }}</pre>
          </section>
          <section class="comparison-version original-version">
            <header><span>原回答</span><small>#{{ currentComparison.source_sample_id?.slice(0, 8) }}</small></header>
            <div class="comparison-turns">
              <article v-for="(turn, index) in comparisonTurns(currentComparison)" :key="index">
                <p class="comparison-question"><b>问题 {{ index + 1 }}</b>{{ turn.user }}</p>
                <p class="comparison-answer"><span v-for="(part, partIndex) in diffParts(turn.original, turn.teacher)"
                    :key="partIndex" :class="{ 'is-changed': part.changed }">{{ part.text }}</span></p>
              </article>
            </div>
          </section>
          <section class="comparison-version teacher-version">
            <header><span>教师回答</span><small>#{{ currentComparison.id.slice(0, 8) }}</small></header>
            <div class="comparison-turns">
              <article v-for="(turn, index) in comparisonTurns(currentComparison)" :key="index">
                <p class="comparison-question"><b>问题 {{ index + 1 }}</b>{{ turn.user }}</p>
                <p class="comparison-answer"><span v-for="(part, partIndex) in diffParts(turn.teacher, turn.original)"
                    :key="partIndex" :class="{ 'is-changed': part.changed }">{{ part.text }}</span></p>
              </article>
            </div>
          </section>
        </div>
        <div class="comparison-nav"><el-button :disabled="comparisonIndex === 0"
            @click="comparisonIndex--">上一条</el-button><span>蓝色与琥珀色标记两版回答发生变化的部分</span><el-button
            :disabled="comparisonIndex >= comparisonItems.length - 1" @click="comparisonIndex++">下一条</el-button></div>
      </template>
    </div>
    <template #footer>
      <div v-if="currentComparison" class="comparison-actions">
        <p><strong>做出版本决策</strong><span>采用教师会替代原样本；两者保留会同时进入可导出数据。</span></p>
        <div><el-button :loading="comparisonLoading"
            @click="decideComparison('keep_original')">保留原回答</el-button><el-button :loading="comparisonLoading"
            @click="decideComparison('keep_both')">两者保留</el-button><el-button type="primary" :icon="Check"
            :loading="comparisonLoading" @click="decideComparison('adopt_teacher')">采用教师回答</el-button></div>
      </div>
    </template>
  </el-dialog>
  <el-dialog v-model="preferenceDialog" width="min(1080px, calc(100% - 28px))" destroy-on-close>
    <template #header><div class="preview-dialog-title"><strong>DPO 偏好数据</strong><span>同一上下文中，明确选择更好的回答。</span></div></template>
    <div v-loading="preferenceLoading" class="preference-workbench">
      <aside class="preference-create"><h3>{{ preferenceEditing ? '编辑偏好对' : '手工创建偏好对' }}</h3><p>手工记录和编辑后的记录会进入待审核状态。</p>
        <el-input v-model="preferenceForm.prompt" type="textarea" :rows="3" placeholder="共同的用户问题" />
        <el-input v-model="preferenceForm.chosen" type="textarea" :rows="4" placeholder="Chosen：更好的回答" />
        <el-input v-model="preferenceForm.rejected" type="textarea" :rows="4" placeholder="Rejected：较差的回答" />
        <el-button type="primary" :disabled="!preferenceForm.prompt.trim() || !preferenceForm.chosen.trim() || !preferenceForm.rejected.trim()" @click="createPreference">{{ preferenceEditing ? '保存并重新审核' : '创建偏好对' }}</el-button><el-button v-if="preferenceEditing" @click="preferenceEditing = null; preferenceForm.prompt = ''; preferenceForm.chosen = ''; preferenceForm.rejected = ''">取消编辑</el-button>
      </aside>
      <main class="preference-list"><el-empty v-if="!preferences.length" description="还没有 DPO 偏好对" />
        <article v-for="item in preferences" :key="item.id" class="preference-card">
          <header><span>{{ item.source_type === 'distillation_review' ? '蒸馏审核' : '手工创建' }}</span><el-tag :type="sampleStatus(item)[1]">{{ sampleStatus(item)[0] }}</el-tag></header>
          <p class="preference-prompt">{{ item.context_messages.at(-1)?.content }}</p>
          <div class="preference-answers"><section><b>CHOSEN</b><p>{{ item.chosen_response.content }}</p></section><section><b>REJECTED</b><p>{{ item.rejected_response.content }}</p></section></div>
          <el-alert v-for="issue in item.issues" :key="issue.rule" :title="issue.message" type="warning" :closable="false" />
          <footer><el-button v-if="item.source_type === 'manual' && item.context_messages.length === 1" text @click="editPreference(item)">编辑</el-button><el-button text type="danger" @click="deletePreference(item)">删除</el-button><template v-if="item.review_status === 'pending'"><el-button @click="reviewPreference(item, 'rejected')">拒绝</el-button><el-button type="success" :disabled="item.validation_status !== 'passed'" @click="reviewPreference(item, 'approved')">通过</el-button></template></footer>
        </article>
      </main>
    </div>
  </el-dialog>
  <el-dialog v-model="versionDialog" class="version-dialog" width="min(1080px, calc(100% - 28px))" destroy-on-close>
    <template #header>
      <div class="preview-dialog-title"><strong>数据集版本</strong><span>把当前可导出样本冻结为不可变快照，用同一份内容重复导出。</span></div>
    </template>
    <div v-loading="versionLoading" class="version-workbench">
      <aside class="version-create">
        <h3>创建发布快照</h3>
        <p>只收录当前审核和校验均通过的数据。</p><el-segmented v-model="versionForm.dataset_type" :options="[{ label: 'SFT', value: 'sft' }, { label: 'DPO', value: 'dpo' }]" /><el-input v-model="versionForm.name" maxlength="100"
          placeholder="版本名称，例如 v1.0" /><el-input v-model="versionForm.description" type="textarea" :rows="3"
          maxlength="1000" placeholder="说明本次数据变化（可选）" /><el-button type="primary" :disabled="!versionForm.name.trim()"
          @click="createVersion">冻结当前版本</el-button>
        <div class="version-export-format"><span>版本导出格式</span><el-select v-model="exportForm.format"><el-option
              label="ShareGPT" value="sharegpt" /><el-option label="Alpaca" value="alpaca" /></el-select><el-select
            v-model="exportForm.file_type"><el-option label="JSONL" value="jsonl" /><el-option label="JSON"
              value="json" /></el-select></div>
      </aside>
      <main class="version-history"><el-empty v-if="!versions.length" description="还没有版本，先冻结当前数据集" :image-size="64" />
        <div v-else class="version-list">
          <article v-for="version in versions" :key="version.id"><i />
            <div>
              <div class="version-name"><strong>{{ version.name }}</strong><el-tag size="small">{{ version.dataset_type?.toUpperCase() }}</el-tag><span>{{ version.sample_count }} 条</span>
              </div>
              <p>{{ version.description || '未填写版本说明' }}</p><small>{{ formatVersionDate(version.created_at) }} · 原始 {{
                version.statistics?.origins?.original || 0 }} / 扩增 {{ version.statistics?.origins?.augmentation || 0 }}
                /
                蒸馏 {{ version.statistics?.origins?.distillation || 0 }}</small>
            </div>
            <div class="version-actions"><el-button text @click="exportVersion(version)">导出</el-button><el-button text
                type="primary" @click="openTrainingPackage(version)">训练包</el-button></div>
          </article>
        </div>
        <section v-if="versions.length > 1" class="version-compare">
          <header>
            <div>
              <h3>比较版本</h3>
              <p>查看两个不可变快照之间的数据变化。</p>
            </div><el-button
              :disabled="!versionCompare.base_id || !versionCompare.target_id || versionCompare.base_id === versionCompare.target_id"
              @click="compareVersions">开始比较</el-button>
          </header>
          <div class="version-selectors"><el-select v-model="versionCompare.base_id" placeholder="基准版本"><el-option
                v-for="version in versions" :key="version.id" :label="version.name"
                :value="version.id" /></el-select><span>对比</span><el-select v-model="versionCompare.target_id"
              placeholder="目标版本"><el-option v-for="version in versions" :key="version.id" :label="version.name"
                :value="version.id" /></el-select></div>
          <div v-if="versionDiff" class="version-diff">
            <div><strong>+{{ versionDiff.counts.added }}</strong><span>新增</span></div>
            <div><strong>−{{ versionDiff.counts.removed }}</strong><span>移除</span></div>
            <div><strong>{{ versionDiff.counts.changed }}</strong><span>内容变化</span></div>
            <div><strong>{{ versionDiff.counts.replaced }}</strong><span>蒸馏替代</span></div>
          </div>
        </section>
      </main>
    </div>
  </el-dialog>
  <el-dialog v-model="trainingPackageDialog" class="training-package-dialog" width="min(980px, calc(100% - 28px))"
    destroy-on-close>
    <template #header>
      <div class="preview-dialog-title"><strong>生成 LLaMA-Factory 训练包</strong><span>从不可变版本生成可迁移
          ZIP；只打包数据和配置，不连接训练服务器。</span></div>
    </template>
    <div class="training-package-layout">
      <main class="training-package-form">
        <section>
          <div class="package-section-title"><span>01</span>
            <div>
              <h3>模型与适配</h3>
              <p>这些值会写入 {{ trainingPackageVersion?.dataset_type === 'dpo' ? 'train_dpo.yaml' : 'train_sft.yaml' }}，下载后仍可修改。</p>
            </div>
          </div>
          <div class="package-fields"><label class="field-wide"><span>基础模型名称或路径</span><el-input
                v-model="trainingPackageForm.model_name_or_path" maxlength="500"
                placeholder="例如 Qwen/Qwen2.5-7B-Instruct" /></label><label><span>模型模板</span><el-select
                v-model="trainingPackageForm.template" filterable allow-create default-first-option><el-option
                  v-for="item in templatePresets" :key="item" :label="item"
                  :value="item" /></el-select></label><label><span>微调方式</span><el-segmented
                v-model="trainingPackageForm.finetuning_type"
                :options="[{ label: 'LoRA', value: 'lora' }, { label: '全量微调', value: 'full' }]" /></label></div>
        </section>
        <section>
          <div class="package-section-title"><span>02</span>
            <div>
              <h3>训练参数</h3>
              <p>提供稳定的 SFT 基础配置，不预设显卡精度和量化方式。</p>
            </div>
          </div>
          <div class="package-fields parameter-fields">
            <label>
              <span>截断长度</span>
              <el-input-number v-model="trainingPackageForm.cutoff_len" :min="128" :max="131072" :step="128"
                controls-position="right" />
            </label>
            <label>
              <span>训练轮数</span>
              <el-input-number v-model="trainingPackageForm.num_train_epochs" :min="0.1" :max="100" :step="0.5"
                controls-position="right" />
            </label>
            <label>
              <span>学习率</span>
              <el-input v-model="trainingPackageForm.learning_rate" placeholder="例如：5e-5" />
            </label>
            <label>
              <span>单设备批次</span>
              <el-input-number v-model="trainingPackageForm.per_device_train_batch_size" :min="1" :max="1024"
                controls-position="right" />
            </label>
            <label>
              <span>梯度累积</span>
              <el-input-number v-model="trainingPackageForm.gradient_accumulation_steps" :min="1" :max="1024"
                controls-position="right" />
            </label>
            <label>
              <span>输出目录名</span>
              <el-input v-model="trainingPackageForm.output_dir_name" maxlength="100" />
            </label>
            <label v-if="trainingPackageVersion?.dataset_type === 'dpo'"><span>DPO beta</span><el-input-number v-model="trainingPackageForm.pref_beta" :min="0.01" :max="10" :step="0.05" /></label>
            <label v-if="trainingPackageVersion?.dataset_type === 'dpo'"><span>偏好损失</span><el-select v-model="trainingPackageForm.pref_loss"><el-option label="Sigmoid" value="sigmoid" /><el-option label="Hinge" value="hinge" /><el-option label="IPO" value="ipo" /></el-select></label>
          </div>
        </section>
      </main>
      <aside class="training-package-summary">
        <div class="package-kicker">PACKAGE READY</div>
        <h3>{{ trainingPackageVersion?.name }}</h3><strong>{{ trainingPackageVersion?.sample_count || 0
        }}</strong><span>条冻结样本</span>
        <ol>
          <li><b>01</b><span>ShareGPT JSONL<small>保留多轮消息结构</small></span></li>
          <li><b>02</b><span>训练配置<small>模型、模板与 SFT 参数</small></span></li>
          <li><b>03</b><span>清单与说明<small>版本血缘和运行命令</small></span></li>
        </ol>
        <p>压缩包不包含模型权重、API Key 或训练框架程序。</p>
      </aside>
    </div>
    <template #footer>
      <div class="training-package-footer"><span>ZIP 内含 data/、训练 YAML、manifest.json 与 README.md</span>
        <div><el-button @click="trainingPackageDialog = false">取消</el-button><el-button type="primary" :icon="Download"
            :loading="trainingPackageLoading" :disabled="!trainingPackageForm.model_name_or_path.trim()"
            @click="buildTrainingPackage">生成并下载</el-button></div>
      </div>
    </template>
  </el-dialog>
  <el-drawer v-model="drawer" :title="`样本 #${detail?.id?.slice(0, 8) || ''}`" size="min(680px, 100%)"
    class="sample-drawer">
    <template v-if="detail">
      <div class="drawer-status"><el-tag :type="sampleStatus(detail)[1]" round>{{ sampleStatus(detail)[0]
          }}</el-tag><span>来源内容块 #{{ detail.chunk_id.slice(0, 8) }}</span><span v-if="detail.parent_sample_id">扩增自样本 #{{
            detail.parent_sample_id.slice(0, 8) }}</span></div>
      <div class="drawer-section">
        <h3>消息内容</h3>
        <p v-if="detail.distillation_source_id" class="field-hint">教师根据来源和原问题独立作答，源样本 #{{
          detail.distillation_source_id.slice(0, 8) }}；审核通过后会替代该源样本。</p>
        <div v-for="(message, index) in messages" :key="index" class="message-card">
          <div class="message-head"><el-select v-model="message.role"><el-option label="system"
                value="system" /><el-option label="user" value="user" /><el-option label="assistant"
                value="assistant" /></el-select><el-button text type="danger"
              @click="messages.splice(index, 1)">移除</el-button></div><el-input v-model="message.content" type="textarea"
            :rows="3" />
        </div><el-button text type="primary" @click="messages.push({ role: 'user', content: '' })">＋
          添加消息</el-button><el-button type="primary" :loading="busy" @click="saveMessages">保存修改</el-button>
      </div>
      <div class="drawer-section">
        <h3>来源内容</h3>
        <pre class="source-preview">{{ detail.chunk_content || '无来源内容' }}</pre>
      </div>
      <div class="drawer-section">
        <h3>校验结果</h3><el-alert v-if="!detail.issues.length" title="结构与内容校验通过" type="success" :closable="false"
          show-icon /><el-alert v-for="issue in detail.issues" :key="issue.rule"
          :title="`${issue.rule}：${issue.message}`" type="warning" :closable="false" class="issue-alert" />
      </div>
    </template>
    <template #footer>
      <div v-if="detail" class="drawer-actions"><el-button :loading="busy"
          @click="regenerate">重新生成此内容块</el-button><el-button type="success" :icon="Check" :loading="busy"
          @click="review('approved')">通过</el-button><el-button :loading="busy"
          @click="review('rejected')">拒绝</el-button><el-button type="danger" plain :loading="busy"
          @click="toggleDeleted">{{ detail.is_deleted ? '恢复样本' : '软删除' }}</el-button></div>
    </template>
  </el-drawer>
</template>
