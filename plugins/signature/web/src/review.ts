// The domain as the customer reviews it, read from Signature's model snapshot: its concepts and what they
// record, the measures it can compute, the rules that always hold, and where each concept's data comes from.

type TypeExpression =
  | { kind: 'named'; name: string }
  | { kind: 'optional' | 'set' | 'list'; item: TypeExpression }
  | { kind: 'tuple'; items: TypeExpression[] }

type Statement = { id: string; english: string }

export type Snapshot = {
  entities?: { id: string; name: string; plural?: string; doc?: string; invariants?: Statement[] }[]
  fields?: { id: string; entityId: string; name: string; type: TypeExpression; doc?: string }[]
  functions?: { id: string; name: string; doc?: string; pre?: Statement[]; post?: Statement[] }[]
  axioms?: Statement[]
  sources?: { id: string; kind?: string; connection?: string; namespace?: string; file?: string }[]
  databaseEntities?: { id: string; sourceId: string; relation: string }[]
  mappings?: { id: string; entityId: string; databaseEntityId: string }[]
}

export type Field = { name: string; holds: string; meaning?: string; linksTo?: string }

export type Concept = {
  id: string
  name: string
  meaning?: string
  fields: Field[]
  rules: string[]
  readFrom: string[]
}

export type Measure = { id: string; name: string; meaning?: string; conditions: string[] }

export type Source = { id: string; name: string; kind?: string; tables: { id: string; name: string }[] }

export type Link = { from: string; to: string; label: string }

export type Review = {
  concepts: Concept[]
  measures: Measure[]
  rules: string[]
  sources: Source[]
  readings: { table: string; concept: string }[]
  links: Link[]
}

export function reviewOf(snapshot: Snapshot): Review {
  const entities = snapshot.entities ?? []
  const fields = snapshot.fields ?? []
  const mappings = snapshot.mappings ?? []
  const tables = snapshot.databaseEntities ?? []
  const tableNames = new Map(tables.map((table) => [table.id, table.relation]))
  const sources = (snapshot.sources ?? []).map((source) => ({
    id: source.id,
    name: source.connection ?? source.namespace ?? source.file ?? source.id,
    kind: source.kind,
    tables: withoutSharedSchema(tables.filter((table) => table.sourceId === source.id)),
  }))
  const placeOf = new Map(
    sources.flatMap((source) => source.tables.map((table) => [table.id, `${table.name} in ${source.name}`] as const)),
  )
  const conceptIds = new Map(entities.map((entity) => [entity.name, entity.id]))
  const linkTarget = (type: TypeExpression) => conceptIds.get(leafName(type) ?? '')

  return {
    concepts: entities.map((entity) => ({
      id: entity.id,
      name: entity.plural ?? entity.name,
      meaning: entity.doc,
      fields: fields
        .filter((field) => field.entityId === entity.id)
        .map((field) => ({ name: field.name, holds: typeName(field.type), meaning: field.doc, linksTo: linkTarget(field.type) })),
      rules: (entity.invariants ?? []).map((invariant) => invariant.english),
      readFrom: mappings
        .filter((mapping) => mapping.entityId === entity.id)
        .flatMap((mapping) => placeOf.get(mapping.databaseEntityId) ?? []),
    })),
    measures: (snapshot.functions ?? []).map((fn) => ({
      id: fn.id,
      name: fn.name,
      meaning: fn.doc,
      conditions: [...(fn.pre ?? []), ...(fn.post ?? [])].map((condition) => condition.english),
    })),
    rules: (snapshot.axioms ?? []).map((axiom) => axiom.english),
    sources,
    readings: mappings
      .filter((mapping) => tableNames.has(mapping.databaseEntityId))
      .map((mapping) => ({ table: mapping.databaseEntityId, concept: mapping.entityId })),
    links: fields.flatMap((field) => {
      const target = linkTarget(field.type)
      return target && target !== field.entityId ? [{ from: field.entityId, to: target, label: field.name }] : []
    }),
  }
}

// Table names without the schema every table in the source shares, as in "orders" for "public.orders".
function withoutSharedSchema(tables: { id: string; relation: string }[]): { id: string; name: string }[] {
  const schemas = new Set(tables.map((table) => (table.relation.includes('.') ? table.relation.split('.')[0] : '')))
  const [shared] = schemas
  const strip = schemas.size === 1 && shared ? `${shared}.` : ''
  return tables.map((table) => ({ id: table.id, name: table.relation.slice(strip.length) }))
}

function leafName(type: TypeExpression): string | undefined {
  switch (type.kind) {
    case 'named':
      return type.name
    case 'tuple':
      return undefined
    default:
      return leafName(type.item)
  }
}

function typeName(type: TypeExpression): string {
  switch (type.kind) {
    case 'named':
      return type.name
    case 'optional':
      return `${typeName(type.item)}, if known`
    case 'tuple':
      return type.items.map(typeName).join(' and ')
    default:
      return `several ${typeName(type.item)}`
  }
}
