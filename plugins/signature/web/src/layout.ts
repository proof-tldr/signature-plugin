// Places the map: each source as a box holding its tables in one column, every concept in a second column, ordered
// by ELK so the lines from tables to concepts cross as little as possible. Links between concepts are drawn as
// curves on the concepts' right and play no part in the layout, so they never stretch the map sideways.
import type { Edge, Node } from '@xyflow/react'
import type { ElkNode } from 'elkjs/lib/elk-api'

import type { Review } from './review'

export const TABLE = { width: 220, height: 32 }
export const CONCEPT = { width: 190, height: 46 }
const SOURCE_HEADER = 40
const SOURCE_PADDING = 12
const LINK_REACH = 34
const LINK_NEST = 22

export type SourceData = { name: string; kind?: string }
export type TableData = { name: string }
export type ConceptData = { name: string }
export type MapNode =
  | Node<SourceData, 'source'>
  | Node<TableData, 'table'>
  | Node<ConceptData, 'concept'>
  | Node<Record<string, never>, 'reach'>
export type MapEdge = Edge<{ kind: 'reading' } | { kind: 'link'; reach: number }>

export async function laidOut(review: Review): Promise<{ nodes: MapNode[]; edges: MapEdge[] }> {
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js')
  const readings: MapEdge[] = review.readings.map((reading) => ({
    id: `reading-${reading.table}-${reading.concept}`,
    source: reading.table,
    target: reading.concept,
    targetHandle: 'read-in',
    data: { kind: 'reading' as const },
  }))
  const placed = await new ELK().layout(graph(review, readings))
  const centre = (id: string) => {
    const spot = placed.children?.find((child) => child.id === id)
    return (spot?.y ?? 0) + CONCEPT.height / 2
  }
  const links = review.links
    .map((link, index) => ({ link, index, span: Math.abs(centre(link.from) - centre(link.to)) }))
    .sort((a, b) => a.span - b.span)
    .map(({ link, index }, rank) => ({
      id: `link-${index}`,
      type: 'link',
      source: link.from,
      target: link.to,
      label: link.label,
      sourceHandle: 'link-out',
      targetHandle: 'link-in',
      data: { kind: 'link' as const, reach: LINK_REACH + LINK_NEST * rank },
    }))
  const nodes = placedNodes(review, placed)
  return { nodes: [...nodes, ...reachOf(nodes, links)], edges: [...readings, ...links] }
}

// An invisible point as far right as the outermost link and its label reach, so fitting the map to the view keeps
// the links, which are drawn outside every concept, in sight.
function reachOf(nodes: MapNode[], links: MapEdge[]): MapNode[] {
  const outermost = Math.max(0, ...links.map((link) => (link.data?.kind === 'link' ? link.data.reach : 0)))
  if (outermost === 0) return []
  const concepts = nodes.filter((node) => node.type === 'concept')
  const right = Math.max(...concepts.map((node) => node.position.x)) + CONCEPT.width
  const top = Math.min(...concepts.map((node) => node.position.y))
  const position = { x: right + outermost + 48, y: top }
  return [{ id: 'reach', type: 'reach', position, data: {}, selectable: false, width: 1, height: 1 }]
}

function graph(review: Review, readings: MapEdge[]): ElkNode {
  return {
    id: 'map',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
      'elk.spacing.nodeNode': '22',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.partitioning.activate': 'true',
    },
    children: [
      ...review.sources.map((source) => ({
        id: `source-${source.id}`,
        layoutOptions: {
          'elk.partitioning.partition': '0',
          'elk.padding': `[top=${SOURCE_HEADER},left=${SOURCE_PADDING},bottom=${SOURCE_PADDING},right=${SOURCE_PADDING}]`,
          'elk.spacing.nodeNode': '6',
        },
        children: source.tables.map((table) => ({ id: table.id, ...TABLE })),
      })),
      ...review.concepts.map((concept) => ({
        id: concept.id,
        layoutOptions: { 'elk.partitioning.partition': '1' },
        ...CONCEPT,
      })),
    ],
    edges: readings.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  }
}

function placedNodes(review: Review, placed: ElkNode): MapNode[] {
  const nodes: MapNode[] = []
  for (const source of review.sources) {
    const box = placed.children?.find((child) => child.id === `source-${source.id}`)
    nodes.push({
      id: `source-${source.id}`,
      type: 'source',
      position: { x: box?.x ?? 0, y: box?.y ?? 0 },
      data: { name: source.name, kind: source.kind },
      style: { width: box?.width, height: box?.height },
      selectable: false,
    })
    for (const table of source.tables) {
      const spot = box?.children?.find((child) => child.id === table.id)
      nodes.push({
        id: table.id,
        type: 'table',
        parentId: `source-${source.id}`,
        extent: 'parent',
        position: { x: spot?.x ?? 0, y: spot?.y ?? 0 },
        data: { name: table.name },
        selectable: false,
      })
    }
  }
  for (const concept of review.concepts) {
    const spot = placed.children?.find((child) => child.id === concept.id)
    nodes.push({
      id: concept.id,
      type: 'concept',
      position: { x: spot?.x ?? 0, y: spot?.y ?? 0 },
      data: { name: concept.name },
    })
  }
  return nodes
}
