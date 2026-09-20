<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue'
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
const form = reactive({ project_name: '', generator: 'qa', model_id: '', prompt_id: '', splitter: 'auto', max_chars: 1000, overlap: 0, content_field: '', content_columns: '' })
const filteredPrompts = computed(() => prompts.value.filter(item => item.mode === form.generator))
const currentPrompt = computed(() => prompts.value.find(item => item.id === form.prompt_id))

function selectFile(event) {
  file.value = event.target.files?.[0] || null
  if (file.value && !form.project_name) form.project_name = file.value.name.replace(/\.[^.]+$/, '')
}
function chooseMode() { form.prompt_id = filteredPrompts.value[0]?.id || '' }
async function load() {
  try {
    [models.value, prompts.value, defaults.value] = await Promise.all([
      api('/api/models'), api('/api/prompts'), api('/api/workspace/settings'),
    ])
    chooseMode()
  } catch (error) { notifyError(error, ElMessage) }
}
async function submit() {
  if (!file.value) { ElMessage.warning('请先选择源文件'); return }
  if (!form.prompt_id) { ElMessage.warning('请先配置提示词'); return }
  submitting.value = true
  try {
    const data = new FormData()
    data.append('file', file.value)
    for (const key of ['project_name', 'generator', 'splitter', 'max_chars', 'overlap', 'content_field', 'content_columns', 'prompt_id']) {
      if (form[key] !== '') data.append(key, form[key])
    }
    if (form.model_id) data.append('model_id', form.model_id)
    const result = await api('/api/projects/build', { method: 'POST', body: data })
    await refreshProjects()
    ElMessage.success('构建任务已创建')
    router.push(`/projects/${result.project_id}`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { submitting.value = false }
}
onMounted(load)
</script>

<template>
  <div class="create-layout">
    <section class="section-card create-card">
      <div class="section-heading"><div><p class="eyebrow">NEW DATASET</p><h2>导入与生成</h2></div><span class="step-chip">01 / 03</span></div>
      <el-form label-position="top" class="create-form" @submit.prevent="submit">
        <el-form-item label="源文件" required>
          <label class="upload-zone"><input type="file" accept=".txt,.md,.markdown,.json,.jsonl,.csv" @change="selectFile" /><el-icon><UploadFilled /></el-icon><strong>{{ file ? file.name : '点击选择文件' }}</strong><span>支持 TXT、Markdown、JSON、JSONL、CSV</span></label>
        </el-form-item>
        <el-form-item label="数据集名称"><el-input v-model="form.project_name" placeholder="默认使用文件名" /></el-form-item>
        <div class="form-two"><el-form-item label="生成方式"><el-select v-model="form.generator" @change="chooseMode"><el-option label="问答样本" value="qa" /><el-option label="指令样本" value="instruction" /></el-select></el-form-item><el-form-item label="生成模型"><el-select v-model="form.model_id"><el-option label="工作区默认模型" value="" /><el-option v-for="model in models" :key="model.id" :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item></div>
        <el-form-item label="提示词模板"><el-select v-model="form.prompt_id" placeholder="选择提示词"><el-option v-for="prompt in filteredPrompts" :key="prompt.id" :label="prompt.name" :value="prompt.id" /></el-select><p v-if="currentPrompt" class="field-hint">{{ currentPrompt.instruction }}</p></el-form-item>
        <div class="form-two"><el-form-item label="切分方式"><el-select v-model="form.splitter"><el-option label="自动切分" value="auto" /><el-option label="按段落" value="paragraph" /><el-option label="固定长度" value="fixed" /><el-option label="Markdown 标题" value="markdown" /></el-select></el-form-item><el-form-item label="最大字符数"><el-input-number v-model="form.max_chars" :min="1" :controls="false" /></el-form-item></div>
        <div class="form-two"><el-form-item label="重叠字符数"><el-input-number v-model="form.overlap" :min="0" :controls="false" /></el-form-item><el-form-item label="JSON / JSONL 内容字段"><el-input v-model="form.content_field" placeholder="例如 article.body" /></el-form-item></div>
        <el-form-item label="CSV 内容列"><el-input v-model="form.content_columns" placeholder="例如 title,body" /></el-form-item>
        <el-button type="primary" size="large" :loading="submitting" class="submit-button" @click="submit">开始构建数据集</el-button>
      </el-form>
    </section>
    <aside class="create-aside">
      <div class="guidance-card"><div class="guidance-icon"><el-icon><DocumentAdd /></el-icon></div><p class="eyebrow">HOW IT WORKS</p><h3>每条样本<br />都有出处。</h3><p>系统会记录从源文档到内容块，再到训练样本的完整关联。生成后可逐条检查、修改和审核。</p><div class="mini-flow"><span>导入</span><i></i><span>生成</span><i></i><span>审核</span><i></i><span>导出</span></div></div>
      <div class="aside-note"><el-icon><InfoFilled /></el-icon><span>当前默认解析线程数：{{ defaults.parser_workers }}。可在处理设置中修改。</span></div>
    </aside>
  </div>
</template>
