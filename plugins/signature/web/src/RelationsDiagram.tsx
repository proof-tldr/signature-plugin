import { BoxIcon } from 'lucide-react'
import { type Edge, Handle, type NodeProps, Position, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'

import { type DiagramNode, HUB, type HubNode, laidOut, THING, type ThingNode } from './layout'
import type { Understanding } from './review'

type RelationsDiagramProps = {
  understanding: Understanding
  selected: string | null
  onSelect: (id: string) => void
}

export function RelationsDiagram(props: RelationsDiagramProps) {
  return (
    <ReactFlowProvider>
      <LaidOutDiagram {...props} />
    </ReactFlowProvider>
  )
}

function LaidOutDiagram({ understanding, selected, onSelect }: RelationsDiagramProps) {
  const [layout, setLayout] = useState<{ nodes: DiagramNode[]; edges: Edge[] } | null>(null)
  const { fitView } = useReactFlow()

  useEffect(() => {
    let current = true
    laidOut(understanding).then((placed) => {
      if (current) setLayout(placed)
    })
    return () => {
      current = false
    }
  }, [understanding])

  useEffect(() => {
    if (layout) requestAnimationFrame(() => fitView({ padding: 0.08 }))
  }, [layout, fitView])

  const nodes = useMemo(
    () => (layout?.nodes ?? []).map((node) => ({ ...node, selected: node.id === selected || node.id === `hub-${selected}` })),
    [layout, selected],
  )
  const edges = useMemo(
    () =>
      (layout?.edges ?? []).map((edge) => {
        const lit = selected !== null && [edge.source, edge.target, edge.data?.fact].includes(selected)
        return {
          ...edge,
          type: 'straight',
          style: { stroke: lit ? 'var(--foreground)' : 'var(--faint)', strokeWidth: lit ? 2 : 1.25 },
        }
      }),
    [layout, selected],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      zoomOnScroll={false}
      panOnScroll={false}
      preventScrolling={false}
      onNodeClick={(_, node) => onSelect(node.type === 'hub' ? node.id.replace(/^hub-/, '') : node.id)}
      colorMode="light"
      minZoom={0.4}
      maxZoom={1.4}
      proOptions={{ hideAttribution: true }}
      aria-label="How the things in your business relate"
    />
  )
}

// Lines run centre to centre under the boxes, so a relationship reads the same from either end.
function Centre() {
  const centre = { top: '50%', left: '50%', right: 'auto', bottom: 'auto' }
  return (
    <>
      <Handle type="target" position={Position.Top} style={centre} />
      <Handle type="source" position={Position.Top} style={centre} />
    </>
  )
}

function ThingBox({ data, selected }: NodeProps<ThingNode>) {
  return (
    <div
      className={`flex cursor-pointer items-center gap-2 rounded-(--radius-surface) border px-3 text-sm font-medium shadow-low transition-colors ${
        selected ? 'border-ring bg-selected' : 'border-border bg-card hover:bg-muted'
      }`}
      style={{ width: THING.width, height: THING.height }}
    >
      <Centre />
      <BoxIcon className="size-4 shrink-0 text-type-text" aria-hidden />
      <span className="truncate">{data.name}</span>
    </div>
  )
}

function HubBox({ data, selected }: NodeProps<HubNode>) {
  return (
    <div
      className={`flex cursor-pointer items-center justify-center rounded-full border px-3 text-xs font-medium transition-colors ${
        selected ? 'border-ring bg-selected' : 'border-border bg-attr-soft text-attr-text hover:bg-muted'
      }`}
      style={{ width: HUB.width, height: HUB.height }}
    >
      <Centre />
      <span className="truncate">{data.name}</span>
    </div>
  )
}

const NODE_TYPES = { thing: ThingBox, hub: HubBox }
