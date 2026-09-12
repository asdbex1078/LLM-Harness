// LOD（细节层次）：缩小时把分组折叠成一张"簇卡片"，放大时展开细节。
//
// 设计文档 3.7 按 depth 定阈值（depth 0 永不折叠），但那假定了"顶层是一个大容器"。
// 实际布局可能是扁平的（多中心脑图就是 12 个平级分组），按 depth 判定会一个都折不了。
// 所以改成按"这个分组里还有没有子分组"判定：
//   叶子分组（里面全是节点）—— 缩到看不清字就折叠成簇卡片；
//   容器分组（里面还有子分组）—— 缩得更小才整体折叠成一张板块卡片。
// pinned 覆盖自动规则；可见元素超预算时，从最深的分组开始继续折叠。
export const BUDGET = 600
export const BUDGET_MAX = 1500
export const LEAF_ZOOM = 0.5        // 叶子分组的折叠阈值：13px 字号 × 0.5 ≈ 6.5px，已读不出来
export const CONTAINER_ZOOM = 0.28  // 容器分组：再缩一档才整体折叠

export function groupDepth(groups, id, seen = new Set()) {
  const g = groups[id]
  if (!g?.parent || seen.has(id)) return 0
  seen.add(id)
  return 1 + groupDepth(groups, g.parent, seen)
}

function ancestors(groups, id) {
  const out = []
  let cur = groups[id]?.parent
  const seen = new Set()
  while (cur && !seen.has(cur)) {
    out.push(cur)
    seen.add(cur)
    cur = groups[cur]?.parent
  }
  return out
}

/** 节点在当前折叠状态下"实际显示成谁"：最外层的那个被折叠的祖先分组，或它自己。 */
export function containerOf(layout, nodeId, collapsed) {
  const gid = layout.nodes[nodeId]?.group
  if (!gid) return nodeId
  const chain = [gid, ...ancestors(layout.groups, gid)]
  const outermost = chain.filter((g) => collapsed.has(g)).pop()
  return outermost || nodeId
}

/** 算出当前缩放下应该折叠哪些分组（只返回最外层的折叠分组）。 */
export function computeCollapsed(layout, zoom, { auto = true, focus = null } = {}) {
  const groups = layout.groups || {}
  // 聚焦模式：点开某个域时，只有它（及其祖先链）展开，其余一律保持簇卡片——
  // 否则放大会把所有域一起展开，等于没聚焦。
  if (focus && groups[focus]) {
    const keep = new Set([focus, ...ancestors(groups, focus)])
    const collapsed = new Set(Object.keys(groups).filter((gid) => !keep.has(gid)))
    return new Set([...collapsed].filter((gid) => !ancestors(groups, gid).some((p) => collapsed.has(p))))
  }
  const wanted = new Set()
  const isLeaf = (gid) => !Object.values(groups).some((x) => x.parent === gid)
  for (const [gid, g] of Object.entries(groups)) {
    const threshold = isLeaf(gid) ? LEAF_ZOOM : CONTAINER_ZOOM
    let collapse = auto && zoom < threshold
    if (g.pinned === 'expanded') collapse = false
    if (g.pinned === 'collapsed') collapse = true
    if (collapse) wanted.add(gid)
  }
  const outermost = new Set(
    [...wanted].filter((gid) => !ancestors(groups, gid).some((p) => wanted.has(p))),
  )
  return auto ? applyBudget(layout, outermost) : outermost
}

/** 超出可见元素预算时，从最深的未钉住分组开始继续折叠。 */
function applyBudget(layout, collapsed) {
  const groups = layout.groups || {}
  const count = () => {
    const hidden = new Set()
    for (const nid of Object.keys(layout.nodes)) {
      if (containerOf(layout, nid, collapsed) !== nid) hidden.add(nid)
    }
    return Object.keys(layout.nodes).length - hidden.size + collapsed.size
  }
  const candidates = () => Object.keys(groups)
    .filter((gid) => !collapsed.has(gid) && groups[gid].pinned !== 'expanded')
    .filter((gid) => !ancestors(groups, gid).some((p) => collapsed.has(p)))
    .sort((a, b) => groupDepth(groups, b) - groupDepth(groups, a))

  let guard = 0
  while (count() > BUDGET && guard++ < 200) {
    const next = candidates()[0]
    if (!next) break
    collapsed.add(next)
  }
  return collapsed
}

/** 簇卡片上展示什么：分组名、节点数、度数最高的几个节点。 */
export function clusterSummary(layout, index, gid, limit = 5) {
  const groups = layout.groups || {}
  const inside = Object.entries(layout.nodes)
    .filter(([, n]) => n.group === gid || ancestors(groups, n.group || '').includes(gid))
    .map(([id]) => id)
  const byId = new Map(index.nodes.map((n) => [n.id, n]))
  const top = inside
    .map((id) => byId.get(id))
    .filter(Boolean)
    .sort((a, b) => (b.degree || 0) - (a.degree || 0))
    .slice(0, limit)
    .map((n) => n.name || n.id)
  return { count: inside.length, top }
}
