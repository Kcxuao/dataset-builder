<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, jsonOptions, notifyError } from '../api'

const models = ref([])
const form = reactive({ parser_workers: 1, default_model_id: '' })
const saving = ref(false)
async function load() {
  try {
    const [settings, availableModels] = await Promise.all([api('/api/workspace/settings'), api('/api/models')])
    form.parser_workers = settings.parser_workers
    form.default_model_id = settings.default_model_id || ''
    models.value = availableModels
  } catch (error) { notifyError(error, ElMessage) }
}
async function save() {
  saving.value = true
  try { await api('/api/workspace/settings', jsonOptions('PUT', { parser_workers: form.parser_workers, default_model_id: form.default_model_id || null })); ElMessage.success('处理设置已保存，新任务将使用这些参数') }
  catch (error) { notifyError(error, ElMessage) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="settings-layout"><section class="section-card"><div class="section-heading"><div><p class="eyebrow">PROCESSING DEFAULTS</p><h2>任务默认参数</h2><span class="section-subtitle">修改仅影响之后创建的任务</span></div></div><el-form label-position="top" class="settings-form"><el-form-item label="解析工作线程数"><el-input-number v-model="form.parser_workers" :min="1" :max="16" /><p class="field-hint">结构化文件中的独立记录可并行解析；单个 TXT 或 Markdown 文件仍只有一个解析任务。</p></el-form-item><el-form-item label="默认模型"><el-select v-model="form.default_model_id"><el-option label="环境配置模型" value="" /><el-option v-for="model in models" :key="model.id" :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item><el-button type="primary" :loading="saving" @click="save">保存设置</el-button></el-form></section><aside class="settings-aside"><span class="aside-index">02 / SETTINGS</span><h3>并发各归其位。</h3><p>解析线程数在这里统一设置。模型请求并发上限由每个模型单独控制，在模型配置页面调整。</p></aside></div>
</template>
