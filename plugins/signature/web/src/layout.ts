// Places the diagram of how the customer's things relate, without implying a direction or a hierarchy: an
// undirected stress layout, a plain line for a fact between two things, and a small hub joined to every thing in
// a fact that ties several together.
import type { Edge, Node } from '@xyflow/react'

import type { Understanding } from './review'

export const THING = { width: 150, height: 40 }
export const HUB = { width: 132, height: 30 }

export type ThingNode = Node<{ name: string }, 'thing'>
export type HubNode = Node<{ name: string }, 'hub'>
export type DiagramNode = ThingNode | HubNode

export async function laidOut(understanding: Understanding): Promise<{ nodes: DiagramNode[]; edges: Edge[] }> {
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js')
  const hubs = understanding.facts.filter((fact) => fact.kind !== 'pair')
  const pairs = understanding.facts.filter((fact) => fact.kind === 'pair' && fact.members.length === 2)
  const edges: Edge[] = [
    ...pairs.map((fact) => ({ id: fact.id, source: fact.members[0]!, target: fact.members[1]!, data: { fact: fact.id } })),
    ...hubs.flatMap((fact) =>
      fact.members.map((member, index) => ({
        id: `${fact.id}-${index}`,
        source: `hub-${fact.id}`,
        target: member,
        data: { fact: fact.id },
      })),
    ),
  ]
  const placed = await new ELK().layout({
    id: 'relations',
    layoutOptions: { 'elk.algorithm': 'stress', 'elk.stress.desiredEdgeLength': '110' },
    children: [
      ...understanding.things.map((thing) => ({ id: thing.id, ...THING })),
      ...hubs.map((fact) => ({ id: `hub-${fact.id}`, ...HUB })),
    ],
    edges: edges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  })
  const positions = apart(placed.children ?? [])
  const at = (id: string) => positions.get(id) ?? { x: 0, y: 0 }
  return {
    nodes: [
      ...understanding.things.map((thing): ThingNode => ({
        id: thing.id,
        type: 'thing',
        position: at(thing.id),
        data: { name: thing.name },
      })),
      ...hubs.map((fact): HubNode => ({
        id: `hub-${fact.id}`,
        type: 'hub',
        position: at(`hub-${fact.id}`),
        data: { name: fact.title },
      })),
    ],
    edges,
  }
}

const GAP = 18

// The stress layout places centres and ignores the boxes' size, so boxes that land on each other are pushed apart
// along whichever axis needs the smaller move, until none overlap.
function apart(boxes: { id: string; x?: number; y?: number; width?: number; height?: number }[]) {
  const placed = boxes.map((box) => ({ id: box.id, x: box.x ?? 0, y: box.y ?? 0, w: box.width ?? 0, h: box.height ?? 0 }))
  for (let round = 0; round < 50; round += 1) {
    let moved = false
    for (const [index, a] of placed.entries()) {
      for (const b of placed.slice(index + 1)) {
        const overlapX = Math.min(a.x + a.w, b.x + b.w) + GAP - Math.max(a.x, b.x)
        const overlapY = Math.min(a.y + a.h, b.y + b.h) + GAP - Math.max(a.y, b.y)
        if (overlapX <= 0 || overlapY <= 0) continue
        moved = true
        if (overlapX < overlapY) {
          const shift = (overlapX / 2) * (a.x <= b.x ? 1 : -1)
          a.x -= shift
          b.x += shift
        } else {
          const shift = (overlapY / 2) * (a.y <= b.y ? 1 : -1)
          a.y -= shift
          b.y += shift
        }
      }
    }
    if (!moved) break
  }
  return new Map(placed.map((box) => [box.id, { x: box.x, y: box.y }]))
}
