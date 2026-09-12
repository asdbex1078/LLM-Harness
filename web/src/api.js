// 与本地服务的三个接口对话。index 只读，layout 读写，Markdown 永不从这里改。

async function request(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    const err = new Error(`${options?.method || 'GET'} ${url} → ${res.status}`)
    err.status = res.status
    try { err.body = await res.json() } catch { err.body = null }
    throw err
  }
  return res.json()
}

export const fetchIndex = () => request('/api/index')
export const fetchLayout = () => request('/api/layout')
export const fetchHealth = () => request('/api/health')

export const fetchNode = (id) => request(`/api/node/${encodeURIComponent(id)}`)

/** Markdown 写回：dry_run=true 只预览，false 才落盘（服务端写前自动备份）。 */
export const postChanges = (body) => request('/api/changes', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const patchLayout = (body) => request('/api/layout', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
