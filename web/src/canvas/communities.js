// 社区发现（louvain）：按"关系密度"把知识点自动分簇，作为**建议**给人看。
//
// 它和你手工分的组是两套东西：目录分组按"我把文件放哪"，社区按"实际上谁跟谁连得紧"。
// 两者不一致的地方，往往就是值得重新思考归属的地方。符合核心原则 5：Agent 只提议不写入——
// 这里只生成预览，确认后才走 PATCH 落盘，且可撤销。
import { louvain } from '@antv/algorithm'
import { PAD, ROW_MAX_W, TREE_GAP, ROW_GAP, looseGrid, packRows } from './layouts'
import { NODE_H, NODE_W } from './shapes'

const CELL = { w: NODE_W + 40, h: NODE_H + 28 }
const COLS_MAX = 5

/** 跑 louvain，返回按规模排序的社区，名字取社区里 pageRank 最高的节点。 */
export function detectCommunities(index) {
  const real = index.nodes.filter((n) => !n.virtual)
  const byId = new Map(real.map((n) => [n.id, n]))
  const data = {
    nodes: real.map((n) => ({ id: n.id })),
    edges: index.edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ source: e.source, target: e.target })),
  }
  const result = louvain(data, false)
  return result.clusters
    .map((c) => {
      const members = c.nodes.map((n) => n.id).filter((id) => byId.has(id))
      const sorted = [...members].sort((a, b) => (byId.get(b)?.weight || 0) - (byId.get(a)?.weight || 0))
      return { id: `c${c.id}`, name: byId.get(sorted[0])?.name || sorted[0] || `社区 ${c.id}`,
               members: sorted, size: members.length }
    })
    .filter((c) => c.size)
    .sort((a, b) => b.size - a.size)
}

function gridSize(count) {
  const cols = Math.max(1, Math.min(COLS_MAX, Math.ceil(Math.sqrt(count))))
  const rows = Math.ceil(count / cols)
  return { cols, rows, w: cols * CELL.w - 40 + 2 * PAD, h: rows * CELL.h - 28 + 44 + PAD }
}

/** 把社区排成一块块分组框：组内按权重从高到低填格子，组间按规模打包成行。 */
export function communityLayout(index, layout) {
  const communities = detectCommunities(index)
  const boxes = packRows(communities.map((c) => ({ ...c, ...gridSize(c.size) })), ROW_MAX_W)
  const groups = {}
  const nodes = {}
  let bottom = 0
  for (const box of boxes) {
    const gid = `g-社区-${box.name}`
    groups[gid] = { name: `${box.name}（${box.size}）`, x: box.x, y: box.y, w: box.w, h: box.h,
                    parent: null, collapsed: false, color: null }
    box.members.forEach((id, i) => {
      nodes[id] = { x: box.x + PAD + (i % box.cols) * CELL.w,
                    y: box.y + 44 + Math.floor(i / box.cols) * CELL.h, group: gid }
    })
    bottom = Math.max(bottom, box.y + box.h)
  }
  const strays = Object.keys(layout.nodes).filter((id) => !nodes[id])
  if (strays.length) {
    const grid = looseGrid(strays, bottom + ROW_GAP)
    const gid = 'g-社区-其他'
    groups[gid] = { name: `其他（${strays.length}）`, x: 0, y: bottom + ROW_GAP, w: grid.w, h: grid.h,
                    parent: null, collapsed: false, color: null }
    for (const n of grid.nodes) nodes[n.id] = { x: n.x, y: n.y, group: gid }
  }
  return { groups, nodes, communities, stats: { trees: boxes.length, strays: strays.length } }
}

/** 社区建议与当前分组的差异：哪些节点"住错了地方"。 */
export function compareWithGroups(communities, layout) {
  const groupOf = (id) => layout.nodes[id]?.group || null
  const moves = []
  for (const c of communities) {
    const counts = new Map()
    for (const id of c.members) {
      const g = groupOf(id)
      counts.set(g, (counts.get(g) || 0) + 1)
    }
    const main = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null
    for (const id of c.members) {
      if (groupOf(id) !== main) moves.push({ id, from: groupOf(id), to: c.name })
    }
  }
  return moves
}
