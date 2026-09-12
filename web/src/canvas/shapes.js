// X6 形状与配色：纯 SVG（不用框架组件，几千节点下组件实例会成为瓶颈），
// 但"纯 SVG"不等于"素"——配色、字号层级、圆角、留白决定了它像线框图还是像手画的图。
import { Graph } from '@antv/x6'

// 分组配色：柔和的分类色板，每个分组一套（描边 / 填充 / 标题）。
// 取值参考手绘图的习惯：低饱和描边 + 极浅填充，白底上不刺眼，缩小后仍分得清。
export const PALETTE = [
  { key: 'blue',   line: '#3f74b5', fill: '#f2f7fd', head: '#eaf1fb', text: '#28527f' },
  { key: 'teal',   line: '#2f8d7b', fill: '#f0faf7', head: '#e4f5f0', text: '#1f6659' },
  { key: 'amber',  line: '#c07a26', fill: '#fdf7ee', head: '#faf0df', text: '#8a5615' },
  { key: 'violet', line: '#7f5bc4', fill: '#f7f4fd', head: '#efeafb', text: '#5b3d95' },
  { key: 'rose',   line: '#bb5570', fill: '#fdf3f5', head: '#fae9ee', text: '#8c3a51' },
  { key: 'cyan',   line: '#2b7f9e', fill: '#f0f9fc', head: '#e2f2f8', text: '#1d5e77' },
  { key: 'olive',  line: '#7c8a2c', fill: '#f8faee', head: '#f1f5de', text: '#5a661c' },
  { key: 'clay',   line: '#a45f3e', fill: '#fdf5f1', head: '#f8eae2', text: '#7b432a' },
  { key: 'indigo', line: '#5560b8', fill: '#f4f5fd', head: '#e9ebfa', text: '#3a4291' },
  { key: 'moss',   line: '#4e8c5a', fill: '#f2faf4', head: '#e6f4ea', text: '#356140' },
]
export const NEUTRAL = { key: 'gray', line: '#94a3b1', fill: '#fafbfc', head: '#f1f3f6', text: '#55636f' }

// 深色主题用同一批色相，把填充压暗、描边提亮，保证在深底上仍分得清簇
export const PALETTE_DARK = PALETTE.map((c) => ({
  key: c.key, line: c.line, fill: mixDark(c.line, 0.16), head: mixDark(c.line, 0.26), text: lighten(c.line, 0.45),
}))
export const NEUTRAL_DARK = { key: 'gray', line: '#6b7683', fill: '#1e242b', head: '#252c34', text: '#9fb0bf' }

export const THEME = {
  light: { bg: '#fafbfc', grid: '#e8ebef', title: '#1c2b3a', groupFill: '#ffffff', groupStroke: '#d8e0e8',
           pill: '#ffffff', edgeLabel: '#7a8794', labelBg: '#ffffff' },
  dark: { bg: '#14181d', grid: '#222931', title: '#e7eef5', groupFill: '#181d23', groupStroke: '#2b333c',
          pill: '#1e242b', edgeLabel: '#95a3b1', labelBg: '#1a1f26' },
}

let theme = 'light'
export const setTheme = (name) => { theme = name === 'dark' ? 'dark' : 'light' }
export const currentTheme = () => theme
export const tokens = () => THEME[theme]

function hex(c) {
  const n = parseInt(c.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
function toHex([r, g, b]) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')
}
function mixDark(color, ratio) {
  const [r, g, b] = hex(color)
  const base = hex('#14181d')
  return toHex([base[0] + (r - base[0]) * ratio, base[1] + (g - base[1]) * ratio, base[2] + (b - base[2]) * ratio])
}
function lighten(color, ratio) {
  const [r, g, b] = hex(color)
  return toHex([r + (255 - r) * ratio, g + (255 - g) * ratio, b + (255 - b) * ratio])
}

/** 分组 → 配色：按分组 id 稳定取色，同一分组每次都是同一个颜色。 */
export function paletteFor(groupId, allGroupIds) {
  const palette = theme === 'dark' ? PALETTE_DARK : PALETTE
  const neutral = theme === 'dark' ? NEUTRAL_DARK : NEUTRAL
  if (!groupId) return neutral
  const i = allGroupIds.indexOf(groupId)
  return i < 0 ? neutral : palette[i % palette.length]
}

// 节点尺寸分三档：度数越高的知识点越大，一眼能看出骨干与末梢
// 三种形态而不是三种大小的矩形：骨干=带色条的卡片，中间=圆角卡片，末梢=胶囊。
// 档位按 pageRank 权重（index.json 里的 weight，0~1）而不是度数——度数只数"连了几条"，
// pageRank 还看"连的对象重不重要"，更贴近"哪些是骨干"。实测 72 节点里 >=0.5 的 9 个、>=0.3 的 35 个。
export const SIZES = [
  { min: 0.5, w: 196, h: 64, rx: 14, title: 14.5, desc: 11, chars: 40, accent: 5, shape: 'card' },
  { min: 0.3, w: 176, h: 52, rx: 12, title: 13, desc: 10.5, chars: 22, accent: 0, shape: 'card' },
  { min: 0, w: 148, h: 38, rx: 19, title: 12.5, desc: 0, chars: 0, accent: 0, shape: 'pill' },
]
export const NODE_W = SIZES[1].w
export const NODE_H = SIZES[1].h

const ICONS = [
  [/Agent|任务|事件|恢复|检查点|幂等/, '🤖'],
  [/编译|解释|字节码|IR|JIT|VM|GCC|Clang|LLVM/, '⚙️'],
  [/CPU|寄存器|内存|总线|硬盘|缓存|硬件|IO|ROM|RAM|EPROM|控制器|运算器/, '🔧'],
  [/指令|ISA|RISC|CISC|微架构|汇编/, '🧩'],
  [/栈|堆|段|内存布局|栈帧|程序/, '🧱'],
  [/理论|逻辑|定理|数论|图灵|冯诺依曼|架构|电学/, '📐'],
  [/语言|C语言|JVM语言/, '💬'],
]

/** 节点图标：按名称 / 类型 / 标签匹配，一个知识点最多一个符号，认领域用。 */
export function iconFor(node) {
  const hay = [node?.name, node?.id, node?.type, ...(node?.tags || [])].filter(Boolean).join(' ')
  return ICONS.find(([re]) => re.test(hay))?.[1] || ''
}

/** 按 pageRank 权重定档；老索引没有 weight 时退回按度数估算。 */
export function sizeFor(node) {
  const weight = typeof node === 'number'
    ? Math.min(1, node / 12)
    : (node?.weight ?? Math.min(1, (node?.degree || 0) / 12))
  return SIZES.find((s) => weight >= s.min) || SIZES[SIZES.length - 1]
}

// 五个关系族各一种线型（设计文档 3.6）。结构族靠嵌套表达，默认不画线，可在工具条勾开。
export const FAMILY_STYLE = {
  结构: { stroke: '#93aec9', strokeWidth: 1.4, targetMarker: 'block', strokeDasharray: null, curved: true },
  依赖: { stroke: '#9aa7b4', strokeWidth: 1.2, targetMarker: 'block', strokeDasharray: null },
  演化: { stroke: '#e0891f', strokeWidth: 2.2, targetMarker: 'block', strokeDasharray: null },
  对照: { stroke: '#9169cf', strokeWidth: 1.2, targetMarker: null, strokeDasharray: '6 4' },
  弱关联: { stroke: '#c3cbd4', strokeWidth: 1, targetMarker: null, strokeDasharray: '2 4' },
}

export const FAMILIES = Object.keys(FAMILY_STYLE)

export function registerShapes() {
  Graph.registerNode('kg-node', {
    inherit: 'rect',
    width: NODE_W,
    height: NODE_H,
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'rect', selector: 'accent' },
      { tagName: 'text', selector: 'title' },
      { tagName: 'text', selector: 'desc' },
    ],
    attrs: {
      body: { rx: 12, ry: 12, fill: '#fff', stroke: '#c6d0da', strokeWidth: 1.2, class: 'kg-card' },
      accent: { x: 0, y: 0, width: 0, refHeight: '100%', rx: 3, ry: 3, fill: 'transparent' },
      title: { refX: 13, refY: 20, fontSize: 13, fontWeight: 600, fill: '#1f2933', textAnchor: 'start',
               textWrap: { width: -26, ellipsis: true } },
      desc: { refX: 13, refY: 38, fontSize: 10.5, fill: '#8593a1', textAnchor: 'start',
              textWrap: { width: -26, ellipsis: true } },
    },
  }, true)

  // 便签：画布上的自由文字，不属于任何知识点，只存在 layout.json 里
  Graph.registerNode('kg-note', {
    inherit: 'rect',
    width: 190, height: 74,
    markup: [{ tagName: 'rect', selector: 'body' }, { tagName: 'text', selector: 'text' }],
    attrs: {
      body: { rx: 6, ry: 6, fill: '#fff7d6', stroke: '#e3d08a', strokeWidth: 1, class: 'kg-card' },
      text: { refX: 12, refY: 16, fontSize: 12, fill: '#6b5a1e', textAnchor: 'start',
              textWrap: { width: -24, ellipsis: true } },
    },
  }, true)

  // 引用卡：同一个知识点在别处再出现一次（虚线边框表示"这是引用，不是本体"）
  Graph.registerNode('kg-ref', {
    inherit: 'rect',
    width: 170, height: 46,
    markup: [{ tagName: 'rect', selector: 'body' }, { tagName: 'text', selector: 'label' },
             { tagName: 'text', selector: 'tag' }],
    attrs: {
      body: { rx: 10, ry: 10, fill: 'transparent', stroke: '#9aa7b4', strokeWidth: 1.2,
              strokeDasharray: '5 4' },
      label: { refX: 12, refY: 18, fontSize: 12.5, fontWeight: 600, textAnchor: 'start',
               textWrap: { width: -24, ellipsis: true } },
      tag: { refX: 12, refY: 34, fontSize: 10.5, text: '引用 · 点击跳到本体', opacity: 0.7, textAnchor: 'start' },
    },
  }, true)

  Graph.registerNode('kg-cluster', {
    inherit: 'rect',
    width: CLUSTER_W,
    height: CLUSTER_H,
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'rect', selector: 'accent' },
      { tagName: 'text', selector: 'title' },
      { tagName: 'text', selector: 'count' },
      { tagName: 'text', selector: 'list' },
      { tagName: 'text', selector: 'hint' },
    ],
    attrs: {
      body: { rx: 16, ry: 16, fill: '#fff', stroke: '#c6d0da', strokeWidth: 1.6, class: 'kg-card' },
      accent: { x: 0, y: 0, width: 6, refHeight: '100%', rx: 3, ry: 3, fill: 'transparent' },
      title: { refX: 18, refY: 26, fontSize: 16, fontWeight: 700, textAnchor: 'start' },
      count: { refX: 18, refY: 48, fontSize: 11.5, textAnchor: 'start' },
      list: { refX: 18, refY: 72, fontSize: 11.5, textAnchor: 'start', textWrap: { width: -36, ellipsis: true } },
      hint: { refX: 18, refY: CLUSTER_H - 16, fontSize: 10.5, textAnchor: 'start' },
    },
  }, true)

  Graph.registerNode('kg-group', {
    inherit: 'rect',
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'rect', selector: 'head' },
      { tagName: 'text', selector: 'label' },
    ],
    attrs: {
      body: { rx: 16, ry: 16, fill: '#fbfcfd', stroke: '#d8e0e8', strokeWidth: 1.2, class: 'kg-group-box' },
      head: { rx: 14, ry: 14, refWidth: '100%', height: 34, fill: '#eef2f6' },
      label: { refX: 16, refY: 22, fontSize: 13, fontWeight: 600, fill: '#4a5b6d', textAnchor: 'start' },
    },
  }, true)
}

export const CLUSTER_W = 260
export const CLUSTER_H = 128

/** 折叠后的簇卡片：分组名 + 节点数 + 度数最高的几个节点，缩小时一眼看清这块是什么。 */
const truncate = (text, max) => (text.length > max ? `${text.slice(0, max)}…` : text)

/**
 * 簇卡片的尺寸与字号跟着"它替代的那个分组框"走，不跟缩放耦合：
 * 折叠后卡片占据原分组的位置，缩小时它本来就大，字自然读得出来；
 * 早先按 1/zoom 放大会算出极端值，触发 X6 文本处理递归爆栈。
 */
export function clusterBox(group, zoom = 1) {
  // 卡片至少要"屏幕上看得清"：世界尺寸随缩放放大，但夹在 1~3 倍——
  // 早先直接用 1/zoom（能到 20 倍）会让 X6 的文本处理递归爆栈。
  const k = Math.min(3, Math.max(1, 1 / Math.max(zoom, 0.05)))
  const w = Math.max(CLUSTER_W * k, Math.min(group.w || CLUSTER_W, 1100))
  const h = Math.max(CLUSTER_H * k, Math.min(group.h || CLUSTER_H, 480))
  return { w, h }
}

export function clusterAttrs(name, summary, color = NEUTRAL, box = { w: CLUSTER_W, h: CLUSTER_H }) {
  const s = Math.max(1, Math.min(box.h / CLUSTER_H, 3.2))   // 字号随卡片变大，但设上限
  return {
    body: { fill: color.fill, stroke: color.line, strokeWidth: 1.6 * s, rx: 16 * s, ry: 16 * s, class: 'kg-card' },
    accent: { width: 6 * s, height: box.h, rx: 3 * s, ry: 3 * s, fill: color.line },
    title: { text: truncate(name, 16), fill: color.text, fontSize: 17 * s, fontWeight: 700,
             refX: 20 * s, refY: 30 * s },
    count: { text: `${summary.count} 个知识点`, fill: color.text, fontSize: 12 * s, refX: 20 * s, refY: 54 * s,
             opacity: 0.85 },
    list: { text: truncate(summary.top.join(' · '), 30), fill: tokens().title, fontSize: 12 * s,
            refX: 20 * s, refY: 80 * s, opacity: 0.75 },
    hint: { text: '点开展开这一簇', fill: color.text, fontSize: 11 * s, refX: 20 * s, refY: box.h - 18 * s,
            opacity: 0.5 },
  }
}

/** 节点视觉：按所属分组配色，按度数定档，draft 虚线、stub 灰调。 */
export function nodeAttrs(indexNode, layoutNode, color = NEUTRAL) {
  const draft = layoutNode?.state === 'draft'
  const stub = !!indexNode?.stub
  const size = sizeFor(indexNode)
  const tone = stub ? NEUTRAL : color
  return {
    accent: { width: size.accent, height: size.h, fill: size.accent ? tone.line : 'transparent' },
    body: {
      rx: size.rx, ry: size.rx,
      class: size.shape === 'pill' ? 'kg-pill' : 'kg-card',
      fill: draft ? '#fffdf4' : size.shape === 'pill' ? tokens().pill : tone.fill,
      stroke: draft ? '#d9a53b' : tone.line,
      strokeWidth: stub ? 1 : size.shape === 'pill' ? 1.1 : 1.3,
      strokeDasharray: draft ? '5 3' : stub ? '3 3' : null,
    },
    title: {
      text: (size.shape === 'pill' ? '' : `${iconFor(indexNode)} `).trimStart()
        ? `${iconFor(indexNode)} ${indexNode?.name || indexNode?.id || ''}`.trim()
        : indexNode?.name || indexNode?.id || '',
      fontSize: size.title,
      fill: stub ? tone.text : tokens().title,
      refX: size.accent ? 13 + size.accent : 13,
      refY: size.desc ? 20 : size.h / 2,
      textVerticalAnchor: 'middle',
      textWrap: { width: size.accent ? -32 : -26, ellipsis: true },
    },
    desc: {
      // 按字数截断而不是靠 textWrap 限高：行数确定，永远不会溢出卡片
      text: size.chars ? (indexNode?.desc || '').slice(0, size.chars) : '',
      fontSize: size.desc || 1,
      fill: tone.text,
      opacity: size.desc ? 0.75 : 0,
      refX: size.accent ? 13 + size.accent : 13,
      refY: size.h - 16,
      textVerticalAnchor: 'middle',
      textWrap: { width: size.accent ? -32 : -26, ellipsis: true },
    },
  }
}

export function groupAttrs(name, color = NEUTRAL) {
  return {
    body: { fill: tokens().groupFill, stroke: color.line, strokeWidth: 1.1, strokeOpacity: 0.4, rx: 16, ry: 16,
            class: 'kg-group-box' },
    head: { fill: color.head, rx: 16, ry: 16, height: 34, refWidth: '100%' },
    label: { text: name, fill: color.text, fontSize: 13, fontWeight: 600 },
  }
}

// 跨分组边聚合成一条「分组 A → 分组 B (n)」：中性灰，粗细随条数增长，点它展开明细
export function aggregateAttrs(count) {
  return {
    line: {
      stroke: '#aeb9c5',
      strokeWidth: Math.min(5, 1.2 + count * 0.35),
      strokeOpacity: 0.4,          // 跨组束是"有联系"的提示，不该抢主干的视觉；选中节点时会高亮
      targetMarker: { name: 'block', width: 8, height: 6 },
    },
  }
}

export function aggregateLabel(count) {
  return {
    attrs: {
      text: { text: String(count), fontSize: 11, fill: tokens().edgeLabel, fontWeight: 600 },
      rect: { fill: tokens().labelBg, stroke: tokens().groupStroke, rx: 8, ry: 8, refWidth: '140%', refHeight: '130%' },
    },
  }
}

export function noteAttrs(note, color = NEUTRAL) {
  return {
    body: { fill: note.color || (currentTheme() === 'dark' ? '#3a3419' : '#fff7d6'),
            stroke: currentTheme() === 'dark' ? '#5e5427' : '#e3d08a' },
    text: { text: note.text || '（空便签，双击编辑）',
            fill: currentTheme() === 'dark' ? '#e8dca9' : '#6b5a1e' },
  }
}

export function refAttrs(name, color = NEUTRAL) {
  return {
    body: { stroke: color.line, strokeDasharray: '5 4', fill: 'transparent' },
    label: { text: name, fill: tokens().title },
    tag: { fill: color.text },
  }
}

export function edgeAttrs(family) {
  const s = FAMILY_STYLE[family] || FAMILY_STYLE['弱关联']
  return {
    line: {
      stroke: s.stroke,
      strokeWidth: s.strokeWidth,
      strokeDasharray: s.strokeDasharray,
      targetMarker: s.targetMarker ? { name: 'block', width: 8, height: 6 } : null,
    },
  }
}
