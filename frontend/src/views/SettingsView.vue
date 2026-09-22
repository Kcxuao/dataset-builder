<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, jsonOptions, notifyError } from '../api'

const models = ref([])
const database = ref(null)
const databaseSettings = ref(null)
const form = reactive({ parser_workers: 1, default_model_id: '' })
const databaseForm = reactive({
  provider: 'sqlite', sqlite_path: '', host: '127.0.0.1', port: 5432, database: '', username: '', password: '',
})
const saving = ref(false)
const savingDatabase = ref(false)
const testingDatabase = ref(false)
const databaseAvailable = computed(() => Boolean(database.value?.configurable))
const currentDatabaseLabel = computed(() => database.value?.label || '正在读取')
const pendingDatabaseLabel = computed(() => databaseForm.provider === 'sqlite' ? '本地 SQLite' : 'PostgreSQL')

function databasePayload() {
  return {
    provider: databaseForm.provider,
    sqlite_path: databaseForm.sqlite_path || null,
    host: databaseForm.host || null,
    port: databaseForm.port,
    database: databaseForm.database || null,
    username: databaseForm.username || null,
    password: databaseForm.password || null,
  }
}
function applyDatabaseSettings(settings) {
  databaseSettings.value = settings
  const saved = settings.saved
  Object.assign(databaseForm, {
    provider: saved.provider,
    sqlite_path: saved.sqlite_path || '',
    host: saved.host || '127.0.0.1',
    port: saved.port || 5432,
    database: saved.database || '',
    username: saved.username || '',
    password: '',
  })
}
async function load() {
  try {
    const [settings, availableModels, databaseStatus] = await Promise.all([
      api('/api/workspace/settings'), api('/api/models'), api('/api/system/database'),
    ])
    form.parser_workers = settings.parser_workers
    form.default_model_id = settings.default_model_id || ''
    models.value = availableModels
    database.value = databaseStatus
    if (databaseStatus.configurable) applyDatabaseSettings(await api('/api/system/database-settings'))
  } catch (error) { notifyError(error, ElMessage) }
}
async function save() {
  saving.value = true
  try {
    await api('/api/workspace/settings', jsonOptions('PUT', {
      parser_workers: form.parser_workers, default_model_id: form.default_model_id || null,
    }))
    ElMessage.success('处理设置已保存，新任务将使用这些参数')
  } catch (error) { notifyError(error, ElMessage) }
  finally { saving.value = false }
}
async function testDatabase() {
  testingDatabase.value = true
  try {
    const result = await api('/api/system/database-settings/test', jsonOptions('POST', databasePayload()))
    ElMessage.success(result.message)
  } catch (error) { notifyError(error, ElMessage) }
  finally { testingDatabase.value = false }
}
async function saveDatabase() {
  savingDatabase.value = true
  try {
    const result = await api('/api/system/database-settings', jsonOptions('PUT', databasePayload()))
    applyDatabaseSettings(result)
    ElMessage.success('数据库配置已保存，关闭并重新启动软件后生效')
  } catch (error) { notifyError(error, ElMessage) }
  finally { savingDatabase.value = false }
}
onMounted(load)
</script>

<template>
  <div class="settings-page">
    <section class="section-card settings-section">
      <div class="section-heading">
        <div><h2>任务默认参数</h2><span class="section-subtitle">修改仅影响之后创建的任务</span></div>
      </div>
      <el-form label-position="top" class="settings-form">
        <el-form-item label="解析工作线程数"><el-input-number v-model="form.parser_workers" :min="1" :max="16" />
          <p class="field-hint">结构化文件中的独立记录可并行解析；单个 TXT 或 Markdown 文件仍只有一个解析任务。</p>
        </el-form-item>
        <el-form-item label="默认模型"><el-select v-model="form.default_model_id"><el-option label="环境配置模型"
              value="" /><el-option v-for="model in models" :key="model.id" :label="`${model.name} · ${model.model}`"
              :value="model.id" /></el-select></el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存任务设置</el-button>
      </el-form>
    </section>

    <section class="section-card settings-section database-settings-card">
      <div class="section-heading database-heading">
        <div><h2>数据存储</h2><span class="section-subtitle">连接配置保存在本机用户目录，不写入业务数据库</span></div>
        <div class="database-route" aria-label="数据库切换状态">
          <span><small>当前</small>{{ currentDatabaseLabel }}</span><i>→</i><span><small>重启后</small>{{ pendingDatabaseLabel }}</span>
        </div>
      </div>
      <el-alert v-if="!databaseAvailable" type="info" :closable="false" show-icon
        title="当前启动方式未启用页面配置；请设置 DATASET_BUILDER_HOME 后重启服务。" />
      <el-alert v-else-if="databaseSettings?.restart_required" type="warning" :closable="false" show-icon
        title="已保存新的连接配置，当前页面仍在使用原数据库；关闭并重新启动软件后生效。" />
      <el-form label-position="top" class="database-form" :disabled="!databaseAvailable">
        <el-form-item label="数据库类型" class="database-provider-field">
          <el-radio-group v-model="databaseForm.provider">
            <el-radio-button value="sqlite">本地 SQLite</el-radio-button>
            <el-radio-button value="postgresql">PostgreSQL</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="databaseForm.provider === 'sqlite'">
          <el-form-item label="数据库文件路径" class="field-wide"><el-input v-model="databaseForm.sqlite_path"
              placeholder="留空使用软件默认数据目录" />
            <p class="field-hint">相对路径会以软件用户数据目录为基准。</p>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="服务器地址"><el-input v-model="databaseForm.host" placeholder="127.0.0.1" /></el-form-item>
          <el-form-item label="端口"><el-input-number v-model="databaseForm.port" :min="1" :max="65535" :controls="false" /></el-form-item>
          <el-form-item label="数据库名"><el-input v-model="databaseForm.database" placeholder="dataset_builder" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="databaseForm.username" autocomplete="username" /></el-form-item>
          <el-form-item label="密码" class="field-wide"><el-input v-model="databaseForm.password" type="password" show-password
              autocomplete="new-password" :placeholder="databaseSettings?.saved?.password_configured ? '已保存；留空继续使用原密码' : '请输入数据库密码'" />
            <p class="field-hint">密码不会返回页面；配置文件仅允许当前系统用户读取。</p>
          </el-form-item>
        </template>
        <div class="database-actions field-wide">
          <el-button :loading="testingDatabase" @click="testDatabase">测试连接</el-button>
          <el-button type="primary" :loading="savingDatabase" @click="saveDatabase">保存并在重启后使用</el-button>
        </div>
      </el-form>
    </section>

    <section class="migration-guide">
      <div><strong>切换前</strong><p>在当前数据库中完成审核并导出需要保留的数据集或版本。</p></div>
      <div><strong>保存并重启</strong><p>先测试连接，再保存配置；退出软件并重新打开，迁移会自动执行。</p></div>
      <div><strong>切换后</strong><p>数据库之间不会自动复制项目；需要时在新数据库中重新导入导出文件。</p></div>
    </section>
  </div>
</template>
