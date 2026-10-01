import {
  Handle,
  MarkerType,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
import { BoxIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { type ConnectionEdge, laidOut, THING, type ThingNode } from './layout'
import type { Understanding } from './review'

type ConnectionsDiagramProps = {
  understanding: Understanding
  selected: string | null
  onSelect: (thingId: string) => void
}

export function ConnectionsDiagram(props: ConnectionsDiagramProps) {
  return (
    <ReactFlowProvider>
      <LaidOutDiagram {...props} />
    </ReactFlowProvider>
  )
}

function LaidOutDiagram({ understanding, selected, onSelect }: ConnectionsDiagramProps) {
  const [layout, setLayout] = useState<{ nodes: ThingNode[]; edges: ConnectionEdge[] } | null>(null)
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
    () => (layout?.nodes ?? []).map((node) => ({ ...node, selected: node.id === selected })),
    [layout, selected],
  )
  const edges = useMemo(
    () =>
      (layout?.edges ?? []).map((edge) => {
        const touches = selected !== null && (edge.source === selected || edge.target === selected)
        const stroke = touches ? 'var(--foreground)' : 'var(--faint)'
        return {
          ...edge,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: stroke },
          style: { stroke, strokeWidth: touches ? 2 : 1.25 },
          labelStyle: { fill: touches ? 'var(--foreground)' : 'var(--muted-foreground)', fontSize: 12 },
          labelBgStyle: { fill: 'var(--band)' },
          labelBgPadding: [4, 2] as [number, number],
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
      onNodeClick={(_, node) => onSelect(node.id)}
      colorMode="light"
      minZoom={0.4}
      maxZoom={1.2}
      proOptions={{ hideAttribution: true }}
      aria-label="How the things in your business connect"
    />
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
      <Handle type="target" position={Position.Left} />
      <BoxIcon className="size-4 shrink-0 text-type-text" aria-hidden />
      <span className="truncate">{data.name}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const NODE_TYPES = { thing: ThingBox }
