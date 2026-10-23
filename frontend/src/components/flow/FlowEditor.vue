<script setup lang="ts">
/**
 * Flow 可视化编辑器组件（预留）
 * 
 * Phase 2 实现时接入 @vue-flow/core：
 * 
 * import { VueFlow, useVueFlow } from '@vue-flow/core'
 * import { Background } from '@vue-flow/background'
 * import { Controls } from '@vue-flow/controls'
 * import { MiniMap } from '@vue-flow/minimap'
 * 
 * 搜索结果参考：
 * - Vue Flow: 支持自定义节点、拖拽、缩放、多选
 * - LuckyFlow: AgentFlowNodeTypeCommon 自定义Agent节点
 * - vue3-workFlow: 节点模型含LLM/代码/MCP/数据库
 * 
 * 数据格式已在 types/flow.ts 中预定义，
 * 与 Vue Flow 的 Node/Edge 格式完全兼容
 */

import { useFlowEditor } from '@/composables/useFlowEditor'

const { flowDefinition, isFlowEditorEnabled } = useFlowEditor()
</script>

<template>
  <div class="flow-editor-placeholder">
    <div class="icon">🔗</div>
    <div class="title">拖曳式 Agent 工作流编辑器</div>
    <div class="desc">
      <p>Phase 2 将接入 <strong>Vue Flow</strong> 实现完整拖曳编辑</p>
      <br>
      <p style="font-size:12px;color:var(--text-secondary);">
        ✅ 数据结构已预留（节点 + 连线图结构）<br>
        ✅ 兼容 Vue Flow Node/Edge 格式<br>
        ✅ 支持自定义Agent节点组件<br>
        ✅ 支持导入/导出 Flow JSON
      </p>
      <br>
      <p style="font-size:12px;">
        当前Flow定义预览：
      </p>
      <pre style="text-align:left;font-size:11px;background:var(--bg-input);padding:12px;border-radius:6px;margin-top:8px;max-height:200px;overflow:auto;">{{ JSON.stringify(flowDefinition, null, 2) }}</pre>
    </div>
  </div>
</template>
