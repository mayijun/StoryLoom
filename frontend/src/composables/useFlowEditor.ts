/**
 * Flow编辑器逻辑（预留）
 * 
 * 搜索结果：
 * "现阶段不需要真正实现拖曳画布，但建议提前把Agent之间的
 *  交互数据结构设计为节点+连线的图结构，这样未来直接接入
 *  Vue Flow作为可视化编辑器时，底层数据模型无需大改"
 * 
 * 当前：只提供数据结构和辅助函数
 * 未来Phase 2：接入 @vue-flow/core 实现完整拖曳编辑
 */

import { ref } from 'vue'
import type { FlowDefinition, FlowNode, FlowEdge } from '@/types/flow'
import { generateDefaultFlow } from '@/types/flow'

export function useFlowEditor() {
  const flowDefinition = ref<FlowDefinition>(generateDefaultFlow([]))
  const isFlowEditorEnabled = ref(false) // Phase 2 再开启

  function updateNodePosition(nodeId: string, x: number, y: number) {
    const node = flowDefinition.value.nodes.find(n => n.id === nodeId)
    if (node) {
      node.position = { x, y }
    }
  }

  function addNode(node: FlowNode) {
    flowDefinition.value.nodes.push(node)
  }

  function removeNode(nodeId: string) {
    flowDefinition.value.nodes = flowDefinition.value.nodes.filter(n => n.id !== nodeId)
    flowDefinition.value.edges = flowDefinition.value.edges.filter(
      e => e.source !== nodeId && e.target !== nodeId
    )
  }

  function addEdge(edge: FlowEdge) {
    flowDefinition.value.edges.push(edge)
  }

  function removeEdge(edgeId: string) {
    flowDefinition.value.edges = flowDefinition.value.edges.filter(e => e.id !== edgeId)
  }

  function exportFlow(): string {
    return JSON.stringify(flowDefinition.value, null, 2)
  }

  function importFlow(json: string) {
    flowDefinition.value = JSON.parse(json)
  }

  return {
    flowDefinition, isFlowEditorEnabled,
    updateNodePosition, addNode, removeNode,
    addEdge, removeEdge,
    exportFlow, importFlow,
  }
}
