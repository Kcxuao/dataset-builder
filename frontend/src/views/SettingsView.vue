<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, jsonOptions, notifyError } from '../api'

const models = ref([])
const database = ref(null)
const form = reactive({ parser_workers: 1, default_model_id: '' })
const saving = ref(false)
async function load() {
  try {
    const [settings, availableModels, databaseStatus] = await Promise.all([api('/api/workspace/settings'), api('/api/models'), api('/api/system/database')])
    form.parser_workers = settings.parser_workers
    form.default_model_id = settings.default_model_id || ''
    models.value = availableModels
    database.value = databaseStatus
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
  <div class="settings-layout"><section class="section-card"><div class="section-heading"><div><h2>任务默认参数</h2><span class="section-subtitle">修改仅影响之后创建的任务</span></div></div><el-form label-position="top" class="settings-form"><el-form-item label="解析工作线程数"><el-input-number v-model="form.parser_workers" :min="1" :max="16" /><p class="field-hint">结构化文件中的独立记录可并行解析；单个 TXT 或 Markdown 文件仍只有一个解析任务。</p></el-form-item><el-form-item label="默认模型"><el-select v-model="form.default_model_id"><el-option label="环境配置模型" value="" /><el-option v-for="model in models" :key="model.id" :label="`${model.name} · ${model.model}`" :value="model.id" /></el-select></el-form-item><el-button type="primary" :loading="saving" @click="save">保存设置</el-button></el-form></section><aside class="settings-aside"><h3>{{ database?.label || '数据存储' }}</h3><p>{{ database?.scope || '正在读取数据库配置' }}</p><p>在启动配置中设置 <code>DATABASE_PROVIDER=sqlite</code> 或 <code>postgresql</code>，修改后重启服务生效。</p></aside></div>
</template>
