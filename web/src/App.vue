<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from 'vue'
import { fetchHealth, fetchIndex, fetchLayout, fetchNode, patchLayout, postChanges } from './api'
import { clone, createHistory, diffPatch, isEmptyPatch } from './canvas/history'
import { createPatcher } from './canvas/patcher'
import { computeCollapsed } from './canvas/lod'
import {
  LABEL_ZOOM, applyEdgeLabels, applyViewport, buildCells, createGraph, currentViewport,
  highlightEdges, mount, movedPositions,
} from './canvas/render'
import { communityLayout, compareWithGroups } from './canvas/communities'
import { mindmapLayout, toPatch } from './canvas/layouts'
import { FAMILIES, FAMILY_STYLE, setTheme } from './canvas/shapes'

const canvasEl = ref(null)
const graph = shallowRef(null)
const patcher = shallowRef(null)
const indexDoc = shallowRef(null)
const layoutDoc = shallowRef(null)

const revision = ref(0)
const indexRevision = ref(0)
const status = ref('saved')
const banner = ref('')
const bannerKind = ref('')
const selected = ref(null)
const detail = shallowRef(null)          // GET /api/node/:id 的结果（md 原文 + 出入边）
const showRaw = ref(false)
const pending = ref([])                  // 待提交的 ChangeSet（本地攒着，未确认不碰 md）
const changePreview = shallowRef(null)   // 预览结果（每个文件的 diff）
const draft = reactive({ relation: '', target: '', year: '', note: '' })
const stats = reactive({ nodes: 0, edges: 0, stubs: 0 })
// 结构族默认不画线：嵌套（分组框）已经表达了归属，86 条结构边里有 74 条两端同框，
// 画出来纯属重复噪音（设计文档 3.6）。需要看的时候在工具条勾上。
const visible = reactive(Object.fromEntries(FAMILIES.map((f) => [f, f !== '结构'])))
const edgesShown = ref(0)
const aggShown = ref(0)
const has3d = ref(false)          // 服务端有 web3d 构建产物时才显示 3D 入口
const inboxCount = ref(0)
const autoLod = ref(true)                // 缩小自动折叠成簇卡片（设计文档 3.7）
const focusGroup = ref(null)             // 聚焦的域：点簇卡片进入，只展开它
const search = ref('')                   // 工具条搜索框
let panorama = null                      // 进入聚焦前的视口，退出时还原
const collapsedIds = shallowRef(new Set())
const theme = ref(localStorage.getItem('knowrary-theme') || 'light')
const aggregate = ref(true)              // 跨分组边默认聚合成「分组→分组 (n)」
const expanded = ref(new Set())          // 被点开看明细的分组对
const preview = shallowRef(null)         // 换布局的预览态：{ serverLayout, result }，未落盘
const history = createHistory()
const histVer = ref(0)                   // 栈深度变化时触发按钮可用状态刷新
let dirtyBefore = null                   // 当前这批未保存改动之前的快照（撤销用）
const canUndo = computed(() => histVer.value >= 0 && history.depth()[0] > 0)
const canRedo = computed(() => histVer.value >= 0 && history.depth()[1] > 0)
const labelsOn = ref(false)
// 只有用户真的操作过画布才允许落盘：既避免"打开页面就涨 revision"，
// 也不依赖 requestAnimationFrame（后台标签页 / 无头浏览器里 rAF 不触发）
const ready = ref(false)
let applyingViewport = false   // 程序化设置视口期间不落盘，否则切族/展开都白涨一个 revision

const statusText = computed(() => ({
  saved: '已保存', saving: '保存中…', dirty: '待保存', retry: '有冲突，已重试', error: '保存失败',
}[status.value] || status.value))

const visibleFamilies = () => new Set(FAMILIES.filter((f) => visible[f]))

function setBanner(text, kind = '') {
  banner.value = text
  bannerKind.value = kind
}

async function load() {
  const [index, layout] = await Promise.all([fetchIndex(), fetchLayout()])
  fetchHealth().then((h) => { has3d.value = !!h.web3d }).catch(() => {})
  indexDoc.value = index
  layoutDoc.value = layout.layout
  revision.value = layout.layout.revision
  indexRevision.value = index.revision
  Object.assign(stats, { nodes: index.stats.nodes, edges: index.stats.edges, stubs: index.stats.stubs })
  inboxCount.value = index.nodes.filter((n) => !n.virtual && !layout.layout.nodes[n.id]).length
  ready.value = false
  render({ view: 'stored' })
  reportProblems(index, layout)
}

// view: 'stored' 用 layout 里存的视口（首次加载）/ 'fit' 适应内容（换布局后）/ 'keep' 保持当前（切族、展开聚合束）
function render({ view = 'keep' } = {}) {
  const g = graph.value
  collapsedIds.value = computeCollapsed(layoutDoc.value, g.zoom(),
    { auto: autoLod.value, focus: focusGroup.value })
  const cells = buildCells(indexDoc.value, layoutDoc.value, {
    families: visibleFamilies(), showLabels: labelsOn.value,
    aggregate: aggregate.value, expanded: expanded.value, collapsed: collapsedIds.value, zoom: g.zoom(),
  })
  edgesShown.value = cells.edges.filter((e) => e.data.kind === 'edge').length
  aggShown.value = cells.edges.length - edgesShown.value
  const keep = view === 'keep' ? { zoom: g.zoom(), translate: g.translate() } : null
  applyingViewport = true
  mount(g, cells)
  if (keep) {
    g.zoomTo(keep.zoom)
    g.translate(keep.translate.tx, keep.translate.ty)
  } else if (view === 'fit') {
    g.zoomToFit({ padding: 60, maxScale: 1 })
  } else {
    applyViewport(g, layoutDoc.value.viewport)
  }
  applyingViewport = false
}

function reportProblems(index, layout) {
  const parts = []
  if (index.errors.length) parts.push(`索引有 ${index.errors.length} 个错误（knowrary check 看详情）`)
  if (layout.orphans.length) parts.push(`${layout.orphans.length} 条孤立布局记录（红色虚线节点，不会自动删除）`)
  if (layout.generated) parts.push('已按 field / 目录生成初始布局，拖动即保存')
  setBanner(parts.join('；'), index.errors.length ? 'error' : '')
}

// 与本地镜像（= 服务端最新状态）比对，值没变就不发；mount() 建父子关系触发的事件天然被过滤掉
function queueIfChanged(kind, id, patch) {
  if (preview.value) return   // 预览布局时画布是"草稿"，不写盘
  const store = kind === 'group' ? layoutDoc.value.groups : layoutDoc.value.nodes
  const cur = store[id]
  if (cur && Object.entries(patch).every(([k, v]) => (typeof v === 'number' ? Math.round(cur[k]) === v : (cur[k] ?? null) === v))) {
    return
  }
  if (!dirtyBefore) dirtyBefore = clone(layoutDoc.value)   // 这批改动的起点，撤销要回到这里
  if (cur) Object.assign(cur, patch)
  if (kind === 'group') patcher.value.queueGroup(id, patch)
  else patcher.value.queueNode(id, patch)
}

// 任何一次事件回调抛异常，都会打断 X6 的内部清理，让整张图不再响应鼠标（拖拽卡死）。
// 所以自己的回调一律包一层，异常只记录、不外抛。
function safe(fn) {
  return (...args) => {
    try {
      return fn(...args)
    } catch (err) {
      reportCrash(err)
    }
  }
}

let recoveringAt = 0
let lastBucket = 0

/** 画布出错时自愈：重建 X6 实例并按服务端状态重画，避免"卡死只能刷新"。 */
function rebuildGraph(reason = '') {
  const old = graph.value
  try {
    old?.dispose()
  } catch {
    /* 已经坏掉的实例，忽略 */
  }
  const fresh = createGraph(canvasEl.value)
  graph.value = fresh
  bindEvents(fresh)
  if (window.__kg) window.__kg.graph = fresh
  render({ view: 'stored' })
  if (reason) setBanner(`画布出错，已自动恢复交互：${reason}`, 'error')
}

function reportCrash(err) {
  const msg = String(err?.message || err?.reason || err || '未知错误')
  const now = Date.now()
  if (now - recoveringAt < 3000) return   // 防止恢复过程本身再出错导致死循环
  recoveringAt = now
  rebuildGraph(msg)
}

function bindEvents(g) {
  // 首次真实交互后才允许落盘（合成事件与真人操作都会触发 mousedown / wheel）
  const markReady = () => { ready.value = true }
  g.container.addEventListener('mousedown', markReady, { capture: true })
  g.container.addEventListener('wheel', markReady, { capture: true, passive: true })

  g.on('node:moved', safe(({ node }) => {
    if (!ready.value) return
    if (node.id.startsWith('note:') || node.id.startsWith('ref:')) {
      const pos = node.position()
      moveDecoration(node.id, Math.round(pos.x), Math.round(pos.y))
      return
    }
    for (const p of movedPositions(node)) queueIfChanged(p.kind, p.id, { x: p.x, y: p.y })
  }))
  g.on('node:change:parent', safe(({ node, current }) => {
    if (!ready.value || node.shape !== 'kg-node') return
    const pos = node.position()
    queueIfChanged('node', node.id, { group: current || null, x: Math.round(pos.x), y: Math.round(pos.y) })
  }))
  g.on('node:selected', safe(({ node }) => {
    selected.value = describe(node.id)
    focus(node.id)
    loadDetail(node.id)
  }))
  g.on('node:unselected', safe(() => { selected.value = null; detail.value = null; focus(null) }))
  g.on('blank:click', safe(() => { selected.value = null; detail.value = null; focus(null) }))
  // 悬停即高亮：不点也能看清一个节点牵着哪些线
  g.on('node:mouseenter', safe(({ node }) => { if (node.shape === 'kg-node') focus(node.id) }))
  g.on('node:mouseleave', safe(() => { focus(selected.value?.id || null) }))
  // 点簇卡片 → 放大进这个域（只展开它）；再点「返回全景」或按 Esc 缩回去
  g.on('node:click', safe(({ node }) => {
    if (node.shape === 'kg-cluster') enterGroup(node.id)
    if (node.shape === 'kg-ref') gotoNode(node.getData()?.target)
  }))
  g.on('node:dblclick', safe(({ node }) => {
    if (node.shape === 'kg-note') editNote(node.id.slice(5))
    else if (node.shape === 'kg-group') exitGroup()   // 双击域的空白处退回全景
  }))
  // 点聚合边展开这对分组之间的明细，再点收起
  g.on('edge:click', safe(({ edge }) => {
    const data = edge.getData() || {}
    if (data.kind !== 'agg') return
    const next = new Set(expanded.value)
    next.has(data.pair) ? next.delete(data.pair) : next.add(data.pair)
    expanded.value = next
    render()
  }))
  g.on('scale', safe(onZoom))
  g.on('translate', safe(() => saveViewport()))
}

function saveViewport() {
  if (!ready.value || applyingViewport) return
  patcher.value.queueViewport(currentViewport(graph.value))
}

function onZoom() {
  const g = graph.value
  saveViewport()
  const next = computeCollapsed(layoutDoc.value, g.zoom(),
    { auto: autoLod.value, focus: focusGroup.value })
  const changed = next.size !== collapsedIds.value.size
    || [...next].some((id) => !collapsedIds.value.has(id))
  // 折叠集合变了要重画；有簇卡片时缩放跨档（卡片尺寸分档跟随缩放）也要重画
  const bucket = Math.round(Math.min(3, Math.max(1, 1 / Math.max(g.zoom(), 0.05))) * 2)
  if (changed || (next.size && bucket !== lastBucket)) {
    lastBucket = bucket
    render()
    return
  }
  const shouldShow = g.zoom() > LABEL_ZOOM
  if (shouldShow !== labelsOn.value) {
    labelsOn.value = shouldShow
    applyEdgeLabels(g, indexDoc.value, shouldShow)
  }
}

// 某个节点的边在画布上的 cell id：组内边是本身，跨组边是它所属的那一束聚合边
function relatedEdgeIds(nodeId) {
  const layout = layoutDoc.value
  const fams = visibleFamilies()
  const groupOf = (nid) => layout.nodes[nid]?.group || null
  const ids = new Set()
  for (const e of indexDoc.value.edges) {
    if (e.source !== nodeId && e.target !== nodeId) continue
    if (!fams.has(e.family)) continue
    if (!layout.nodes[e.source] || !layout.nodes[e.target]) continue
    const a = groupOf(e.source)
    const b = groupOf(e.target)
    const pair = a && b ? `${a}->${b}` : null
    ids.add(!aggregate.value || !pair || a === b || expanded.value.has(pair) ? e.id : `agg:${pair}`)
  }
  return ids
}

function focus(nodeId) {
  highlightEdges(graph.value, nodeId ? relatedEdgeIds(nodeId) : null)
}

// ---- 阶段 3：节点详情 + Markdown 写回（所有写回都走 ChangeSet，确认前不碰文件）----

async function loadDetail(id) {
  detail.value = null
  try {
    detail.value = await fetchNode(id)
  } catch (err) {
    if (err.status !== 404) setBanner(`读取节点失败：${err.body?.detail || err.message}`, 'error')
  }
}

const relationTypes = computed(() =>
  (indexDoc.value?.families || []).map((f) => ({ family: f.name, types: f.types })))

const allNodeIds = computed(() => (indexDoc.value?.nodes || []).map((n) => n.id))

function queueChange(change) {
  pending.value = [...pending.value, change]
  changePreview.value = null
}

function addEdgeDraft() {
  if (!detail.value || !draft.relation || !draft.target) return
  queueChange({
    type: 'add_edge', source: detail.value.id, relation: draft.relation, target: draft.target,
    ...(draft.year ? { year: Number(draft.year) } : {}),
    ...(draft.note ? { note: draft.note } : {}),
  })
  draft.target = ''
  draft.year = ''
  draft.note = ''
}

function removeEdge(edge) {
  queueChange({ type: 'remove_edge', source: detail.value.id, relation: edge.type, target: edge.target })
}

function retypeEdge(edge, relation) {
  if (!relation || relation === edge.type) return
  queueChange({ type: 'update_edge', source: detail.value.id, target: edge.target,
                from_relation: edge.type, relation })
}

function editDesc() {
  const value = window.prompt('新的一句话摘要（desc）', detail.value?.meta?.desc || '')
  if (value === null) return
  queueChange({ type: 'update_frontmatter', source: detail.value.id, fields: { desc: value } })
}

async function previewChanges() {
  if (!pending.value.length) return
  try {
    changePreview.value = await postChanges({
      base_revision: indexRevision.value, dry_run: true, changes: pending.value,
    })
    setBanner('')
  } catch (err) {
    changePreview.value = null
    setBanner(`变更被拒绝：${err.body?.detail?.message || err.body?.detail || err.message}`, 'error')
  }
}

async function applyChanges() {
  try {
    const res = await postChanges({
      base_revision: indexRevision.value, dry_run: false, changes: pending.value,
    })
    pending.value = []
    changePreview.value = null
    const id = detail.value?.id
    await load()
    if (id) await loadDetail(id)
    setBanner(`已写回 ${res.files.length} 个文件，原文备份在 ${res.backup}`)
  } catch (err) {
    setBanner(`写回失败：${err.body?.detail?.message || err.body?.detail || err.message}`, 'error')
  }
}

function dropChange(i) {
  pending.value = pending.value.filter((_, idx) => idx !== i)
  changePreview.value = null
}

function describeChange(c) {
  if (c.type === 'add_edge') return `新增　${c.relation} → ${c.target}`
  if (c.type === 'remove_edge') return `删除　${c.relation} → ${c.target}`
  if (c.type === 'update_edge') return `改类型　${c.from_relation} → ${c.relation}（${c.target}）`
  return `改 frontmatter　${Object.entries(c.fields).map(([k, v]) => `${k} = ${v}`).join('、')}`
}

/** 搜索命中 / 3D 跳回来：展开它所在的域、居中并选中。 */
function gotoNode(id) {
  const place = layoutDoc.value?.nodes?.[id]
  if (!place) {
    setBanner(`「${id}」还没放到画布上（在 Inbox 里）`, 'error')
    return
  }
  const g = graph.value
  if (place.group && collapsedIds.value.has(place.group)) {
    if (!panorama) panorama = { zoom: g.zoom(), translate: g.translate() }
    focusGroup.value = place.group
  }
  render()
  applyingViewport = true
  g.zoomTo(Math.max(g.zoom(), 0.8))
  g.centerPoint(place.x + 90, place.y + 30)
  applyingViewport = false
  const cell = g.getCellById(id)
  if (cell) {
    g.cleanSelection?.()
    g.select?.(cell)
  }
  selected.value = describe(id)
  loadDetail(id)
  focus(id)
  search.value = ''
}

const searchHits = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return []
  return (indexDoc.value?.nodes || [])
    .filter((n) => !n.virtual && `${n.id} ${n.name || ''} ${n.desc || ''}`.toLowerCase().includes(q))
    .slice(0, 8)
})

// ---- 便签与引用卡：只存在 layout.json 里，和 md 无关 ----

const newId = (prefix) => `${prefix}${Date.now().toString(36)}`

function viewportCenter() {
  const g = graph.value
  const p = g.graphToLocal(g.container.clientWidth / 2, g.container.clientHeight / 2)
  return { x: Math.round(p.x - 90), y: Math.round(p.y - 30) }
}

function addNote() {
  const text = window.prompt('便签内容', '')
  if (!text) return
  const notes = [...(layoutDoc.value.notes || []), { id: newId('nt'), text, ...viewportCenter(), w: 190, h: 74 }]
  layoutDoc.value = { ...layoutDoc.value, notes }
  patcher.value.queueList('notes', notes)
  render()
}

function addRef() {
  const target = selected.value?.id
  if (!target) return
  const refs = [...(layoutDoc.value.refs || []), { id: newId('r'), target, ...viewportCenter(), w: 170, h: 46 }]
  layoutDoc.value = { ...layoutDoc.value, refs }
  patcher.value.queueList('refs', refs)
  render()
}

/** 便签 / 引用卡被拖动或编辑后，整表写回（它们是带 id 的小集合）。 */
function saveList(kind, updater) {
  const key = kind === 'note' ? 'notes' : 'refs'
  const items = (layoutDoc.value[key] || []).map(updater).filter(Boolean)
  layoutDoc.value = { ...layoutDoc.value, [key]: items }
  patcher.value.queueList(key, items)
}

function moveDecoration(cellId, x, y) {
  const [kind, id] = cellId.split(':')
  saveList(kind, (item) => (item.id === id ? { ...item, x, y } : item))
}

function editNote(id) {
  const note = (layoutDoc.value.notes || []).find((n) => n.id === id)
  const text = window.prompt('便签内容（清空即删除）', note?.text || '')
  if (text === null) return
  saveList('note', (item) => (item.id !== id ? item : text.trim() ? { ...item, text } : null))
  render()
}

function describe(id) {
  const index = indexDoc.value
  const node = index.nodes.find((n) => n.id === id)
  if (!node) return { id, orphan: true }
  const byId = new Map(index.edges.map((e) => [e.id, e]))
  const pick = (ids) => ids.map((eid) => byId.get(eid)).filter(Boolean)
  return { ...node, out: pick(node.out), in: pick(node.in), placed: layoutDoc.value.nodes[id] || null }
}

// —— 布局菜单：算法只生成"初始种子"，先预览、确认后才落盘 ——
const LAYOUTS = {
  mindmap: { label: '多中心脑图', run: () => mindmapLayout(indexDoc.value, layoutDoc.value), structure: true },
  community: { label: '社区发现重排（建议）', structure: false,
               run: () => communityLayout(indexDoc.value, layoutDoc.value) },
}

/** 下拉里既有"换布局"也有"换视图"：3D 是另一个页面，直接跳过去。 */
function onPick(kind) {
  if (!kind) return
  if (kind === '3d') {
    window.location.href = './3d/'
    return
  }
  runLayout(kind)
}

function runLayout(kind) {
  const spec = LAYOUTS[kind]
  const serverBefore = layoutDoc.value
  const result = spec.run()
  preview.value = { serverLayout: layoutDoc.value, result, kind }
  layoutDoc.value = {
    ...layoutDoc.value,
    groups: { ...result.groups },
    nodes: Object.fromEntries(Object.entries(result.nodes).map(
      ([id, pos]) => [id, { ...(layoutDoc.value.nodes[id] || { w: 160, h: 60, state: 'final' }), ...pos }])),
  }
  if (spec.structure) visible['结构'] = true     // 脑图 / 径向的主干就是结构边
  expanded.value = new Set()
  const extra = kind === 'mindmap' ? `${result.stats.trees} 棵脑图 + ${result.stats.strays} 个未归入层级的节点`
    : kind === 'community'
      ? `louvain 发现 ${result.communities.length} 个社区，${compareWithGroups(result.communities, serverBefore).length} 个节点建议换组`
      : `${Object.keys(result.groups).length} 个分组重排`
  setBanner(`预览「${spec.label}」：${extra}。确认后才写盘，旧布局会自动备份。`)
  render({ view: 'fit' })
}

async function applyPreview() {
  const { result, serverLayout } = preview.value
  status.value = 'saving'
  try {
    const saved = await patchLayout(toPatch(result, serverLayout, revision.value))
    preview.value = null
    await load()
    if (history.record(clone(serverLayout), clone(layoutDoc.value), '换布局')) histVer.value++
    status.value = 'saved'
    setBanner(saved.backup ? `已应用新布局，旧布局备份在 ${saved.backup}` : '已应用新布局')
  } catch (err) {
    status.value = 'error'
    setBanner(`应用失败：${err.body?.detail || err.message}`, 'error')
  }
}

function cancelPreview() {
  layoutDoc.value = preview.value.serverLayout
  preview.value = null
  setBanner('')
  render({ view: 'fit' })
}

/** 点开一个域：只展开它并放大到铺满视口（视口不落盘，纯浏览状态）。 */
function enterGroup(gid) {
  const box = layoutDoc.value.groups[gid]
  if (!box) return
  const g = graph.value
  if (!focusGroup.value) panorama = { zoom: g.zoom(), translate: g.translate() }
  focusGroup.value = gid
  render()
  applyingViewport = true
  g.zoomToRect({ x: box.x - 60, y: box.y - 60, width: box.w + 120, height: box.h + 120 }, { maxScale: 1.4 })
  applyingViewport = false
  setBanner(`已放大到「${box.name}」，点「返回全景」或按 Esc 退回`)
}

/** 退回全景：还原进入前的视口。 */
function exitGroup() {
  if (!focusGroup.value) return
  const g = graph.value
  focusGroup.value = null
  render()
  applyingViewport = true
  if (panorama) {
    g.zoomTo(panorama.zoom)
    g.translate(panorama.translate.tx, panorama.translate.ty)
  } else {
    g.zoomToFit({ padding: 60, maxScale: 1 })
  }
  applyingViewport = false
  panorama = null
  setBanner('')
}

async function restore(target, what) {
  const patch = diffPatch(layoutDoc.value, target)
  if (isEmptyPatch(patch)) return
  status.value = 'saving'
  try {
    await patchLayout({ base_revision: revision.value, ...patch })
    await load()
    status.value = 'saved'
    setBanner(what)
  } catch (err) {
    status.value = 'error'
    setBanner(`${what}失败：${err.body?.detail || err.message}`, 'error')
  }
}

async function undo() {
  if (preview.value || !canUndo.value) return
  const target = history.takeUndo()
  histVer.value++
  if (target) await restore(target, '已撤销上一步布局改动')
}

async function redo() {
  if (preview.value || !canRedo.value) return
  const target = history.takeRedo()
  histVer.value++
  if (target) await restore(target, '已重做')
}

function onKeydown(e) {
  const tag = (e.target?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea') return
  if (e.key === 'Escape') {
    exitGroup()
    return
  }
  if (!(e.metaKey || e.ctrlKey)) return
  const key = e.key.toLowerCase()
  if (key === 'escape') return
  if (key === 'z') {
    e.preventDefault()
    e.shiftKey ? redo() : undo()
  } else if (key === 'y') {
    e.preventDefault()
    redo()
  }
}

function applyThemeNow() {
  setTheme(theme.value)
  document.documentElement.dataset.theme = theme.value
  localStorage.setItem('knowrary-theme', theme.value)
  // 不用 X6 的 drawBackground/drawGrid 就地换肤：实测它会把已渲染的 cell 从 DOM 里抹掉
  // （模型里还在、画布空白）。主题切换很少见，直接重建画布最稳。
  if (graph.value) rebuildGraph()
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyThemeNow()
}

function fit() {
  ready.value = true   // 点按钮属于用户操作，之后的视口值该落盘
  graph.value.zoomToFit({ padding: 60, maxScale: 1 })
}

async function reload() {
  await patcher.value.flush()
  await load()
}

onMounted(async () => {
  setTheme(theme.value)
  document.documentElement.dataset.theme = theme.value
  const g = createGraph(canvasEl.value)
  graph.value = g
  patcher.value = createPatcher({
    getRevision: () => revision.value,
    setRevision: (r) => { revision.value = r },
    onStatus: (s, payload) => {
      status.value = s
      if (s === 'saved' && dirtyBefore) {
        if (history.record(dirtyBefore, clone(layoutDoc.value), '拖动')) histVer.value++
        dirtyBefore = null
      }
      if (s === 'error') setBanner(`保存失败：${payload?.body?.detail || payload?.message || '未知错误'}`, 'error')
      if (s === 'saved' && bannerKind.value === 'error') setBanner('')
    },
    onConflict: (fresh) => {
      layoutDoc.value = fresh.layout
      setBanner('layout 被其他窗口改过，已合并到最新 revision 后重试')
    },
  })
  bindEvents(g)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('error', onGlobalError)
  window.addEventListener('unhandledrejection', onGlobalError)
  // 本地个人工具：暴露一个调试句柄，排查渲染问题时能在控制台直接看模型
  window.__kg = { graph: g, get layout() { return layoutDoc.value }, get index() { return indexDoc.value } }
  try {
    await load()
    // 从 3D 总览跳回来时带着 ?focus=<id>：定位到那个节点，然后把参数抹掉
    const wanted = new URLSearchParams(window.location.search).get('focus')
    if (wanted) {
      ready.value = true
      gotoNode(wanted)
      window.history.replaceState({}, '', window.location.pathname)
    }
  } catch (err) {
    setBanner(`加载失败：${err.message}。确认本地服务已启动（server/dev.sh）`, 'error')
  }
})

function onGlobalError(e) {
  reportCrash(e?.error || e?.reason || e?.message)
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('error', onGlobalError)
  window.removeEventListener('unhandledrejection', onGlobalError)
  patcher.value?.flush()
})
</script>

<template>
  <div class="app">
    <header>
      <span class="brand">Knowrary</span>
      <span class="muted">结构视图</span>
      <span v-if="focusGroup" class="muted">聚焦：{{ layoutDoc?.groups?.[focusGroup]?.name }}</span>
      <span class="muted">节点 {{ stats.nodes }} · 组内边 {{ edgesShown }}<template v-if="aggShown"> · 跨组 {{ aggShown }} 束</template>
        / 共 {{ stats.edges }} · stub {{ stats.stubs }}
        <template v-if="inboxCount"> · Inbox {{ inboxCount }}</template>
      </span>
      <span class="families">
        <label v-for="f in FAMILIES" :key="f">
          <input type="checkbox" v-model="visible[f]" @change="render()" />
          <i class="swatch" :style="{ borderTopColor: FAMILY_STYLE[f].stroke,
                                      borderTopStyle: FAMILY_STYLE[f].strokeDasharray ? 'dashed' : 'solid' }" />
          {{ f }}
        </label>
      </span>
      <label class="families">
        <input type="checkbox" v-model="aggregate" @change="expanded = new Set(); render()" />
        聚合跨组边
      </label>
      <label class="families" title="缩小时把分组折叠成簇卡片（点卡片展开）">
        <input type="checkbox" v-model="autoLod" @change="render()" />
        自动折叠
        <span v-if="collapsedIds.size" class="muted">（{{ collapsedIds.size }} 簇）</span>
      </label>
      <span class="search">
        <input v-model="search" placeholder="搜索知识点…" @keydown.enter="searchHits[0] && gotoNode(searchHits[0].id)" />
        <ul v-if="searchHits.length" class="hits">
          <li v-for="h in searchHits" :key="h.id" @click="gotoNode(h.id)">
            {{ h.name || h.id }}<span class="muted"> · {{ h.field || '' }}</span>
          </li>
        </ul>
      </span>
      <button title="在视口中心加一张便签（只存 layout，不进 md）" @click="addNote">＋便签</button>
      <span class="spacer" />
      <template v-if="preview">
        <button class="primary" @click="applyPreview">应用布局</button>
        <button @click="cancelPreview">取消</button>
      </template>
      <select v-else class="layout-menu" @change="onPick($event.target.value); $event.target.value = ''">
        <option value="">视图 / 布局…</option>
        <option v-for="(spec, kind) in LAYOUTS" :key="kind" :value="kind">{{ spec.label }}</option>
        <option v-if="has3d" value="3d">3D 总览（新页面）</option>
      </select>
      <button v-if="focusGroup" class="primary" @click="exitGroup">← 返回全景</button>
      <button :disabled="!canUndo || !!preview" title="撤销（⌘Z / Ctrl+Z）" @click="undo">↶ 撤销</button>
      <button :disabled="!canRedo || !!preview" title="重做（⇧⌘Z / Ctrl+Y）" @click="redo">↷ 重做</button>
      <button @click="fit">适应窗口</button>
      <button title="画布没反应时点这里重建（不影响已保存的布局）" @click="rebuildGraph('手动重建')">恢复画布</button>
      <button :title="theme === 'dark' ? '切到浅色' : '切到深色'" @click="toggleTheme">{{ theme === 'dark' ? '☀︎' : '☾' }}</button>
      <button :disabled="!!preview" @click="reload">重新加载</button>
      <span class="rev">index r{{ indexRevision }} · layout r{{ revision }}</span>
      <span class="status" :class="status">{{ statusText }}</span>
    </header>

    <div v-if="banner" class="banner" :class="bannerKind">{{ banner }}</div>

    <main>
      <div ref="canvasEl" class="canvas" />
      <aside v-if="selected">
        <h3>{{ selected.name || selected.id }}</h3>
        <div class="desc">{{ selected.desc || '（无摘要）' }}</div>
        <dl>
          <dt>id</dt><dd>{{ selected.id }}</dd>
          <template v-if="selected.field"><dt>领域</dt><dd>{{ selected.field }}</dd></template>
          <template v-if="selected.type"><dt>类型</dt><dd>{{ selected.type }}</dd></template>
          <template v-if="selected.year"><dt>年份</dt><dd>{{ selected.year }}</dd></template>
          <template v-if="selected.weight"><dt>权重</dt><dd>{{ (selected.weight * 100).toFixed(0) }}%（pageRank）</dd></template>
          <template v-if="detail"><dt>文件</dt><dd>{{ detail.path }}</dd></template>
        </dl>

        <div class="row" v-if="detail">
          <a class="btn" :href="detail.obsidian_uri">在 Obsidian 打开</a>
          <button @click="editDesc">改摘要</button>
          <button @click="showRaw = !showRaw">{{ showRaw ? '收起原文' : '看 md 原文' }}</button>
          <button title="在当前视口放一张指向它的引用卡" @click="addRef">放引用卡</button>
        </div>
        <pre v-if="showRaw && detail" class="raw">{{ detail.raw }}</pre>

        <template v-if="detail">
          <strong>出边 {{ detail.out.length }}<span class="muted">（可改，写回本文件）</span></strong>
          <ul class="edges">
            <li v-for="e in detail.out" :key="e.id">
              <select :value="e.type" @change="retypeEdge(e, $event.target.value)">
                <optgroup v-for="g in relationTypes" :key="g.family" :label="g.family">
                  <option v-for="t in g.types" :key="t" :value="t">{{ t }}</option>
                </optgroup>
              </select>
              → {{ e.target }}<span class="fam" v-if="e.year">（{{ e.year }}）</span>
              <button class="mini" title="删除这条关系" @click="removeEdge(e)">✕</button>
            </li>
          </ul>

          <strong>新增关系</strong>
          <div class="add-edge">
            <select v-model="draft.relation">
              <option value="">类型…</option>
              <optgroup v-for="g in relationTypes" :key="g.family" :label="g.family">
                <option v-for="t in g.types" :key="t" :value="t">{{ t }}</option>
              </optgroup>
            </select>
            <input v-model="draft.target" list="kg-nodes" placeholder="目标节点 id" />
            <datalist id="kg-nodes"><option v-for="id in allNodeIds" :key="id" :value="id" /></datalist>
            <input v-model="draft.year" class="year" placeholder="年份" />
            <input v-model="draft.note" placeholder="说明（可选）" />
            <button :disabled="!draft.relation || !draft.target" @click="addEdgeDraft">加入变更</button>
          </div>

          <template v-if="detail.in_edges.length">
            <strong>入边 {{ detail.in_edges.length }}<span class="muted">（写在对方文件里）</span></strong>
            <ul class="edges">
              <li v-for="e in detail.in_edges" :key="e.id">{{ e.source }} {{ e.type }} →</li>
            </ul>
          </template>
        </template>
        <p class="muted" v-if="selected.orphan">这个节点在索引里不存在，只剩布局记录。</p>
      </aside>

      <aside v-if="pending.length" class="changes">
        <h3>待写回的变更 {{ pending.length }}</h3>
        <p class="muted">未确认前不会碰任何 md 文件。</p>
        <ul class="edges">
          <li v-for="(c, i) in pending" :key="i">
            {{ describeChange(c) }}
            <button class="mini" @click="dropChange(i)">✕</button>
          </li>
        </ul>
        <div class="row">
          <button @click="previewChanges">预览变更</button>
          <button class="primary" :disabled="!changePreview" @click="applyChanges">确认写入</button>
          <button @click="pending = []; changePreview = null">全部放弃</button>
        </div>
        <template v-if="changePreview">
          <strong>将改动 {{ changePreview.files.length }} 个文件</strong>
          <div v-for="f in changePreview.files" :key="f.path">
            <div class="muted">{{ f.path }}</div>
            <pre class="diff">{{ f.diff }}</pre>
          </div>
        </template>
      </aside>
    </main>
    <div class="hint">拖空白平移 · 滚轮缩放 · shift+拖空白框选 · 拖节点到别的分组框内即改归属（松手 300ms 后自动保存，⌘Z 可撤销）·
      悬停/选中节点高亮它的边 · 点簇卡片放大进那个域（Esc 或「返回全景」退回）· 点「跨组 n 束」展开明细</div>
  </div>
</template>
