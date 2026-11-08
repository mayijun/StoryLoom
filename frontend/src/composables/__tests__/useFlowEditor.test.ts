import { describe, it, expect, beforeEach } from 'vitest'
import { useFlowEditor } from '@/composables/useFlowEditor'
import type { FlowNode, FlowEdge } from '@/types/flow'

function node(id: string, x = 0, y = 0): FlowNode {
  return { id, type: 'agent', position: { x, y }, data: {} }
}

function edge(id: string, source: string, target: string): FlowEdge {
  return { id, source, target, type: 'default' }
}

describe('useFlowEditor', () => {
  let editor: ReturnType<typeof useFlowEditor>

  beforeEach(() => {
    editor = useFlowEditor()
  })

  it('初始化为默认流程，包含开始/结束节点', () => {
    const ids = editor.flowDefinition.value.nodes.map(n => n.id)

    expect(ids).toContain('start')
    expect(ids).toContain('end')
    expect(editor.isFlowEditorEnabled.value).toBe(false)
  })

  it('addNode 追加节点', () => {
    const before = editor.flowDefinition.value.nodes.length
    editor.addNode(node('n1'))

    expect(editor.flowDefinition.value.nodes).toHaveLength(before + 1)
    expect(editor.flowDefinition.value.nodes.at(-1)?.id).toBe('n1')
  })

  it('removeNode 删除节点并清理相关边', () => {
    editor.addNode(node('a'))
    editor.addNode(node('b'))
    editor.addEdge(edge('e1', 'a', 'b'))
    editor.addEdge(edge('e2', 'start', 'a'))
    editor.addEdge(edge('e3', 'b', 'end'))

    editor.removeNode('a')

    const nodeIds = editor.flowDefinition.value.nodes.map(n => n.id)
    const edgeIds = editor.flowDefinition.value.edges.map(e => e.id)

    expect(nodeIds).not.toContain('a')
    expect(edgeIds).not.toContain('e1')
    expect(edgeIds).not.toContain('e2')
    expect(edgeIds).toContain('e3')
  })

  it('updateNodePosition 更新指定节点位置', () => {
    editor.updateNodePosition('start', 100, 200)

    const start = editor.flowDefinition.value.nodes.find(n => n.id === 'start')!
    expect(start.position).toEqual({ x: 100, y: 200 })
  })

  it('updateNodePosition 对不存在节点无副作用', () => {
    editor.updateNodePosition('not-exist', 1, 1)
    expect(editor.flowDefinition.value.nodes.find(n => n.id === 'not-exist')).toBeUndefined()
  })

  it('addEdge / removeEdge 维护边列表', () => {
    editor.addEdge(edge('e1', 'start', 'end'))

    expect(editor.flowDefinition.value.edges.find(e => e.id === 'e1')).toBeDefined()

    editor.removeEdge('e1')

    expect(editor.flowDefinition.value.edges.find(e => e.id === 'e1')).toBeUndefined()
  })

  it('exportFlow 返回 JSON 字符串，importFlow 可还原', () => {
    editor.addNode(node('custom'))
    const json = editor.exportFlow()

    expect(typeof json).toBe('string')
    const parsed = JSON.parse(json)
    expect(parsed.nodes.some((n: FlowNode) => n.id === 'custom')).toBe(true)

    // 用一个空流程覆盖
    editor.importFlow(JSON.stringify({
      flow_id: 'f1', name: '导入', nodes: [node('only')], edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }))

    expect(editor.flowDefinition.value.nodes.map(n => n.id)).toEqual(['only'])
    expect(editor.flowDefinition.value.edges).toHaveLength(0)
  })
})
