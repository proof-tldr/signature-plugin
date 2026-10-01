import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  type EdgeProps,
  Handle,
  MarkerType,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'

import { CONCEPT, laidOut, type MapEdge, type MapNode, TABLE } from './layout'
import type { Review } from './review'

type SourceMapProps = {
  review: Review
  selected: string | null
  onSelect: (conceptId: string | null) => void
}

export function SourceMap(props: SourceMapProps) {
  return (
    <ReactFlowProvider>
      <LaidOutMap {...props} />
    </ReactFlowProvider>
  )
}

function LaidOutMap({ review, selected, onSelect }: SourceMapProps) {
  const [layout, setLayout] = useState<{ nodes: MapNode[]; edges: MapEdge[] } | null>(null)
  const { fitView } = useReactFlow()

  useEffect(() => {
    let current = true
    laidOut(review).then((placed) => {
      if (current) setLayout(placed)
    })
    return () => {
      current = false
    }
  }, [review])

  useEffect(() => {
    if (layout) requestAnimationFrame(() => fitView({ padding: 0.12 }))
  }, [layout, fitView])

  const selectedTables = useMemo(() => {
    const tables = new Set<string>()
    for (const reading of review.readings) if (reading.concept === selected) tables.add(reading.table)
    return tables
  }, [review, selected])

  const nodes = useMemo(
    () =>
      (layout?.nodes ?? []).map((node) => ({
        ...node,
        selected: node.id === selected,
        className: selected && !lit(node, selected, selectedTables) ? 'opacity-35' : undefined,
      })),
    [layout, selected, selectedTables],
  )
  const edges = useMemo(
    () =>
      (layout?.edges ?? []).map((edge) => {
        const touches = edge.source === selected || edge.target === selected
        const link = edge.data?.kind === 'link'
        const stroke = link || (selected && touches) ? 'var(--signature)' : 'var(--muted)'
        return {
          ...edge,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: stroke },
          style: {
            stroke,
            strokeWidth: selected && touches ? 2 : 1.25,
            strokeDasharray: link ? '5 4' : undefined,
            opacity: selected && !touches ? 0.25 : 1,
          },
        }
      }),
    [layout, selected],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      onNodeClick={(_, node) => node.type === 'concept' && onSelect(node.id === selected ? null : node.id)}
      onPaneClick={() => onSelect(null)}
      colorMode="system"
      minZoom={0.3}
      maxZoom={1.25}
      proOptions={{ hideAttribution: true }}
      aria-label="Map of where each concept's data comes from"
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--line)" />
      <Controls showInteractive={false} position="bottom-left" />
    </ReactFlow>
  )
}

function lit(node: MapNode, selected: string, tables: Set<string>): boolean {
  if (node.type === 'concept') return node.id === selected
  if (node.type === 'table') return tables.has(node.id)
  return true // a source box stays lit; its tables carry the emphasis
}

function SourceNode({ data }: NodeProps<Extract<MapNode, { type: 'source' }>>) {
  return (
    <div className="h-full w-full rounded-lg border border-line bg-paper/70">
      <div className="flex items-baseline justify-between px-3 pt-2.5">
        <span className="text-[13px] font-semibold text-ink">{data.name}</span>
        {data.kind ? <span className="text-xs text-muted">{data.kind}</span> : null}
      </div>
    </div>
  )
}

function TableNode({ data }: NodeProps<Extract<MapNode, { type: 'table' }>>) {
  return (
    <div
      className="flex items-center truncate rounded-md bg-canvas px-2.5 text-[13px] text-ink"
      style={{ width: TABLE.width, height: TABLE.height }}
      title={data.name}
    >
      {data.name}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function ConceptNode({ data, selected }: NodeProps<Extract<MapNode, { type: 'concept' }>>) {
  return (
    <div
      className={`flex cursor-pointer items-center rounded-md border px-3.5 font-serif text-[17px] transition-colors ${
        selected ? 'border-signature bg-signature-wash text-ink' : 'border-ink/70 bg-paper text-ink hover:border-signature'
      }`}
      style={{ width: CONCEPT.width, height: CONCEPT.height }}
    >
      <Handle type="target" id="read-in" position={Position.Left} />
      <span className="truncate">{data.name}</span>
      <Handle type="source" id="link-out" position={Position.Right} />
      <Handle type="target" id="link-in" position={Position.Right} />
    </div>
  )
}

// A field linking one concept to another: a curve out to the right of both concepts and back, reaching further out
// the longer it spans, so nested links never overlap.
function LinkEdge({ sourceX, sourceY, targetX, targetY, label, style, markerEnd, data }: EdgeProps<MapEdge>) {
  const reach = data?.kind === 'link' ? data.reach : 40
  const out = Math.max(sourceX, targetX) + reach
  const path = `M${sourceX},${sourceY} C${out},${sourceY} ${out},${targetY} ${targetX},${targetY}`
  return (
    <>
      <BaseEdge path={path} style={style} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <span
          className="nodrag nopan pointer-events-none absolute bg-canvas px-1 text-xs"
          style={{
            color: style?.stroke,
            opacity: style?.opacity,
            transform: `translate(-50%, -50%) translate(${sourceX + reach * 0.75}px, ${(sourceY + targetY) / 2}px)`,
          }}
        >
          {label}
        </span>
      </EdgeLabelRenderer>
    </>
  )
}

function ReachNode() {
  return <div className="h-px w-px" aria-hidden />
}

const NODE_TYPES = { source: SourceNode, table: TableNode, concept: ConceptNode, reach: ReachNode }
const EDGE_TYPES = { link: LinkEdge }
