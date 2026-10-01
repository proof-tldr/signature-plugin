// Places the diagram of how the customer's things connect: one box per thing, an arrow per connection, laid out
// left to right by ELK so that arrows cross as little as possible.
import type { Edge, Node } from '@xyflow/react'

import type { Understanding } from './review'

export const THING = { width: 150, height: 44 }

export type ThingNode = Node<{ name: string }, 'thing'>
export type ConnectionEdge = Edge

export async function laidOut(understanding: Understanding): Promise<{ nodes: ThingNode[]; edges: ConnectionEdge[] }> {
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js')
  const edges = understanding.connections.map((connection, index) => ({
    id: `connection-${index}`,
    source: connection.from,
    target: connection.to,
    label: connection.label,
  }))
  const placed = await new ELK().layout({
    id: 'connections',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.layered.spacing.nodeNodeBetweenLayers': '56',
      'elk.spacing.nodeNode': '28',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.separateConnectedComponents': 'false',
    },
    children: understanding.things.map((thing) => ({ id: thing.id, ...THING })),
    edges: edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  })
  const nodes = understanding.things.map((thing): ThingNode => {
    const spot = placed.children?.find((child) => child.id === thing.id)
    return { id: thing.id, type: 'thing', position: { x: spot?.x ?? 0, y: spot?.y ?? 0 }, data: { name: thing.name } }
  })
  return { nodes, edges }
}
