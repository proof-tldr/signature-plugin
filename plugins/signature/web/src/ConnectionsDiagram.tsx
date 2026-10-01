import {
  Handle,
  MarkerType,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
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
        const stroke = touches ? 'var(--signature)' : 'var(--muted)'
        return {
          ...edge,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: stroke },
          style: { stroke, strokeWidth: touches ? 2 : 1.25 },
          labelStyle: { fill: touches ? 'var(--signature)' : 'var(--muted)', fontSize: 13 },
          labelBgStyle: { fill: 'var(--canvas)' },
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
      className={`flex cursor-pointer items-center justify-center rounded-md border px-3 font-serif text-[17px] transition-colors ${
        selected ? 'border-signature bg-signature-wash' : 'border-ink/60 bg-paper hover:border-signature'
      }`}
      style={{ width: THING.width, height: THING.height }}
    >
      <Handle type="target" position={Position.Left} />
      <span className="truncate">{data.name}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const NODE_TYPES = { thing: ThingBox }
