<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Plus, Delete } from '@element-plus/icons-vue'
import { api, jsonOptions, notifyError } from '../api'

const prompts = ref([])
const mode = ref('qa')
const dialog = ref(false)
const editing = ref(null)
const saving = ref(false)
const form = reactive({ name: '', mode: 'qa', instruction: '' })
const visible = computed(() => prompts.value.filter(item => item.mode === mode.value))
async function load() { try { prompts.value = await api('/api/prompts') } catch (error) { notifyError(error, ElMessage) } }
function openForm(prompt = null) { editing.value = prompt?.id || null; Object.assign(form, prompt ? { name: prompt.name, mode: prompt.mode, instruction: prompt.instruction } : { name: '', mode: mode.value, instruction: '' }); dialog.value = true }
async function save() {
  saving.value = true
  try { await api(editing.value ? `/api/prompts/${editing.value}` : '/api/prompts', jsonOptions(editing.value ? 'PUT' : 'POST', form)); dialog.value = false; await load(); ElMessage.success('提示词已保存') }
  catch (error) { notifyError(error, ElMessage) }
  finally { saving.value = false }
}
async function remove(prompt) {
  try { await ElMessageBox.confirm(`删除提示词“${prompt.name}”？历史任务仍保留当时使用的内容。`, '删除提示词', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }); await api(`/api/prompts/${prompt.id}`, { method: 'DELETE' }); await load(); ElMessage.success('提示词已删除') }
  catch (error) { if (error !== 'cancel') notifyError(error, ElMessage) }
}
onMounted(load)
</script>

<template>
  <section class="section-card"><div class="section-heading"><div><h2>提示词模板</h2><span class="section-subtitle">选择内置预设，或保存自己的生成规则</span></div><el-button type="primary" :icon="Plus" @click="openForm()">新增模板</el-button></div>
    <el-segmented v-model="mode" :options="[{ label: '问答生成', value: 'qa' }, { label: '指令生成', value: 'instruction' }]" class="prompt-segment" />
    <div class="prompt-grid"><div v-for="prompt in visible" :key="prompt.id" class="prompt-card"><div class="prompt-card-top"><span class="prompt-mark">“</span><el-tag :type="prompt.builtin ? 'info' : 'primary'" effect="light" round>{{ prompt.builtin ? '内置预设' : '自定义' }}</el-tag></div><h3>{{ prompt.name }}</h3><p>{{ prompt.instruction }}</p><div v-if="!prompt.builtin" class="prompt-actions"><el-button text :icon="EditPen" @click="openForm(prompt)">编辑</el-button><el-button text type="danger" :icon="Delete" @click="remove(prompt)">删除</el-button></div></div></div>
  </section>
  <el-dialog v-model="dialog" :title="editing ? '编辑提示词' : '新增提示词'" width="min(620px, 94vw)" destroy-on-close><el-form label-position="top"><el-form-item label="模板名称" required><el-input v-model="form.name" /></el-form-item><el-form-item label="生成方式"><el-select v-model="form.mode"><el-option label="问答生成" value="qa" /><el-option label="指令生成" value="instruction" /></el-select></el-form-item><el-form-item label="提示词内容" required><el-input v-model="form.instruction" type="textarea" :rows="7" /></el-form-item><p class="field-hint">系统会自动附加结构化输出格式要求。</p></el-form><template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存模板</el-button></template></el-dialog>
</template>
