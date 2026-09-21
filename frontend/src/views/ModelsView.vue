<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, EditPen, Plus, Refresh, Star } from '@element-plus/icons-vue'
import { api, jsonOptions, notifyError } from '../api'

const emptyForm = () => ({
  name: '', base_url: '', model: '', api_key: '', temperature: 0.7, max_tokens: 1024,
  timeout: 60, concurrency_limit: 4, max_retries: 2, json_mode: false, thinking: '',
})
const models = ref([])
const providers = ref([])
const discoveredModels = ref([])
const settings = ref({ parser_workers: 1, default_model_id: null })
const connectionChecks = ref({})
const dialog = ref(false)
const editing = ref(null)
const saving = ref(false)
const discovering = ref(false)
const checkingConnections = ref(false)
const providerId = ref('custom')
const form = reactive(emptyForm())
const dialogTitle = computed(() => editing.value ? '编辑模型' : '新增模型')

async function load() {
  try {
    [models.value, settings.value, providers.value] = await Promise.all([
      api('/api/models'), api('/api/workspace/settings'), api('/api/model-providers'),
    ])
    connectionChecks.value = {}
    await checkConnections()
  } catch (error) { notifyError(error, ElMessage) }
}
function connectionState(model) {
  return connectionChecks.value[model.id] || { status: 'checking', message: '正在检查连接' }
}
function connectionLabel(model) {
  const status = connectionState(model).status
  return { checking: '检查中', connected: '连接正常', unavailable: '连接异常' }[status] || '未检查'
}
async function checkConnections(modelIds = [], showError = false) {
  const ids = modelIds.length ? modelIds : models.value.map((model) => model.id)
  if (!ids.length) return
  checkingConnections.value = !modelIds.length
  connectionChecks.value = {
    ...connectionChecks.value,
    ...Object.fromEntries(ids.map((id) => [id, { status: 'checking', message: '正在检查连接' }])),
  }
  try {
    const result = await api('/api/models/connection-check', jsonOptions('POST', { model_ids: ids }))
    connectionChecks.value = {
      ...connectionChecks.value,
      ...Object.fromEntries(result.checks.map((item) => [item.model_id, item])),
    }
  } catch (error) {
    connectionChecks.value = {
      ...connectionChecks.value,
      ...Object.fromEntries(ids.map((id) => [id, { status: 'unavailable', message: error.message }])),
    }
    if (showError) notifyError(error, ElMessage)
  } finally { checkingConnections.value = false }
}
async function refreshConnection(model) {
  await checkConnections([model.id], true)
}
function openForm(model = null) {
  editing.value = model?.id || null
  Object.assign(form, model
    ? { ...model, api_key: '', thinking: model.thinking === null ? '' : String(model.thinking) }
    : emptyForm())
  providerId.value = 'custom'
  discoveredModels.value = []
  dialog.value = true
}
function applyProvider(id) {
  const provider = providers.value.find((item) => item.id === id)
  if (!provider?.base_url) return
  form.name = provider.name
  form.base_url = provider.base_url
  form.api_key = ''
  form.model = ''
  discoveredModels.value = []
}
async function discoverModels() {
  discovering.value = true
  try {
    const result = await api('/api/models/discover', jsonOptions('POST', {
      base_url: form.base_url,
      api_key: form.api_key || null,
      model_id: editing.value || null,
    }))
    discoveredModels.value = result.models
    ElMessage.success(`已获取 ${result.models.length} 个模型，可选择或继续手动填写`)
  } catch (error) { notifyError(error, ElMessage) }
  finally { discovering.value = false }
}
async function save() {
  saving.value = true
  try {
    const data = {
      ...form,
      api_key: form.api_key || null,
      thinking: form.thinking === '' ? null : form.thinking === 'true',
    }
    await api(
      editing.value ? `/api/models/${editing.value}` : '/api/models',
      jsonOptions(editing.value ? 'PUT' : 'POST', data),
    )
    dialog.value = false
    form.api_key = ''
    await load()
    ElMessage.success('模型配置已保存')
  } catch (error) { notifyError(error, ElMessage) }
  finally { saving.value = false }
}
async function setDefault(model) {
  try {
    settings.value = await api('/api/workspace/settings', jsonOptions('PUT', {
      parser_workers: settings.value.parser_workers, default_model_id: model.id,
    }))
    ElMessage.success(`已将“${model.name}”设为默认模型`)
  } catch (error) { notifyError(error, ElMessage) }
}
async function archive(model) {
  try {
    await ElMessageBox.confirm(
      `归档“${model.name}”？历史任务仍可使用原配置重试。`, '归档模型',
      { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' },
    )
    await api(`/api/models/${model.id}`, { method: 'DELETE' })
    await load()
    ElMessage.success('模型已归档')
  } catch (error) {
    if (error !== 'cancel') notifyError(error, ElMessage)
  }
}
onMounted(load)
</script>

<template>
  <section class="section-card">
    <div class="section-heading">
      <div><h2>可用模型</h2><span class="section-subtitle">管理多个兼容 OpenAI 接口的模型配置</span></div>
      <div class="section-actions"><el-button :icon="Refresh" :loading="checkingConnections" @click="checkConnections([], true)">刷新状态</el-button><el-button type="primary" :icon="Plus" @click="openForm()">新增模型</el-button></div>
    </div>
    <el-empty v-if="!models.length" description="还没有模型配置，可添加第一个模型" :image-size="110">
      <el-button type="primary" @click="openForm()">新增模型</el-button>
    </el-empty>
    <div v-else class="model-grid">
      <div v-for="model in models" :key="model.id" class="model-card">
        <div class="model-card-top"><div class="model-monogram">{{ model.name.slice(0, 1) }}</div><div class="model-card-status"><span class="model-connection" :class="`is-${connectionState(model).status}`" :title="connectionState(model).message"><i></i>{{ connectionLabel(model) }}</span><el-tag v-if="settings.default_model_id === model.id" type="primary" effect="light" round>默认模型</el-tag><el-tag v-else effect="plain" round>已启用</el-tag></div></div>
        <h3>{{ model.name }}</h3><p>{{ model.model }}</p><div class="model-url">{{ model.base_url }}</div>
        <div class="model-facts"><span>并发 {{ model.concurrency_limit }}</span><span>最大令牌 {{ model.max_tokens }}</span><span>{{ model.has_api_key ? '已配置密钥' : '无需密钥' }}</span></div>
        <div class="model-actions"><el-button text :icon="Refresh" :loading="connectionState(model).status === 'checking'" @click="refreshConnection(model)">刷新连接</el-button><el-button v-if="settings.default_model_id !== model.id" text type="primary" :icon="Star" @click="setDefault(model)">设为默认</el-button><el-button text :icon="EditPen" @click="openForm(model)">编辑</el-button><el-button text type="danger" :icon="Delete" @click="archive(model)">归档</el-button></div>
      </div>
    </div>
  </section>
  <el-dialog v-model="dialog" :title="dialogTitle" width="min(620px, 94vw)" destroy-on-close>
    <el-form label-position="top" class="dialog-form">
      <div class="form-two">
        <el-form-item label="服务预设"><el-select v-model="providerId" @change="applyProvider"><el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" /></el-select></el-form-item>
        <el-form-item label="配置名称" required><el-input v-model="form.name" /></el-form-item>
      </div>
      <el-form-item label="兼容接口地址" required><el-input v-model="form.base_url" placeholder="https://example.com/v1" /></el-form-item>
      <el-form-item :label="editing ? 'API Key（地址不变时可留空）' : 'API Key'"><el-input v-model="form.api_key" type="password" show-password autocomplete="off" /></el-form-item>
      <el-form-item label="模型名称" required>
        <div class="model-discovery">
          <el-select v-model="form.model" filterable allow-create clearable placeholder="拉取后选择，或直接手动填写">
            <el-option v-for="item in discoveredModels" :key="item.id" :label="item.owned_by ? `${item.id}（${item.owned_by}）` : item.id" :value="item.id" />
          </el-select>
          <el-button :icon="Refresh" :loading="discovering" :disabled="!form.base_url.trim()" @click="discoverModels">拉取模型</el-button>
        </div>
        <p class="field-hint">通过服务的标准模型列表接口拉取；服务不支持时可继续手动填写。</p>
      </el-form-item>
      <div class="form-two">
        <el-form-item label="温度"><el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" /></el-form-item><el-form-item label="最大令牌数"><el-input-number v-model="form.max_tokens" :min="1" /></el-form-item><el-form-item label="超时秒数"><el-input-number v-model="form.timeout" :min="1" /></el-form-item><el-form-item label="请求并发上限"><el-input-number v-model="form.concurrency_limit" :min="1" :max="32" /></el-form-item><el-form-item label="重试次数"><el-input-number v-model="form.max_retries" :min="0" :max="10" /></el-form-item>
        <el-form-item label="思考模式"><el-select v-model="form.thinking"><el-option label="使用服务默认设置" value="" /><el-option label="开启" value="true" /><el-option label="关闭" value="false" /></el-select></el-form-item>
      </div>
      <el-form-item label="JSON 输出模式"><el-switch v-model="form.json_mode" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存模型</el-button></template>
  </el-dialog>
</template>
