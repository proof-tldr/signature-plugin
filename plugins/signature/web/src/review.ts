// What Signature understood about the customer's business, in the words a non-technical reviewer uses: the things
// the business deals in and what is recorded about each, how those things connect, what can be calculated, and
// what Signature will assume is always true. Read from Signature's model snapshot; database vocabulary (tables,
// columns, types) stays out, apart from one plain line on where each thing's information comes from.

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

// One thing Signature keeps track of, named in the reader's words: "Placed on", a date.
export type Detail = { name: string; kind: string; meaning?: string; canBeEmpty: boolean }

export type Thing = {
  id: string
  name: string
  meaning?: string
  tracked: Detail[]
  assumptions: string[]
  from?: string
}

// `label` names the arrow only when the connection's name differs from the thing it points at.
export type Connection = { from: string; to: string; sentence: string; label?: string }

export type Calculation = { id: string; name: string; meaning?: string; conditions: string[] }

export type Understanding = {
  things: Thing[]
  connections: Connection[]
  calculations: Calculation[]
  assumptions: string[]
}

type Entity = NonNullable<Snapshot['entities']>[number]
type Field = NonNullable<Snapshot['fields']>[number]

export function understandingOf(snapshot: Snapshot): Understanding {
  const entities = snapshot.entities ?? []
  const fields = snapshot.fields ?? []
  const byName = new Map(entities.map((entity) => [entity.name, entity]))
  const byId = new Map(entities.map((entity) => [entity.id, entity]))
  const origins = originsOf(snapshot)
  return {
    things: entities.map((entity) => ({
      id: entity.id,
      name: plural(entity),
      meaning: entity.doc,
      tracked: fields.filter((field) => field.entityId === entity.id).map((field) => tracked(field, byName)),
      assumptions: (entity.invariants ?? []).map((invariant) => invariant.english),
      from: origins.get(entity.id),
    })),
    connections: fields.flatMap((field) => {
      const owner = byId.get(field.entityId)
      const target = byName.get(leafName(field.type) ?? '')
      return owner && target && target.id !== owner.id ? [connection(owner, field, target)] : []
    }),
    calculations: (snapshot.functions ?? []).map((fn) => ({
      id: fn.id,
      name: words(fn.name, { capitalised: true }),
      meaning: fn.doc,
      conditions: [...(fn.pre ?? []), ...(fn.post ?? [])].map((condition) => condition.english),
    })),
    assumptions: (snapshot.axioms ?? []).map((axiom) => axiom.english),
  }
}

function tracked(field: Field, things: Map<string, Entity>): Detail {
  return {
    name: words(field.name, { capitalised: true }),
    kind: kindOf(field.type, things),
    meaning: field.doc,
    canBeEmpty: field.type.kind === 'optional',
  }
}

// What kind of value a field holds, as a reader would say it: "Text", "Date", "A customer", "Several products".
const KINDS: Record<string, string> = {
  string: 'Text',
  text: 'Text',
  integer: 'Number',
  'whole number': 'Number',
  real: 'Number',
  number: 'Number',
  boolean: 'Yes or no',
  date: 'Date',
  timestamp: 'Date and time',
  money: 'Money',
}

function kindOf(type: TypeExpression, things: Map<string, Entity>): string {
  switch (type.kind) {
    case 'named': {
      const thing = things.get(type.name)
      if (thing) return words(an(words(thing.name)), { capitalised: true })
      return KINDS[words(type.name)] ?? words(type.name, { capitalised: true })
    }
    case 'optional':
      return kindOf(type.item, things)
    case 'tuple':
      return 'Several values'
    default: {
      const thing = things.get(leafName(type.item) ?? '')
      return thing ? `Several ${words(plural(thing))}` : `Several ${kindOf(type.item, things).toLowerCase()}`
    }
  }
}

function connection(owner: Entity, field: Field, target: Entity): Connection {
  const many = field.type.kind === 'set' || field.type.kind === 'list'
  const amount = many ? 'several' : field.type.kind === 'optional' ? 'at most one' : 'one'
  const targetWords = many ? words(plural(target)) : words(target.name)
  const namedAfterTarget = [words(target.name), words(plural(target))].includes(words(field.name))
  return {
    from: owner.id,
    to: target.id,
    sentence: `Each ${words(owner.name)} has ${amount} ${targetWords}${namedAfterTarget ? '' : `, its ${words(field.name)}`}.`,
    label: namedAfterTarget ? undefined : words(field.name),
  }
}

// Where each thing's information comes from, as "the orders table in your sales database" or "products.csv".
function originsOf(snapshot: Snapshot): Map<string, string> {
  const sources = new Map((snapshot.sources ?? []).map((source) => [source.id, source]))
  const tables = new Map((snapshot.databaseEntities ?? []).map((table) => [table.id, table]))
  const origins = new Map<string, string>()
  for (const mapping of snapshot.mappings ?? []) {
    const table = tables.get(mapping.databaseEntityId)
    const source = table && sources.get(table.sourceId)
    if (!table || !source) continue
    const tableName = table.relation.split('.').at(-1) ?? table.relation
    const place = source.file ?? `the ${words(tableName)} table in your ${source.connection ?? source.namespace ?? ''} database`
    const earlier = origins.get(mapping.entityId)
    origins.set(mapping.entityId, earlier ? `${earlier} and ${place}` : place)
  }
  return origins
}

function plural(entity: Entity): string {
  return entity.plural ?? `${words(entity.name, { capitalised: true })}s`
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

// "OrderLine", "order_line" and "orderLine" all read "order line".
export function words(name: string, { capitalised = false } = {}): string {
  const spaced = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
  return capitalised ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced
}

function an(noun: string): string {
  return /^[aeiou]/.test(noun) ? `an ${noun}` : `a ${noun}`
}

