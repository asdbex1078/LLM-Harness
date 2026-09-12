// 布局算法：把 index 里的关系结构算成坐标，结果写回 layout.json 当"初始种子"，
// 之后位置仍归人工定稿（核心原则 2：布局是数据，不是算法输出）。
//
// 多中心脑图：知识图谱不是一棵树——实测 72 节点里有 11 个根、26 个节点有多个父、
// 55% 的边不是树边。所以不强行做成一棵树，而是每个根各生成一棵脑图并排摆，
// 非树边交给画布的跨组聚合去表达。这正是"多主题板"的做法。
import Hierarchy from '@antv/hierarchy'
import { NODE_H, NODE_W } from './shapes'

const STRUCT_FAMILY = '结构'
const V_GAP = 18
const H_GAP = 64
export const TREE_GAP = 140   // 两棵脑图之间的间距
export const ROW_GAP = 180
export const ROW_MAX_W = 4200
export const PAD = 40     // 分组框内边距

/** 从结构族的边推导父子关系：source 包含/部件/实例 target，即 source 是父。 */
export function buildForest(index) {
  const nodes = index.nodes.filter((n) => !n.virtual)
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const children = new Map()
  const parents = new Map()
  for (const e of index.edges) {
    if (e.family !== STRUCT_FAMILY || !byId.has(e.source) || !byId.has(e.target)) continue
    if (!children.has(e.source)) children.set(e.source, [])
    children.get(e.source).push(e.target)
    if (!parents.has(e.target)) parents.set(e.target, [])
    parents.get(e.target).push(e.source)
  }
  // 多父节点只认一个父（度数最高者，其余关系留给跨组聚合边表达），避免树里出现重复节点
  const mainParent = new Map()
  for (const [child, ps] of parents) {
    const pick = [...ps].sort((a, b) => (byId.get(b)?.degree || 0) - (byId.get(a)?.degree || 0) || a.localeCompare(b))[0]
    mainParent.set(child, pick)
  }
  const roots = nodes.filter((n) => children.has(n.id) && !mainParent.has(n.id)).map((n) => n.id)
  const placed = new Set()
  const toTree = (id) => {
    if (placed.has(id)) return null            // 环 / 多父：只进一次树
    placed.add(id)
    const kids = (children.get(id) || [])
      .filter((c) => mainParent.get(c) === id)
      .sort()
      .map(toTree)
      .filter(Boolean)
    return { id, name: byId.get(id)?.name || id, children: kids }
  }
  const trees = roots.sort().map(toTree).filter(Boolean)
  const loose = nodes.filter((n) => !placed.has(n.id)).map((n) => n.id)
  return { trees, loose, byId }
}

function runMindmap(tree) {
  const out = Hierarchy.mindmap(tree, {
    direction: 'H',
    getId: (d) => d.id,
    getHeight: () => NODE_H + 6,
    getWidth: () => NODE_W + 8,
    getVGap: () => V_GAP,
    getHGap: () => H_GAP,
  })
  const points = []
  out.eachNode((n) => points.push({ id: n.id ?? n.data?.id, x: n.x, y: n.y }))
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  return {
    points,
    minX: Math.min(...xs), minY: Math.min(...ys),
    w: Math.max(...xs) - Math.min(...xs) + NODE_W,
    h: Math.max(...ys) - Math.min(...ys) + NODE_H,
  }
}

export function packRows(items, maxWidth) {
  /** 把若干个盒子按行摆放，超过行宽换行。返回每个盒子的左上角。 */
  const out = []
  let x = 0
  let y = 0
  let rowH = 0
  for (const item of items) {
    if (x > 0 && x + item.w > maxWidth) {
      x = 0
      y += rowH + ROW_GAP
      rowH = 0
    }
    out.push({ ...item, x, y })
    x += item.w + TREE_GAP
    rowH = Math.max(rowH, item.h)
  }
  return out
}

export function looseGrid(ids, originY) {
  const cols = Math.max(1, Math.min(8, Math.ceil(Math.sqrt(ids.length))))
  const cell = { w: NODE_W + 40, h: NODE_H + 30 }
  const nodes = ids.map((id, i) => ({
    id, x: PAD + (i % cols) * cell.w, y: originY + PAD + Math.floor(i / cols) * cell.h,
  }))
  return {
    nodes,
    w: cols * cell.w - 40 + 2 * PAD,
    h: Math.ceil(ids.length / cols) * cell.h - 30 + 2 * PAD,
  }
}

/**
 * 生成多中心脑图布局。返回可直接 PATCH 的 { groups, nodes }：
 * 每棵脑图一个分组框（框名 = 根节点名），落单节点单独一组。
 */
export function mindmapLayout(index, layout) {
  const { trees, loose, byId } = buildForest(index)
  const laid = trees.map((t) => ({ tree: t, ...runMindmap(t) }))
    .sort((a, b) => b.points.length - a.points.length)
  const placedBoxes = packRows(laid, ROW_MAX_W)

  const groups = {}
  const nodes = {}
  let bottom = 0
  for (const box of placedBoxes) {
    const gid = `g-脑图-${box.tree.id}`
    groups[gid] = {
      name: `${byId.get(box.tree.id)?.name || box.tree.id}（${box.points.length}）`,
      x: box.x, y: box.y, w: box.w + 2 * PAD, h: box.h + 2 * PAD,
      parent: null, collapsed: false, color: '#eef2f8',
    }
    for (const p of box.points) {
      nodes[p.id] = { x: box.x + PAD + (p.x - box.minX), y: box.y + PAD + (p.y - box.minY), group: gid }
    }
    bottom = Math.max(bottom, box.y + box.h + 2 * PAD)
  }

  // 不在任何层级里的节点（含 layout 里的孤立记录）单独一块，不丢
  const strays = [...new Set([...loose, ...Object.keys(layout.nodes).filter((id) => !nodes[id])])]
  if (strays.length) {
    const grid = looseGrid(strays, bottom + ROW_GAP)
    const gid = 'g-脑图-未归入层级'
    groups[gid] = { name: `未归入层级（${strays.length}）`, x: 0, y: bottom + ROW_GAP,
                    w: grid.w, h: grid.h, parent: null, collapsed: false, color: '#f6f7f9' }
    for (const n of grid.nodes) nodes[n.id] = { x: n.x, y: n.y, group: gid }
  }
  return { groups, nodes, stats: { trees: placedBoxes.length, strays: strays.length } }
}

/** 生成一个把旧分组全部删掉、换成新分组的 PATCH 主体。 */
export function toPatch(result, layout, baseRevision) {
  const groups = {}
  for (const gid of Object.keys(layout.groups)) groups[gid] = null   // 旧分组删除
  Object.assign(groups, result.groups)
  const nodes = {}
  for (const [id, pos] of Object.entries(result.nodes)) {
    nodes[id] = { x: Math.round(pos.x), y: Math.round(pos.y), group: pos.group }
  }
  return { base_revision: baseRevision, groups, nodes }
}
