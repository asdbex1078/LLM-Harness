// X6 形状与边样式：纯 SVG，不用框架组件（几千节点下组件实例会成为瓶颈）。
import { Graph } from '@antv/x6'

export const NODE_W = 160
export const NODE_H = 60

// 五个关系族各一种线型（设计文档 3.6）。结构族靠嵌套表达，默认不画线，可在工具条勾开。
export const FAMILY_STYLE = {
  // 结构族默认由嵌套表达、不画线（见 App.vue 的 visible 初值）；勾开时用最淡的灰蓝
  结构: { stroke: '#b9cbdd', strokeWidth: 1, targetMarker: 'block', strokeDasharray: null },
  依赖: { stroke: '#8a8a8a', strokeWidth: 1, targetMarker: 'block', strokeDasharray: null },
  演化: { stroke: '#e07b1a', strokeWidth: 2.5, targetMarker: 'block', strokeDasharray: null },
  对照: { stroke: '#8e5bd6', strokeWidth: 1, targetMarker: null, strokeDasharray: '5 4' },
  弱关联: { stroke: '#bbb', strokeWidth: 1, targetMarker: null, strokeDasharray: '2 3' },
}

export const FAMILIES = Object.keys(FAMILY_STYLE)

export function registerShapes() {
  Graph.registerNode('kg-node', {
    inherit: 'rect',
    width: NODE_W,
    height: NODE_H,
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'text', selector: 'title' },
      { tagName: 'text', selector: 'desc' },
    ],
    attrs: {
      body: { rx: 6, ry: 6, fill: '#fff', stroke: '#9aa7b4', strokeWidth: 1 },
      title: { refX: 10, refY: 21, fontSize: 13, fontWeight: 600, fill: '#1f2933', textAnchor: 'start' },
      desc: {
        refX: 10, refY: 41, fontSize: 11, fill: '#66737f', textAnchor: 'start',
        textWrap: { width: -20, height: 16, ellipsis: true },
      },
    },
  }, true)

  Graph.registerNode('kg-group', {
    inherit: 'rect',
    markup: [
      { tagName: 'rect', selector: 'body' },
      { tagName: 'text', selector: 'label' },
    ],
    attrs: {
      body: { rx: 8, ry: 8, fill: '#eef2f8', stroke: '#c3cede', strokeWidth: 1, fillOpacity: 0.75 },
      label: { refX: 12, refY: 22, fontSize: 13, fontWeight: 600, fill: '#4a5b6d', textAnchor: 'start' },
    },
  }, true)
}

// 节点视觉状态：draft 虚线浅填充、stub 灰色虚线、到期复习（阶段 4）留角标位
export function nodeAttrs(indexNode, layoutNode) {
  const draft = layoutNode?.state === 'draft'
  const stub = !!indexNode?.stub
  return {
    body: {
      fill: draft ? '#fffdf5' : stub ? '#fafafa' : '#fff',
      stroke: draft ? '#d9a53b' : stub ? '#c4c4c4' : '#9aa7b4',
      strokeDasharray: draft ? '4 3' : stub ? '3 3' : null,
    },
    title: { text: indexNode?.name || indexNode?.id || '' },
    desc: { text: (indexNode?.desc || '').slice(0, 40) },
  }
}

// 跨分组边聚合成一条「分组 A → 分组 B (n)」：中性灰，粗细随条数增长，点它展开明细
export function aggregateAttrs(count) {
  return {
    line: {
      stroke: '#9fb0c2',
      strokeWidth: Math.min(6, 1.5 + count * 0.45),
      strokeOpacity: 0.75,
      targetMarker: { name: 'block', width: 9, height: 7 },
    },
  }
}

export function aggregateLabel(count) {
  return {
    attrs: {
      text: { text: String(count), fontSize: 11, fill: '#5b6b7c', fontWeight: 600 },
      rect: { fill: '#eef2f8', stroke: '#c3cede', rx: 7, ry: 7, refWidth: '120%', refHeight: '120%' },
    },
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
