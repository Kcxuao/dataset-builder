export async function api(path, options = {}) {
  const response = await fetch(path, options)
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch { /* 保留状态码提示 */ }
    throw new Error(detail)
  }
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  return type.includes('application/json') ? response.json() : response
}

export function jsonOptions(method, data) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }
}

export function notifyError(error, ElMessage) {
  ElMessage.error(error?.message || '操作失败，请稍后重试')
}
