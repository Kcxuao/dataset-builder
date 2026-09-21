<script setup>
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DocumentAdd, InfoFilled, UploadFilled } from '@element-plus/icons-vue'
import { api, notifyError } from '../api'

const router = useRouter()
const refreshProjects = inject('refreshProjects')
const models = ref([])
const prompts = ref([])
const defaults = ref({ parser_workers: 1, default_model_id: null })
const file = ref(null)
const submitting = ref(false)
const previewing = ref(false)
const trialing = ref(false)
const previewDialogVisible = ref(false)
const preview = ref(null)
const trial = ref(null)
const selectedChunks = ref([])
const selectedChunkCount = computed(() => selectedChunks.value.length)
const fileType = computed(() => file.value?.name.split('.').pop()?.toLowerCase() || '')
const needsContentField = computed(() => ['json', 'jsonl'].includes(fileType.value))
const needsContentColumns = computed(() => fileType.value === 'csv')
const form = reactive({ project_name: '', generator: 'qa', model_id: '', prompt_id: '', splitter: 'auto', max_chars: 1000, overlap: 0, content_field: '', content_columns: '' })
const filteredPrompts = computed(() => prompts.value.filter(item => item.mode === form.generator))
const currentPrompt = computed(() => prompts.value.find(item => item.id === form.prompt_id))

function selectFile(event) {
  file.value = event.target.files?.[0] || null
  if (file.value && !form.project_name) form.project_name = file.value.name.replace(/\.[^.]+$/, '')
  clearPreview()
}
function clearPreview() { preview.value = null; trial.value = null; selectedChunks.value = []; previewDialogVisible.value = false }
function chooseMode() { form.prompt_id = filteredPrompts.value[0]?.id || ''; clearPreview() }
function roleLabel(role) { return { system: '系统', user: '用户', assistant: '助手' }[role] || role }
async function load() {
  try {
    [models.value, prompts.value, defaults.value] = await Promise.all([
      api('/api/models'), api('/api/prompts'), api('/api/workspace/settings'),
    ])
    chooseMode()
  } catch (error) { notifyError(error, ElMessage) }
}
function validateForm() {
  if (!file.value) { ElMessage.warning('请先选择源文件'); return false }
  if (!form.prompt_id) { ElMessage.warning('请先配置提示词'); return false }
  if (needsContentField.value && !form.content_field.trim()) { ElMessage.warning('请填写 JSON 内容字段'); return false }
  if (needsContentColumns.value && !form.content_columns.trim()) { ElMessage.warning('请填写 CSV 内容列'); return false }
  return true
}
function buildData(extra = {}) {
  const data = new FormData()
  data.append('file', file.value)
  for (const key of ['project_name', 'generator', 'splitter', 'max_chars', 'overlap', 'prompt_id']) {
    if (form[key] !== '') data.append(key, form[key])
  }
  if (needsContentField.value) data.append('content_field', form.content_field.trim())
  if (needsContentColumns.value) data.append('content_columns', form.content_columns.trim())
  if (form.model_id) data.append('model_id', form.model_id)
  for (const [key, value] of Object.entries(extra)) data.append(key, value)
  return data
}
async function loadPreview() {
  if (!validateForm()) return
  previewing.value = true
  try {
    preview.value = await api('/api/projects/preview', { method: 'POST', body: buildData() })
    trial.value = null; selectedChunks.value = []
    previewDialogVisible.value = true
    ElMessage.success('预览已更新，尚未调用模型')
  } catch (error) { notifyError(error, ElMessage) }
  finally { previewing.value = false }
}
async function generateTrial() {
  if (!preview.value) return
  if (!selectedChunks.value.length || selectedChunks.value.length > 3) { ElMessage.warning('请选择 1 到 3 个内容块'); return }
  trialing.value = true
  try {
    trial.value = await api('/api/projects/preview/generate', {
      method: 'POST', body: buildData({ fingerprint: preview.value.fingerprint, chunk_indices: selectedChunks.value.join(',') }),
    })
  } catch (error) { notifyError(error, ElMessage) }
  finally { trialing.value = false }
}
async function submit() {
  if (!validateForm()) return
  submitting.value = true
  try {
    const result = await api('/api/projects/build', { method: 'POST', body: buildData() })
    await refreshProjects()
    ElMessage.success('构建任务已创建')
    router.push(`/projects/${result.project_id}`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { submitting.value = false }
}
watch(form, clearPreview, { deep: true })
onMounted(load)
</script>

<template>
  <div class="create-layout">
    <section class="section-card create-card">
      <div class="section-heading"><div><h2>导入与生成</h2><span class="section-subtitle">选择来源文件，再设置生成与切分方式</span></div></div>
      <el-form label-position="top" class="create-form" @submit.prevent="submit">
        <h3 class="form-group-title">来源文件</h3>
        <el-form-item label="源文件" required>
          <label class="upload-zone"><input type="file" accept=".txt,.md,.markdown,.json,.jsonl,.csv" aria-label="选择源文件" @change="selectFile" /><el-icon><UploadFilled /></el-icon><strong>{{ file ? file.name : '点击或按回车选择文件' }}</strong><span>支持 TXT、Markdown、JSON、JSONL、CSV</span></label>
        </el-form-item>
        <el-form-item label="数据集名称"><el-input v-model="form.project_name" placeholder="默认使用文件名" /></el-form-item>
        <el-form-item v-if="needsContentField" label="JSON 内容字段" required><el-input v-model="form.content_field" placeholder="例如 article.body" /><p class="field-hint">指定每条记录中用于生成样本的文本字段。</p></el-form-item>
        <el-form-item v-if="needsContentColumns" label="CSV 内容列" required><el-input v-model="form.content_columns" placeholder="例如 title,body" /><p class="field-hint">多个列名用英文逗号分隔。</p></el-form-item>
        <h3 class="form-group-title">生成配置</h3>
        <div class="form-two"><el-form-item label="生成方式"><el-select v-model="form.generator" @change="chooseMode"><el-option label="问答样本" value="qa" /><el-option label="指令样本" value="instruction" /></el-select></el-form-item><el-form-item label="生成模型"><el-select v-model="form.model_id"><el-option label="工作区默认模型" value="" /><el-option v-for="model in models" :key="model.id" :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item></div>
        <el-form-item label="提示词模板"><el-select v-model="form.prompt_id" placeholder="选择提示词"><el-option v-for="prompt in filteredPrompts" :key="prompt.id" :label="prompt.name" :value="prompt.id" /></el-select><p v-if="currentPrompt" class="field-hint">{{ currentPrompt.instruction }}</p></el-form-item>
        <h3 class="form-group-title">切分配置</h3>
        <div class="form-two"><el-form-item label="切分方式"><el-select v-model="form.splitter"><el-option label="自动切分" value="auto" /><el-option label="按段落" value="paragraph" /><el-option label="固定长度" value="fixed" /><el-option label="Markdown 标题" value="markdown" /></el-select></el-form-item><el-form-item label="最大字符数"><el-input-number v-model="form.max_chars" :min="1" :controls="false" /></el-form-item></div>
        <el-form-item label="重叠字符数"><el-input-number v-model="form.overlap" :min="0" :controls="false" /></el-form-item>
        <div class="form-actions"><el-button size="large" :loading="previewing" @click="loadPreview">生成前预览</el-button><el-button type="primary" size="large" :loading="submitting" class="submit-button" @click="submit">开始完整构建</el-button></div>
      </el-form>
    </section>
    <aside class="create-aside">
      <div class="guidance-card"><div class="guidance-icon"><el-icon><DocumentAdd /></el-icon></div><h3>每条样本<br />都有出处。</h3><p>系统会记录从源文档到内容块，再到训练样本的完整关联。生成后可逐条检查、修改和审核。</p><div class="mini-flow"><span>导入</span><i></i><span>生成</span><i></i><span>审核</span><i></i><span>导出</span></div></div>
      <div class="aside-note"><el-icon><InfoFilled /></el-icon><span>当前默认解析线程数：{{ defaults.parser_workers }}。可在处理设置中修改。</span></div>
    </aside>
    <el-dialog v-model="previewDialogVisible" class="preview-dialog" width="calc(100% - 48px)" top="5vh" destroy-on-close>
      <template #header><div class="preview-dialog-title"><strong>生成前检查</strong><span>查看切分结果，必要时试生成少量样本。</span></div></template>
      <div v-if="preview" aria-live="polite">
        <section class="generation-preview">
          <header class="preview-header">
            <div><h3>切分预览</h3><p>确认内容块边界后，再决定是否试生成。</p></div>
            <el-tag effect="plain" type="info">预览未调用模型</el-tag>
          </header>
          <div class="preview-metrics">
            <div><strong>{{ preview.document_count }}</strong><span>源文档</span></div>
            <div><strong>{{ preview.chunk_count }}</strong><span>内容块</span></div>
            <div><strong>{{ preview.estimated_request_upper_bound }}</strong><span>完整构建请求上界</span></div>
            <div v-if="preview.max_output_tokens"><strong>{{ preview.max_output_tokens }}</strong><span>单次输出上限 tokens</span></div>
          </div>
          <div class="preview-instruction"><span>从下方选择 1–3 个内容块试生成</span><small>实际费用取决于模型输出。</small></div>
          <el-checkbox-group v-model="selectedChunks" :max="3" class="chunk-picker">
            <article v-for="chunk in preview.chunks" :key="chunk.index" class="chunk-card" :class="{ 'is-selected': selectedChunks.includes(chunk.index) }">
              <div class="chunk-card-head"><el-checkbox :label="chunk.index"><span class="chunk-number">#{{ chunk.index + 1 }}</span><strong>{{ chunk.source_name }}</strong></el-checkbox><span>{{ chunk.length }} 字</span></div>
              <p>{{ chunk.content }}</p>
            </article>
          </el-checkbox-group>
          <footer class="preview-actions"><span>已选 <b>{{ selectedChunkCount }}</b> / 3 个内容块</span><el-button type="primary" :disabled="!selectedChunks.length" :loading="trialing" @click="generateTrial">试生成所选内容块</el-button></footer>
        </section>
        <section v-if="trial" class="trial-results" aria-live="polite">
          <header class="preview-header"><div><h3>试生成结果</h3><p>仅用于检查，不会保存到当前项目。</p></div><el-tag type="success" effect="plain">{{ trial.samples.length }} 条临时样本</el-tag></header>
          <div v-if="trial.samples.length" class="trial-sample-list">
            <article v-for="(sample, sampleIndex) in trial.samples" :key="sample.id" class="trial-sample">
              <div class="trial-sample-head"><span>样本 {{ sampleIndex + 1 }}</span><span>临时结果</span></div>
              <div v-for="(message, messageIndex) in sample.messages" :key="`${message.role}-${messageIndex}`" class="trial-message" :class="`role-${message.role}`">
                <span>{{ roleLabel(message.role) }}</span><p>{{ message.content }}</p>
              </div>
            </article>
          </div>
          <el-empty v-else description="模型没有返回可检查的样本" :image-size="64" />
          <div v-if="trial.issues.length" class="trial-issues"><el-alert v-for="issue in trial.issues" :key="issue.id" type="warning" :title="issue.message" :closable="false" show-icon /></div>
        </section>
      </div>
    </el-dialog>
  </div>
</template>
