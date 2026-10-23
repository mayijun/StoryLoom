<script setup lang="ts">
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import AgentNode from './nodes/AgentNode.vue'

// ★ 直接使用已预定义的 flowDefinition 数据
// 无需任何数据结构改动！
import { useFlowEditor } from '@/composables/useFlowEditor'
const { flowDefinition } = useFlowEditor()
</script>

<template>
  <VueFlow
    :nodes="flowDefinition.nodes"
    :edges="flowDefinition.edges"
    :default-viewport="flowDefinition.viewport"
  >
    <template #node-agent="nodeProps">
      <AgentNode v-bind="nodeProps" />
    </template>
    <Background />
    <Controls />
    <MiniMap />
  </VueFlow>
</template>
