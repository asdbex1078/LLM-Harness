// 撤销 / 重做：所有布局写入都经过 PATCH，所以"撤销"就是再发一个把状态改回去的 PATCH。
//
// 实现上用整份 layout 快照做栈，而不是维护逆操作：72 节点的 layout 约 12 KB，
// 30 步也就几百 KB，换来的是"任何操作都能原样退回"——包括整体换布局这种大改动。
const LIMIT = 30

export const clone = (doc) => JSON.parse(JSON.stringify(doc))

const ENTRY_KEYS = ['groups', 'nodes', 'edges']
const LIST_KEYS = ['refs', 'notes', 'images']
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)

/** 生成把 from 变成 to 的 merge patch：条目值为 null 表示删除该条目。 */
export function diffPatch(from, to) {
  const patch = {}
  for (const key of ENTRY_KEYS) {
    const a = from[key] || {}
    const b = to[key] || {}
    const delta = {}
    for (const id of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(id in b)) delta[id] = null
      else if (!same(a[id], b[id])) delta[id] = b[id]
    }
    if (Object.keys(delta).length) patch[key] = delta
  }
  for (const key of LIST_KEYS) {
    if (!same(from[key] || [], to[key] || [])) patch[key] = to[key] || []
  }
  if (!same(from.viewport, to.viewport)) patch.viewport = to.viewport
  return patch
}

export const isEmptyPatch = (patch) => Object.keys(patch).length === 0

export function createHistory() {
  const undoStack = []
  const redoStack = []
  return {
    /** 记一步：before / after 都是整份 layout 快照。 */
    record(before, after, label = '') {
      if (same(before, after)) return false
      undoStack.push({ before, after, label })
      if (undoStack.length > LIMIT) undoStack.shift()
      redoStack.length = 0
      return true
    },
    /** 取出上一步，返回要恢复到的快照。 */
    takeUndo() {
      const step = undoStack.pop()
      if (!step) return null
      redoStack.push(step)
      return step.before
    },
    takeRedo() {
      const step = redoStack.pop()
      if (!step) return null
      undoStack.push(step)
      return step.after
    },
    depth: () => [undoStack.length, redoStack.length],
    lastLabel: () => undoStack[undoStack.length - 1]?.label || '',
  }
}
