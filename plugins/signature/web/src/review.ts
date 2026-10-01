// What Signature understood about the customer's business, laid out the way business experts validate a model
// (fact-oriented modelling, as in Object-Role Modeling): the things the business deals in, each relationship as one
// fact read from every side it has rather than from whichever side the model happens to store it, facts tying three
// or more things together read as one sentence, the calculations, and the rules. Real examples from the customer's
// own data, found on their machine, sit beside each so they judge cases rather than abstractions. Database vocabulary
// stays out, apart from one plain line on where each thing's records come from.

type TypeExpression =
  | { kind: 'named'; name: string }
  | { kind: 'optional' | 'set' | 'list'; item: TypeExpression }
  | { kind: 'tuple'; items: TypeExpression[] }

type Statement = { id: string; english: string }

export type Snapshot = {
  entities?: { id: string; name: string; plural?: string; doc?: string; invariants?: Statement[] }[]
  fields?: { id: string; entityId: string; name: string; type: TypeExpression; doc?: string }[]
  functions?: {
    id: string
    name: string
    doc?: string
    parameters?: { name: string; type: TypeExpression }[]
    pre?: Statement[]
    post?: Statement[]
  }[]
  axioms?: Statement[]
  sources?: { id: string; kind?: string; connection?: string; namespace?: string; file?: string }[]
  databaseEntities?: { id: string; sourceId: string; relation: string }[]
  mappings?: { id: string; entityId: string; databaseEntityId: string }[]
}

// Real cases the plugin found in the customer's data: a few records of each thing, and a few pairs for each
// relationship, keyed by the thing's or the relationship's field id.
export type Examples = { things?: Record<string, string[]>; links?: Record<string, [string, string][]> }

export type Detail = { name: string; holds: string; meaning?: string; canBeEmpty: boolean }

export type Thing = {
  id: string
  name: string
  meaning?: string
  details: Detail[]
  rules: string[]
  from?: string
  examples: string[]
}

// One fact relating things, with a sentence for each side it can be read from, the things it involves (the
// diagram joins them), and real cases of it.
export type Fact = {
  id: string
  // A pair is drawn as a line between two things; a joining or relating fact as a hub joined to each of its things.
  kind: 'pair' | 'joining' | 'relating'
  title: string
  readings: string[]
  members: string[]
  meaning?: string
  examples: string[]
}

export type Calculation = { id: string; name: string; meaning?: string; conditions: string[] }

export type Understanding = {
  things: Thing[]
  facts: Fact[]
  calculations: Calculation[]
  rules: string[]
}

type Entity = NonNullable<Snapshot['entities']>[number]
type Field = NonNullable<Snapshot['fields']>[number]
type Fn = NonNullable<Snapshot['functions']>[number]

export function understandingOf(snapshot: Snapshot, examples: Examples = {}): Understanding {
  const entities = snapshot.entities ?? []
  const fields = snapshot.fields ?? []
  const byName = new Map(entities.map((entity) => [entity.name, entity]))
  const links = fields.filter((field) => targetOf(field.type, byName))
  const joining = new Set(entities.filter((entity) => joinsOthers(entity, links, byName)).map((entity) => entity.id))
  const origins = originsOf(snapshot)
  const functions = snapshot.functions ?? []
  const relating = functions.filter((fn) => entityParameters(fn, byName).length >= 2)

  return {
    things: entities
      .filter((entity) => !joining.has(entity.id))
      .map((entity) => ({
        id: entity.id,
        name: plural(entity),
        meaning: entity.doc,
        details: fields
          .filter((field) => field.entityId === entity.id && !targetOf(field.type, byName))
          .map((field) => detail(field)),
        rules: (entity.invariants ?? []).map((invariant) => invariant.english),
        from: origins.get(entity.id),
        examples: examples.things?.[entity.id] ?? [],
      })),
    facts: [
      ...links
        .filter((field) => !joining.has(field.entityId))
        .map((field) => pairFact(field, entityOf(field.entityId, entities), targetOf(field.type, byName)!, examples)),
      ...entities.filter((entity) => joining.has(entity.id)).map((entity) => joiningFact(entity, fields, byName, examples)),
      ...relating.map((fn) => relatingFact(fn, byName)),
    ],
    calculations: functions
      .filter((fn) => !relating.includes(fn))
      .map((fn) => ({
        id: fn.id,
        name: words(fn.name, { capitalised: true }),
        meaning: fn.doc,
        conditions: [...(fn.pre ?? []), ...(fn.post ?? [])].map((condition) => condition.english),
      })),
    rules: (snapshot.axioms ?? []).map((axiom) => axiom.english),
  }
}

// A relationship stored as a field on one thing, read from both sides. The stored side's count comes from the
// field; nothing in the model limits the other side, so it reads "any number, including none", which is exactly
// what Signature will assume and so what the reviewer must confirm. A thing related to itself reads once.
function pairFact(field: Field, owner: Entity, target: Entity, examples: Examples): Fact {
  const many = field.type.kind === 'set' || field.type.kind === 'list'
  const count = many ? 'can have any number of' : field.type.kind === 'optional' ? 'has at most one' : 'has exactly one'
  const role = words(field.name)
  const named = [words(target.name), words(plural(target))].includes(role)
  const targetWords = many ? words(plural(target)) : words(target.name)
  const asRole = named ? targetWords : `${role} (${many ? words(plural(target)) : an(words(target.name))})`
  const forward = `Each ${words(owner.name)} ${count} ${asRole}.`
  const reverse = named
    ? `${capitalise(an(words(target.name)))} can have any number of ${words(plural(owner))}, including none.`
    : `${capitalise(an(words(target.name)))} can be the ${role} of any number of ${words(plural(owner))}, including none.`
  return {
    id: field.id,
    kind: 'pair',
    title: `${plural(owner)} and ${plural(target)}`,
    readings: owner.id === target.id ? [forward] : [forward, reverse],
    members: owner.id === target.id ? [owner.id] : [owner.id, target.id],
    meaning: field.doc,
    examples: (examples.links?.[field.id] ?? []).map(([from, to]) => `${from}: ${role} ${to}`),
  }
}

// A thing whose records exist to tie two or more other things together, as an order line ties an order to a
// product: shown as the fact it stands for, with its own details as part of the sentence.
function joiningFact(entity: Entity, fields: Field[], things: Map<string, Entity>, examples: Examples): Fact {
  const own = fields.filter((field) => field.entityId === entity.id)
  const members = own.flatMap((field) => targetOf(field.type, things) ?? [])
  const extras = own.filter((field) => !targetOf(field.type, things)).map((field) => words(field.name))
  const tied = members.map((member) => an(words(member.name)))
  return {
    id: entity.id,
    kind: 'joining',
    title: plural(entity),
    readings: [`Each ${words(entity.name)} ties together ${list(tied)}${extras.length ? `, with its ${list(extras)}` : ''}.`],
    members: members.map((member) => member.id),
    meaning: entity.doc,
    examples: examples.things?.[entity.id] ?? [],
  }
}

// A fact over three or more things at once, held as a function of them (the price a supplier charges for a
// product at a warehouse). It is one sentence; splitting it into pairs would lose what it says.
function relatingFact(fn: Fn, things: Map<string, Entity>): Fact {
  const members = entityParameters(fn, things)
  return {
    id: fn.id,
    kind: 'relating',
    title: words(fn.name, { capitalised: true }),
    readings: [`${words(fn.name, { capitalised: true })} depends on ${list(members.map((member) => an(words(member.name))))} together.`],
    members: members.map((member) => member.id),
    meaning: fn.doc,
    examples: [],
  }
}

function detail(field: Field): Detail {
  return {
    name: words(field.name, { capitalised: true }),
    holds: KINDS[words(leafName(field.type) ?? '')] ?? words(leafName(field.type) ?? 'value', { capitalised: true }),
    meaning: field.doc,
    canBeEmpty: field.type.kind === 'optional',
  }
}

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

function joinsOthers(entity: Entity, links: Field[], things: Map<string, Entity>): boolean {
  const own = links.filter((field) => field.entityId === entity.id && field.type.kind === 'named')
  const others = new Set(own.map((field) => targetOf(field.type, things)?.id))
  const pointedAt = links.some((field) => targetOf(field.type, things)?.id === entity.id)
  return others.size >= 2 && !pointedAt
}

function entityParameters(fn: Fn, things: Map<string, Entity>): Entity[] {
  return (fn.parameters ?? []).flatMap((parameter) => targetOf(parameter.type, things) ?? [])
}

function targetOf(type: TypeExpression, things: Map<string, Entity>): Entity | undefined {
  return things.get(leafName(type) ?? '')
}

function entityOf(id: string, entities: Entity[]): Entity {
  return entities.find((entity) => entity.id === id)!
}

// Where each thing's records come from, as "the orders table in your sales database" or "products.csv".
function originsOf(snapshot: Snapshot): Map<string, string> {
  const sources = new Map((snapshot.sources ?? []).map((source) => [source.id, source]))
  const tables = new Map((snapshot.databaseEntities ?? []).map((table) => [table.id, table]))
  const origins = new Map<string, string>()
  for (const mapping of snapshot.mappings ?? []) {
    const table = tables.get(mapping.databaseEntityId)
    const source = table && sources.get(table.sourceId)
    if (!table || !source) continue
    const tableName = table.relation.split('.').at(-1) ?? table.relation
    const place = source.file || `the ${words(tableName)} table in your ${source.connection ?? source.namespace ?? ''} database`
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
  return capitalised ? capitalise(spaced) : spaced
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function an(noun: string): string {
  return /^[aeiou]/.test(noun) ? `an ${noun}` : `a ${noun}`
}

function list(items: string[]): string {
  return items.length <= 1 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}
