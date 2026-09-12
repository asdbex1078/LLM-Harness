// layout 写入队列：拖拽过程中不写盘，松手后 300ms 节流合并，一次 PATCH 发完。
// revision 冲突（409）时重新拉取服务端 layout，再用最新 revision 重放本地待写项。
import { fetchLayout, patchLayout } from '../api'

const DELAY = 300
const VIEWPORT_DELAY = 1000

export function createPatcher({ getRevision, setRevision, onStatus, onConflict }) {
  let pending = { nodes: {}, groups: {}, viewport: null, lists: {} }
  let timer = null
  let inflight = false

  const empty = (p) => !p.viewport && !Object.keys(p.nodes).length && !Object.keys(p.groups).length
    && !Object.keys(p.lists || {}).length

  function schedule(delay) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(flush, delay)
  }

  function queueNode(id, patch) {
    pending.nodes[id] = { ...(pending.nodes[id] || {}), ...patch }
    onStatus?.('dirty')
    schedule(DELAY)
  }

  function queueGroup(id, patch) {
    pending.groups[id] = { ...(pending.groups[id] || {}), ...patch }
    onStatus?.('dirty')
    schedule(DELAY)
  }

  /** refs / notes / images 是带 id 的小集合，服务端按整表替换。 */
  function queueList(name, items) {
    pending.lists = { ...pending.lists, [name]: items }
    onStatus?.('dirty')
    schedule(DELAY)
  }

  function queueViewport(viewport) {
    pending.viewport = viewport
    schedule(VIEWPORT_DELAY)
  }

  function mergeBack(snapshot) {
    pending = {
      nodes: { ...snapshot.nodes, ...pending.nodes },
      groups: { ...snapshot.groups, ...pending.groups },
      viewport: pending.viewport || snapshot.viewport,
      lists: { ...snapshot.lists, ...pending.lists },
    }
  }

  async function flush() {
    if (inflight || empty(pending)) return
    inflight = true
    const snapshot = pending
    pending = { nodes: {}, groups: {}, viewport: null, lists: {} }
    const body = { base_revision: getRevision() }
    Object.assign(body, snapshot.lists || {})
    if (Object.keys(snapshot.nodes).length) body.nodes = snapshot.nodes
    if (Object.keys(snapshot.groups).length) body.groups = snapshot.groups
    if (snapshot.viewport) body.viewport = snapshot.viewport
    onStatus?.('saving')
    try {
      const saved = await patchLayout(body)
      setRevision(saved.revision)
      onStatus?.(empty(pending) ? 'saved' : 'dirty', saved)
    } catch (err) {
      mergeBack(snapshot)
      if (err.status === 409) {
        const fresh = await fetchLayout()
        setRevision(fresh.layout.revision)
        onConflict?.(fresh)
        onStatus?.('retry')
        inflight = false
        schedule(50) // 用新 revision 重放本地改动
        return
      }
      onStatus?.('error', err)
    } finally {
      inflight = false
      if (!empty(pending) && !timer) schedule(DELAY)
    }
  }

  return { queueNode, queueGroup, queueViewport, queueList, flush, pendingCount: () => Object.keys(pending.nodes).length + Object.keys(pending.groups).length }
}
