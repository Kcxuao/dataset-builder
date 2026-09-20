const $ = (id) => document.getElementById(id);
const state = { projects: [], models: [], prompts: [], projectId: null, runId: null, pollTimer: null, lastRunStatus: null, samples: [], sampleId: null, offset: 0, limit: 20, modelEditId: null, promptEditId: null };
const panels = ['import-panel', 'review-panel', 'export-panel', 'models-panel', 'prompts-panel', 'processing-panel', 'trash-panel'];
function showPanels(...ids) { for (const id of panels) $(id).classList.toggle('hidden', !ids.includes(id)); $('stage-rail').classList.toggle('hidden', !ids.includes('import-panel') && !ids.includes('review-panel')); }
function showSettings(panel, title) { clearTimeout(state.pollTimer); state.runId = null; state.projectId = null; showPanels(panel); $('progress-panel').classList.add('hidden'); $('retry-button').classList.add('hidden'); $('delete-project').classList.add('hidden'); $('project-title').textContent = title; $('project-subtitle').textContent = '在这里管理工作区配置。'; }
const stageNames = { created: '任务已创建', importing: '正在导入', parsing: '正在解析', splitting: '正在切分', generating: '正在生成样本', cleaning: '正在清洗', validating: '正在校验', ready_for_review: '等待人工审核', completed: '处理完成', failed: '处理失败', interrupted: '任务已中断' };
const activeStatuses = new Set(['created', 'importing', 'parsing', 'splitting', 'generating', 'cleaning', 'validating']);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch {}
    throw new Error(detail);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
}
function notice(message, error = false) {
  const node = $('notice'); node.textContent = message; node.classList.remove('hidden'); node.classList.toggle('error', error);
}
function run(action) { Promise.resolve().then(action).catch((error) => notice(error.message, true)); }
function node(tag, className, content) {
  const element = document.createElement(tag); if (className) element.className = className;
  if (content !== undefined) element.textContent = content; return element;
}
function excerpt(sample) {
  return (sample.messages.find((message) => message.role === 'user')?.content || sample.messages[0]?.content || '空消息').slice(0, 90);
}
function statusText(sample) {
  if (sample.is_deleted) return '已删除';
  if (sample.validation_status !== 'passed') return '校验失败';
  return { pending: '待审核', approved: '已通过', rejected: '已拒绝' }[sample.review_status] || sample.review_status;
}
async function loadProjects(preferredId = state.projectId) {
  state.projects = await api('/api/projects'); $('project-count').textContent = state.projects.length;
  const list = $('projects'); list.replaceChildren();
  for (const project of state.projects) {
    const button = node('button', `project-item${project.id === preferredId ? ' active' : ''}`);
    button.type = 'button'; button.dataset.projectId = project.id;
    button.append(node('strong', '', project.name), node('small', '', `${project.sample_count} 条样本 · ${project.run_status || '未开始'}`));
    button.addEventListener('click', () => run(() => selectProject(project.id))); list.append(button);
  }
  if (preferredId && state.projects.some((project) => project.id === preferredId)) await selectProject(preferredId, false);
  else if (state.projects.length) await selectProject(state.projects[0].id, false);
  else showImport();
}
function showImport() {
  clearTimeout(state.pollTimer); state.runId = null;
  state.projectId = null; state.sampleId = null; $('project-title').textContent = '创建你的第一个数据集';
  $('project-subtitle').textContent = '导入文档，生成可审核的训练样本。';
  showPanels('import-panel'); $('retry-button').classList.add('hidden'); $('delete-project').classList.add('hidden'); $('progress-panel').classList.add('hidden');
  for (const button of document.querySelectorAll('.project-item')) button.classList.remove('active');
}
async function selectProject(id, refreshProjects = true) {
  state.projectId = id; state.sampleId = null; state.offset = 0;
  const project = state.projects.find((item) => item.id === id); if (!project) return;
  $('project-title').textContent = project.name;
  $('project-subtitle').textContent = `构建状态：${project.run_status || '未知'} · ${project.sample_count} 条样本`;
  showPanels('review-panel', 'export-panel'); $('delete-project').classList.remove('hidden');
  $('retry-button').classList.toggle('hidden', !project.failed_chunks);
  if (refreshProjects) for (const button of document.querySelectorAll('.project-item')) button.classList.toggle('active', button.dataset.projectId === id);
  await loadSamples();
  watchRun(project.run_id);
}
function watchRun(runId) {
  clearTimeout(state.pollTimer); state.runId = runId; state.lastRunStatus = null;
  $('progress-panel').classList.toggle('hidden', !runId);
  if (runId) run(() => refreshRun(runId));
}
async function refreshRun(runId) {
  const progress = await api(`/api/runs/${runId}`);
  if (state.runId !== runId) return;
  const processed = progress.completed_items + progress.failed_items;
  const total = progress.total_items;
  const finished = !activeStatuses.has(progress.status);
  const percentage = total ? Math.round(processed / total * 100) : (finished ? 100 : 0);
  $('progress-stage').textContent = stageNames[progress.status] || '处理中';
  $('progress-count').textContent = total ? `${processed} / ${total}` : '等待切分结果';
  $('progress-fill').style.width = `${Math.min(100, percentage)}%`;
  $('progress-detail').textContent = `已成功 ${progress.completed_items} 个内容块，失败 ${progress.failed_items} 个，生成 ${progress.sample_count} 条样本。${progress.status === 'generating' ? `完成 ${percentage}%` : ''}`;
  if (progress.status === 'interrupted') $('progress-detail').textContent = total ? '服务曾中断此任务，可以重试剩余内容块。' : '任务在切分完成前中断，请重新上传源文件。';
  $('retry-button').classList.toggle('hidden', !(progress.failed_items > 0 || (progress.status === 'interrupted' && total > 0)));
  const errors = $('progress-errors'); errors.replaceChildren();
  if (progress.error_message) errors.append(node('div', 'progress-error', progress.error_message));
  for (const chunk of progress.failed_chunks) errors.append(node('div', 'progress-error', `内容块 ${chunk.id.slice(0, 8)}：${chunk.error}`));
  if (finished && state.lastRunStatus && activeStatuses.has(state.lastRunStatus)) {
    notice(progress.status === 'failed' ? '构建失败，请查看任务错误详情。' : '构建结束，样本已进入审核队列。', progress.status === 'failed');
    await loadSamples();
  }
  state.lastRunStatus = progress.status;
  if (!finished) state.pollTimer = setTimeout(() => run(() => refreshRun(runId)), 1200);
}
async function loadSamples(selectId = null) {
  if (!state.projectId) return;
  state.samples = await api(`/api/projects/${state.projectId}/samples?limit=${state.limit}&offset=${state.offset}`);
  $('sample-count').textContent = `${state.samples.length} 条 / 当前页`;
  $('page-label').textContent = String(Math.floor(state.offset / state.limit) + 1);
  $('prev-page').disabled = state.offset === 0; $('next-page').disabled = state.samples.length < state.limit;
  for (const button of $('bulk-actions').querySelectorAll('button')) button.disabled = !state.samples.length;
  const list = $('samples'); list.replaceChildren();
  if (!state.samples.length) list.append(node('p', 'empty-detail', '当前页没有样本。'));
  for (const sample of state.samples) {
    const button = node('button', `sample-item${sample.id === selectId ? ' active' : ''}`); button.type = 'button';
    const top = node('div', 'sample-item-top'); top.append(node('strong', '', excerpt(sample)), node('span', `status-pill ${sample.review_status}`, statusText(sample)));
    button.append(top, node('small', '', `#${sample.id.slice(0, 8)} · ${sample.messages.length} 条消息`));
    button.addEventListener('click', () => renderDetail(sample.id)); list.append(button);
  }
  if (selectId && state.samples.some((sample) => sample.id === selectId)) renderDetail(selectId);
  else { state.sampleId = null; $('detail-title').textContent = '选择样本'; $('detail-status').textContent = ''; $('detail-body').replaceChildren(node('div', 'empty-detail', '选择左侧样本查看消息、来源与校验结果。')); }
}
async function loadModels(selectedId = '') {
  const models = await api('/api/models'); state.models = models; const select = $('model-select');
  select.replaceChildren(); const fallback = node('option', '', '工作区默认模型'); fallback.value = ''; select.append(fallback);
  for (const model of models) { const option = node('option', '', `${model.name} · ${model.model}`); option.value = model.id; select.append(option); }
  select.value = selectedId;
  const defaults = $('default-model-select'); const current = defaults.value; defaults.replaceChildren();
  const env = node('option', '', '环境配置模型'); env.value = ''; defaults.append(env);
  for (const model of models) { const option = node('option', '', `${model.name} · ${model.model}`); option.value = model.id; defaults.append(option); }
  defaults.value = current;
  renderModelList();
}
function renderPresets() {
  const mode = $('generator-select').value; const select = $('prompt-preset'); select.replaceChildren();
  for (const preset of state.prompts.filter((item) => item.mode === mode)) { const option = node('option', '', preset.name); option.value = preset.id; select.append(option); }
  updatePromptPreview();
}
function updatePromptPreview() {
  const preset = state.prompts.find((item) => item.id === $('prompt-preset').value);
  $('prompt-preview').textContent = preset?.instruction || '';
}
function configRow(title, description) { const row = node('div', 'config-row'); const info = node('div'); info.append(node('strong', '', title), node('small', '', description)); row.append(info); return row; }
function renderModelList() {
  const list = $('model-list'); list.replaceChildren();
  for (const model of state.models) {
    const row = configRow(model.name, `${model.model} · ${model.base_url} · 并发 ${model.concurrency_limit}`);
    const setDefault = node('button', 'plain-button', '设为默认'); setDefault.type = 'button';
    setDefault.addEventListener('click', () => run(async () => {
      const current = await api('/api/workspace/settings');
      await api('/api/workspace/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parser_workers: current.parser_workers, default_model_id: model.id }) });
      await loadProcessing(); notice(`已将“${model.name}”设为默认模型。`);
    }));
    const edit = node('button', 'plain-button', '编辑'); edit.type = 'button'; edit.addEventListener('click', () => {
      state.modelEditId = model.id; const form = $('model-form');
      for (const key of ['name', 'base_url', 'model', 'temperature', 'max_tokens', 'timeout', 'concurrency_limit', 'max_retries']) form.elements[key].value = model[key];
      form.elements.thinking.value = model.thinking === null ? '' : String(model.thinking);
      form.elements.json_mode.checked = model.json_mode; form.elements.api_key.value = '';
      $('model-form-title').textContent = `编辑 ${model.name}`; $('cancel-model-edit').classList.remove('hidden');
      form.scrollIntoView({ behavior: 'smooth' });
    });
    const del = node('button', 'danger-button', '归档'); del.type = 'button'; del.addEventListener('click', () => run(async () => {
      if (!confirm(`归档模型“${model.name}”？历史任务仍可重试。`)) return;
      await api(`/api/models/${model.id}`, { method: 'DELETE' }); await loadModels(); notice('模型已归档。');
    })); row.append(setDefault, edit, del); list.append(row);
  }
}
async function loadPrompts() { state.prompts = await api('/api/prompts'); renderPresets(); renderPromptList(); }
function renderPromptList() {
  const list = $('prompt-list'); list.replaceChildren();
  for (const prompt of state.prompts) {
    const row = configRow(prompt.name, `${prompt.mode === 'qa' ? '问答' : '指令'} · ${prompt.instruction}`);
    if (!prompt.builtin) {
      const edit = node('button', 'plain-button', '编辑'); edit.type = 'button'; edit.addEventListener('click', () => {
        state.promptEditId = prompt.id; const form = $('prompt-form');
        form.elements.name.value = prompt.name; form.elements.mode.value = prompt.mode;
        form.elements.instruction.value = prompt.instruction;
        $('prompt-form-title').textContent = `编辑 ${prompt.name}`; $('cancel-prompt-edit').classList.remove('hidden');
        form.scrollIntoView({ behavior: 'smooth' });
      });
      const del = node('button', 'danger-button', '删除'); del.type = 'button'; del.addEventListener('click', () => run(async () => {
        if (!confirm(`删除提示词“${prompt.name}”？`)) return;
        await api(`/api/prompts/${prompt.id}`, { method: 'DELETE' }); await loadPrompts(); notice('提示词已删除。');
      })); row.append(edit, del);
    }
    list.append(row);
  }
}
async function loadProcessing() { const settings = await api('/api/workspace/settings'); $('processing-form').elements.parser_workers.value = settings.parser_workers; $('default-model-select').value = settings.default_model_id || ''; }
async function loadTrash() {
  const projects = await api('/api/projects?trash=true'); const list = $('trash-list'); list.replaceChildren();
  if (!projects.length) list.append(node('p', 'empty-detail', '回收站为空。'));
  for (const project of projects) {
    const row = configRow(project.name, `${project.sample_count} 条样本`);
    const restore = node('button', 'plain-button', '恢复'); restore.type = 'button'; restore.addEventListener('click', () => run(async () => {
      await api(`/api/projects/${project.id}/restore`, { method: 'POST' }); await loadTrash(); await loadProjects(project.id); notice('数据集已恢复。');
    })); row.append(restore); list.append(row);
  }
}
function messageRow(message = { role: 'user', content: '' }) {
  const row = node('div', 'message-row'); const head = node('div', 'message-row-head');
  const select = node('select'); select.setAttribute('aria-label', '消息角色');
  for (const role of ['system', 'user', 'assistant']) { const option = node('option', '', role); option.value = role; select.append(option); } select.value = message.role;
  const remove = node('button', 'danger-button', '移除'); remove.type = 'button'; remove.addEventListener('click', () => row.remove());
  head.append(select, remove); const textarea = node('textarea'); textarea.value = message.content; textarea.setAttribute('aria-label', '消息内容');
  row.append(head, textarea); return row;
}
function detailSection(title) { const section = node('section', 'detail-section'); section.append(node('h3', '', title)); return section; }
async function renderDetail(id) {
  state.sampleId = id; const sample = await api(`/api/samples/${id}`);
  for (const button of document.querySelectorAll('.sample-item')) button.classList.toggle('active', button.querySelector('small')?.textContent.includes(id.slice(0, 8)));
  $('detail-title').textContent = `样本 #${id.slice(0, 8)}`;
  $('detail-status').textContent = statusText(sample); $('detail-status').className = `status-pill ${sample.validation_status === 'failed' ? 'failed' : sample.review_status}`;
  const body = $('detail-body'); body.replaceChildren();
  const messages = detailSection('消息内容'); const editor = node('div', 'message-editor');
  for (const message of sample.messages) editor.append(messageRow(message));
  const add = node('button', 'plain-button', '＋ 添加消息'); add.type = 'button'; add.addEventListener('click', () => editor.append(messageRow()));
  const save = node('button', 'primary-button', '保存修改'); save.type = 'button'; save.addEventListener('click', () => run(async () => {
    const values = [...editor.children].map((row) => ({ role: row.querySelector('select').value, content: row.querySelector('textarea').value }));
    await api(`/api/samples/${id}/messages`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: values }) });
    notice('修改已保存，审核状态已重置为待审核。'); await loadSamples(id);
  })); messages.append(editor, add, node('span', '', ' '), save); body.append(messages);
  const source = detailSection('来源 Chunk'); source.append(node('div', 'source-content', sample.chunk_content || '无来源内容')); body.append(source);
  const issues = detailSection('校验结果');
  if (!sample.issues.length) issues.append(node('p', '', '✓ 结构与内容校验通过'));
  else for (const issue of sample.issues) issues.append(node('div', 'issue', `${issue.rule}: ${issue.message}`)); body.append(issues);
  const actions = detailSection('审核操作'); const buttons = node('div', 'actions');
  for (const [label, status] of [['通过', 'approved'], ['拒绝', 'rejected'], ['待审核', 'pending']]) {
    const button = node('button', status === 'approved' ? 'primary-button' : 'plain-button', label); button.type = 'button';
    button.addEventListener('click', () => run(async () => { await api(`/api/samples/${id}/review`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); notice('审核状态已更新。'); await loadSamples(id); })); buttons.append(button);
  }
  const del = node('button', 'danger-button', sample.is_deleted ? '恢复样本' : '软删除'); del.type = 'button';
  del.addEventListener('click', () => run(async () => { await api(`/api/samples/${id}/deleted`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_deleted: !sample.is_deleted }) }); notice('样本状态已更新。'); await loadSamples(id); })); buttons.append(del); actions.append(buttons); body.append(actions);
}
$('new-project').addEventListener('click', showImport);
$('nav-models').addEventListener('click', () => { showSettings('models-panel', '模型配置'); run(() => loadModels()); });
$('nav-prompts').addEventListener('click', () => { showSettings('prompts-panel', '提示词配置'); run(() => loadPrompts()); });
$('nav-processing').addEventListener('click', () => { showSettings('processing-panel', '处理设置'); run(() => loadProcessing()); });
$('nav-trash').addEventListener('click', () => { showSettings('trash-panel', '回收站'); run(() => loadTrash()); });
$('delete-project').addEventListener('click', () => run(async () => {
  const project = state.projects.find((item) => item.id === state.projectId); if (!project) return;
  if (!confirm(`将数据集“${project.name}”移入回收站？`)) return;
  await api(`/api/projects/${project.id}`, { method: 'DELETE' }); await loadProjects(); notice('数据集已移入回收站。');
}));
$('generator-select').addEventListener('change', renderPresets);
$('prompt-preset').addEventListener('change', updatePromptPreview);
$('cancel-model-edit').addEventListener('click', () => { state.modelEditId = null; $('model-form').reset(); $('model-form-title').textContent = '新增模型'; $('cancel-model-edit').classList.add('hidden'); });
$('cancel-prompt-edit').addEventListener('click', () => { state.promptEditId = null; $('prompt-form').reset(); $('prompt-form-title').textContent = '新增提示词'; $('cancel-prompt-edit').classList.add('hidden'); });
$('model-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const form = event.target; const values = Object.fromEntries(new FormData(form));
  values.temperature = Number(values.temperature); values.max_tokens = Number(values.max_tokens);
  values.timeout = Number(values.timeout); values.concurrency_limit = Number(values.concurrency_limit);
  values.max_retries = Number(values.max_retries); values.json_mode = values.json_mode === 'on';
  values.thinking = values.thinking === '' ? null : values.thinking === 'true';
  if (!values.api_key) values.api_key = null;
  const editing = state.modelEditId;
  const model = await api(editing ? `/api/models/${editing}` : '/api/models', {
    method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
  });
  $('cancel-model-edit').click(); await loadModels(model.id); notice('模型配置已保存。');
}); });
$('prompt-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const form = event.target; const values = Object.fromEntries(new FormData(form)); const editing = state.promptEditId;
  await api(editing ? `/api/prompts/${editing}` : '/api/prompts', {
    method: editing ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
  });
  $('cancel-prompt-edit').click(); await loadPrompts(); notice('提示词已保存。');
}); });
$('processing-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const values = Object.fromEntries(new FormData(event.target)); values.parser_workers = Number(values.parser_workers);
  values.default_model_id = values.default_model_id || null;
  await api('/api/workspace/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
  notice('处理设置已保存。');
}); });
$('bulk-actions').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]'); if (!button || !state.samples.length) return;
  run(async () => {
    const ids = state.samples.map((sample) => sample.id);
    const result = await api(`/api/projects/${state.projectId}/samples/bulk`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample_ids: ids, action: button.dataset.action }),
    });
    notice(`已更新 ${result.updated_ids.length} 条，跳过 ${result.skipped.length} 条。${result.skipped[0] ? `原因：${result.skipped[0].reason}` : ''}`);
    await loadSamples(state.sampleId);
  });
});
$('import-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const button = event.target.querySelector('button[type=submit]'); button.disabled = true; button.textContent = '正在上传…'; notice('正在上传文件并创建构建任务…');
  try { const result = await api('/api/projects/build', { method: 'POST', body: new FormData(event.target) }); notice('构建任务已创建，进度会自动更新。'); await loadProjects(result.project_id); }
  finally { button.disabled = false; button.textContent = '开始构建 ↗'; }
}); });
$('retry-button').addEventListener('click', () => run(async () => { const result = await api(`/api/projects/${state.projectId}/retry`, { method: 'POST' }); notice('失败内容块已开始重试，进度会自动更新。'); watchRun(result.run_id); }));
$('prev-page').addEventListener('click', () => run(async () => { state.offset = Math.max(0, state.offset - state.limit); await loadSamples(); }));
$('next-page').addEventListener('click', () => run(async () => { state.offset += state.limit; await loadSamples(); }));
$('export-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const values = Object.fromEntries(new FormData(event.target));
  const result = await api(`/api/projects/${state.projectId}/exports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
  const link = $('download-link'); link.href = result.download_url; link.classList.remove('hidden'); notice(`已导出 ${result.sample_count} 条样本。`);
}); });
run(async () => { await loadModels(); await loadPrompts(); await loadProcessing(); await loadProjects(); });
