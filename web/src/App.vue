<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from 'vue'
import { fetchIndex, fetchLayout } from './api'
import { createPatcher } from './canvas/patcher'
import {
  LABEL_ZOOM, applyEdgeLabels, applyViewport, buildCells, createGraph, currentViewport,
  highlightEdges, mount, movedPositions,
} from './canvas/render'
import { FAMILIES, FAMILY_STYLE } from './canvas/shapes'

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
const stats = reactive({ nodes: 0, edges: 0, stubs: 0 })
// 结构族默认不画线：嵌套（分组框）已经表达了归属，86 条结构边里有 74 条两端同框，
// 画出来纯属重复噪音（设计文档 3.6）。需要看的时候在工具条勾上。
const visible = reactive(Object.fromEntries(FAMILIES.map((f) => [f, f !== '结构'])))
const edgesShown = ref(0)
const aggShown = ref(0)
const inboxCount = ref(0)
const aggregate = ref(true)              // 跨分组边默认聚合成「分组→分组 (n)」
const expanded = ref(new Set())          // 被点开看明细的分组对
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
  indexDoc.value = index
  layoutDoc.value = layout.layout
  revision.value = layout.layout.revision
  indexRevision.value = index.revision
  Object.assign(stats, { nodes: index.stats.nodes, edges: index.stats.edges, stubs: index.stats.stubs })
  inboxCount.value = index.nodes.filter((n) => !n.virtual && !layout.layout.nodes[n.id]).length
  ready.value = false
  render({ fitView: true })
  reportProblems(index, layout)
}

function render({ fitView = false } = {}) {
  const g = graph.value
  const cells = buildCells(indexDoc.value, layoutDoc.value, {
    families: visibleFamilies(), showLabels: labelsOn.value,
    aggregate: aggregate.value, expanded: expanded.value,
  })
  edgesShown.value = cells.edges.filter((e) => e.data.kind === 'edge').length
  aggShown.value = cells.edges.length - edgesShown.value
  const keep = fitView ? null : { zoom: g.zoom(), translate: g.translate() }
  applyingViewport = true
  mount(g, cells)
  if (keep) {
    g.zoomTo(keep.zoom)
    g.translate(keep.translate.tx, keep.translate.ty)
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
  const store = kind === 'group' ? layoutDoc.value.groups : layoutDoc.value.nodes
  const cur = store[id]
  if (cur && Object.entries(patch).every(([k, v]) => (typeof v === 'number' ? Math.round(cur[k]) === v : (cur[k] ?? null) === v))) {
    return
  }
  if (cur) Object.assign(cur, patch)
  if (kind === 'group') patcher.value.queueGroup(id, patch)
  else patcher.value.queueNode(id, patch)
}

function bindEvents(g) {
  // 首次真实交互后才允许落盘（合成事件与真人操作都会触发 mousedown / wheel）
  const markReady = () => { ready.value = true }
  g.container.addEventListener('mousedown', markReady, { capture: true })
  g.container.addEventListener('wheel', markReady, { capture: true, passive: true })

  g.on('node:moved', ({ node }) => {
    if (!ready.value) return
    for (const p of movedPositions(node)) queueIfChanged(p.kind, p.id, { x: p.x, y: p.y })
  })
  g.on('node:change:parent', ({ node, current }) => {
    if (!ready.value || node.shape !== 'kg-node') return
    const pos = node.position()
    queueIfChanged('node', node.id, { group: current || null, x: Math.round(pos.x), y: Math.round(pos.y) })
  })
  g.on('node:selected', ({ node }) => {
    selected.value = describe(node.id)
    focus(node.id)
  })
  g.on('node:unselected', () => { selected.value = null; focus(null) })
  g.on('blank:click', () => { selected.value = null; focus(null) })
  // 悬停即高亮：不点也能看清一个节点牵着哪些线
  g.on('node:mouseenter', ({ node }) => { if (node.shape === 'kg-node') focus(node.id) })
  g.on('node:mouseleave', () => { focus(selected.value?.id || null) })
  // 点聚合边展开这对分组之间的明细，再点收起
  g.on('edge:click', ({ edge }) => {
    const data = edge.getData() || {}
    if (data.kind !== 'agg') return
    const next = new Set(expanded.value)
    next.has(data.pair) ? next.delete(data.pair) : next.add(data.pair)
    expanded.value = next
    render()
  })
  g.on('scale', onZoom)
  g.on('translate', () => saveViewport())
}

function saveViewport() {
  if (!ready.value || applyingViewport) return
  patcher.value.queueViewport(currentViewport(graph.value))
}

function onZoom() {
  const g = graph.value
  saveViewport()
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

function describe(id) {
  const index = indexDoc.value
  const node = index.nodes.find((n) => n.id === id)
  if (!node) return { id, orphan: true }
  const byId = new Map(index.edges.map((e) => [e.id, e]))
  const pick = (ids) => ids.map((eid) => byId.get(eid)).filter(Boolean)
  return { ...node, out: pick(node.out), in: pick(node.in), placed: layoutDoc.value.nodes[id] || null }
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
  const g = createGraph(canvasEl.value)
  graph.value = g
  patcher.value = createPatcher({
    getRevision: () => revision.value,
    setRevision: (r) => { revision.value = r },
    onStatus: (s, payload) => {
      status.value = s
      if (s === 'error') setBanner(`保存失败：${payload?.body?.detail || payload?.message || '未知错误'}`, 'error')
      if (s === 'saved' && bannerKind.value === 'error') setBanner('')
    },
    onConflict: (fresh) => {
      layoutDoc.value = fresh.layout
      setBanner('layout 被其他窗口改过，已合并到最新 revision 后重试')
    },
  })
  bindEvents(g)
  try {
    await load()
  } catch (err) {
    setBanner(`加载失败：${err.message}。确认本地服务已启动（server/dev.sh）`, 'error')
  }
})

onBeforeUnmount(() => { patcher.value?.flush() })
</script>

<template>
  <div class="app">
    <header>
      <span class="brand">Knowrary</span>
      <span class="muted">结构视图</span>
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
      <span class="spacer" />
      <button @click="fit">适应窗口</button>
      <button @click="reload">重新加载</button>
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
          <template v-if="selected.status"><dt>状态</dt><dd>{{ selected.status }}</dd></template>
          <template v-if="selected.placed"><dt>分组</dt><dd>{{ selected.placed.group || '（顶层）' }}</dd></template>
          <template v-if="selected.path"><dt>文件</dt><dd>{{ selected.path }}</dd></template>
        </dl>
        <template v-if="selected.out?.length">
          <strong>出边 {{ selected.out.length }}</strong>
          <ul><li v-for="e in selected.out" :key="e.id">{{ e.type }} → {{ e.target }}
            <span class="fam">（{{ e.family }}{{ e.year ? ' ' + e.year : '' }}）</span></li></ul>
        </template>
        <template v-if="selected.in?.length">
          <strong>入边 {{ selected.in.length }}</strong>
          <ul><li v-for="e in selected.in" :key="e.id">{{ e.source }} {{ e.type }} →
            <span class="fam">（{{ e.family }}）</span></li></ul>
        </template>
        <p class="muted" v-if="selected.orphan">这个节点在索引里不存在，只剩布局记录。</p>
      </aside>
    </main>
    <div class="hint">拖空白平移 · 滚轮缩放 · shift+拖空白框选 · 拖节点到别的分组框内即改归属（松手 300ms 后自动保存）·
      悬停/选中节点高亮它的边 · 点「跨组 n 束」的粗线展开这对分组之间的明细，再点收起</div>
  </div>
</template>
