const $ = (id) => document.getElementById(id);
const state = { projects: [], projectId: null, samples: [], sampleId: null, offset: 0, limit: 20 };

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
  state.projectId = null; state.sampleId = null; $('project-title').textContent = '创建你的第一个数据集';
  $('project-subtitle').textContent = '导入文档，生成可审核的训练样本。';
  $('import-panel').classList.remove('hidden'); $('review-panel').classList.add('hidden'); $('export-panel').classList.add('hidden'); $('retry-button').classList.add('hidden');
  for (const button of document.querySelectorAll('.project-item')) button.classList.remove('active');
}
async function selectProject(id, refreshProjects = true) {
  state.projectId = id; state.sampleId = null; state.offset = 0;
  const project = state.projects.find((item) => item.id === id); if (!project) return;
  $('project-title').textContent = project.name;
  $('project-subtitle').textContent = `构建状态：${project.run_status || '未知'} · ${project.sample_count} 条样本`;
  $('import-panel').classList.add('hidden'); $('review-panel').classList.remove('hidden'); $('export-panel').classList.remove('hidden');
  $('retry-button').classList.toggle('hidden', !project.failed_chunks);
  if (refreshProjects) for (const button of document.querySelectorAll('.project-item')) button.classList.toggle('active', button.dataset.projectId === id);
  await loadSamples();
}
async function loadSamples(selectId = null) {
  if (!state.projectId) return;
  state.samples = await api(`/api/projects/${state.projectId}/samples?limit=${state.limit}&offset=${state.offset}`);
  $('sample-count').textContent = `${state.samples.length} 条 / 当前页`;
  $('page-label').textContent = String(Math.floor(state.offset / state.limit) + 1);
  $('prev-page').disabled = state.offset === 0; $('next-page').disabled = state.samples.length < state.limit;
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
$('import-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const button = event.target.querySelector('button[type=submit]'); button.disabled = true; button.textContent = '正在构建…'; notice('文件已上传，正在解析和生成样本；请保持页面打开。');
  try { const result = await api('/api/projects/build', { method: 'POST', body: new FormData(event.target) }); notice(`构建完成：${result.samples} 条样本，${result.failed_chunks} 个 Chunk 失败。`); await loadProjects(result.project_id); }
  finally { button.disabled = false; button.textContent = '开始构建 ↗'; }
}); });
$('retry-button').addEventListener('click', () => run(async () => { notice('正在重试失败 Chunk…'); const result = await api(`/api/projects/${state.projectId}/retry`, { method: 'POST' }); notice(`重试完成：新增 ${result.samples} 条样本，仍有 ${result.failed_chunks} 个 Chunk 失败。`); await loadProjects(state.projectId); }));
$('prev-page').addEventListener('click', () => run(async () => { state.offset = Math.max(0, state.offset - state.limit); await loadSamples(); }));
$('next-page').addEventListener('click', () => run(async () => { state.offset += state.limit; await loadSamples(); }));
$('export-form').addEventListener('submit', (event) => { event.preventDefault(); run(async () => {
  const values = Object.fromEntries(new FormData(event.target));
  const result = await api(`/api/projects/${state.projectId}/exports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
  const link = $('download-link'); link.href = result.download_url; link.classList.remove('hidden'); notice(`已导出 ${result.sample_count} 条样本。`);
}); });
run(() => loadProjects());
