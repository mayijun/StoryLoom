/**
 * Flow 编辑器类型定义（预留Vue Flow）
 * 
 * 数据结构严格对齐 Vue Flow 格式：
 * - Node: { id, type, position: {x,y}, data }
 * - Edge: { id, source, target, type }
 * 
 * 搜索结果确认：
 * "建议提前把Agent之间的交互数据结构设计为节点+连线的图结构，
 *  这样未来直接接入Vue Flow时底层数据模型无需大改"
 * 
 * 参考：
 * - vue3-workFlow: 节点模型含开始/判断/LLM/代码/MCP/数据库/结束
 * - LuckyFlow: AgentFlowNodeTypeCommon 自定义Agent节点
 */

export interface FlowNode {
  id: string
  type: 'agent' | 'asset' | 'process' | 'start' | 'end'
  position: { x: number; y: number }
  data: Record<string, any>
  label?: string
  sourcePosition?: 'top' | 'right' | 'bottom' | 'left'
  targetPosition?: 'top' | 'right' | 'bottom' | 'left'
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  type: 'default' | 'data_flow' | 'control_flow'
  label?: string
  data?: Record<string, any>
}

export interface FlowDefinition {
  flow_id: string
  name: string
  nodes: FlowNode[]
  edges: FlowEdge[]
  viewport: { x: number; y: number; zoom: number }
}

/**
 * 从当前Agent配置生成默认的Flow定义
 * 这样即使还没有实现拖曳编辑器，
 * 后端也能用这个数据结构来编排Agent
 */
export function generateDefaultFlow(agentIds: string[]): FlowDefinition {
  const nodes: FlowNode[] = [
    { id: 'start', type: 'start', position: { x: 0, y: 200 }, data: { label: '开始' } },
  ]
  const edges: FlowEdge[] = []

  // 默认线性流程
  const defaultOrder = [
    'surprise', 'foreshadowing', 'director',
    'actors', 'consistency', 'prose',
  ]

  let prevId = 'start'
  let x = 200

  for (const step of defaultOrder) {
    const nodeId = `node_${step}`
    nodes.push({
      id: nodeId,
      type: 'process',
      position: { x, y: 200 },
      data: { step, label: step },
    })
    edges.push({
      id: `edge_${prevId}_${nodeId}`,
      source: prevId,
      target: nodeId,
      type: 'control_flow',
    })
    prevId = nodeId
    x += 250
  }

  nodes.push({ id: 'end', type: 'end', position: { x, y: 200 }, data: { label: '结束' } })
  edges.push({
    id: `edge_${prevId}_end`,
    source: prevId,
    target: 'end',
    type: 'control_flow',
  })

  return {
    flow_id: 'default',
    name: 'Default Scene Flow',
    nodes,
    edges,
    viewport: { x: 0, y: 0, zoom: 1 },
  }
}
