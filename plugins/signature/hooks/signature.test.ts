import { expect, test, type FoundElement, type ElementQuery } from 'claude-code/testing'
import type { ToolGroupCall } from 'claude-code'

const TOOL = 'mcp__plugin_signature_signature__'
// The plugin's userConfig, which a load requires
const KEY = { options: { api_key: 'test-key' } }
const VIEWPORT = { columns: 120, rows: 40 }

const ANSWER = {
  state: 'answered',
  question: 'What is the average rating of each book?',
  reading: 'the set of rows, one per book B, each holding:\n  • B\n  • the average of the rating of R over every review R such that:\n      – the book of R is B\n      – the rating of R is not none',
  columns: ['book', 'average_rating'],
  rows: [['Ulysses', 1], ['The Hobbit', 4.333333333333333], ['Dune', 4.5]],
  row_count: 3,
  truncated: false,
  reason: null,
  note: 'Show the customer this answer.',
}

/** A Signature tool's name as Claude sees it. */
const signatureTool = (name: string): `mcp__${string}__${string}` => `${TOOL}${name}`

/** An MCP result carrying the value as its structured content. */
const structured = (value: unknown) => ({ content: [], isError: false, structuredContent: value })

/** The ToolResult site of a Signature call that answered with the output. */
const resultSite = (tool: string, output: unknown) => ({
  plugin: 'signature', component: 'ToolResult' as const, requestId: 'call-1', surface: 'terminal' as const, viewport: VIEWPORT,
  props: { tool_use_id: 'call-1', tool: signatureTool(tool), output, isErrored: false },
})

/** The ToolGroup site of a folded run of calls. */
const groupSite = (calls: ToolGroupCall[]) => ({
  plugin: 'signature', component: 'ToolGroup' as const, requestId: 'group-1', surface: 'terminal' as const, viewport: VIEWPORT,
  props: { calls, isActive: false, isExpanded: false },
})

/** A finished call in a folded run. */
const call = (tool: string, input: unknown, output?: unknown): ToolGroupCall =>
  ({ tool_use_id: tool, tool, input, isRunning: false, isErrored: false, isInterrupted: false, output })

/** A drawn answer table's columns, each as the texts it shows from the top (its header, then its cells), and how it aligns them. */
async function columnsOf(ui: { findAll: (query: ElementQuery) => Promise<FoundElement[]> }, count: number) {
  return Promise.all(Array.from({ length: count }, async (_, index) => {
    const [column] = await ui.findAll({ key: `column-${index}` })
    return { text: column?.text ?? '', alignItems: column?.props.alignItems }
  }))
}

test('an answer is drawn as a table under readable headers, its numbers tidy and its rows in order', KEY, async ($, on) => {
  const ui = await $.ui.mount(resultSite('ask_question', structured(ANSWER)))
  expect(await columnsOf(ui, 2)).toEqual([
    { text: 'BookDuneThe HobbitUlysses', alignItems: 'flex-start' },
    { text: 'Average rating4.54.331', alignItems: 'flex-end' },
  ])
  expect(await ui.find({ type: 'Text', text: /^the set of rows, one per book B/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^✓ Proven by Signature · ran on your data · 3 rows/ })).toBeDefined()
})

test('an answer read from the text of the result is drawn as well', KEY, async ($, on) => {
  const ui = await $.ui.mount(resultSite('ask_question', [{ type: 'text', text: JSON.stringify(ANSWER) }]))
  expect((await columnsOf(ui, 1))[0]?.text).toBe('BookDuneThe HobbitUlysses')
})

test('a single value is drawn on its own, not as a table of one cell', KEY, async ($, on) => {
  const count = { ...ANSWER, question: 'How many books are there?', reading: 'the number of books B', columns: ['int'], rows: [[8]], row_count: 1 }
  const ui = await $.ui.mount(resultSite('ask_question', structured(count)))
  expect(await ui.find({ type: 'Text', text: '8' })).toBeDefined()
  expect(await ui.find({ key: 'column-0' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'Int' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^✓ Proven by Signature · ran on your data$/ })).toBeDefined()
})

test('a question Signature could not prove an answer to says so, and what to do, in the customer’s words', KEY, async ($, on) => {
  const unproven = { ...ANSWER, state: 'unproven', rows: [], columns: [], reading: null, reason: 'the checker refuted it' }
  const ui = await $.ui.mount(resultSite('ask_question', structured(unproven)))
  expect(await ui.find({ type: 'Text', text: "Signature couldn't prove an answer, so nothing ran" })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Asking it more simply, one part at a time, usually works.' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /refuted/ })).toBeUndefined()
  expect(await ui.find({ key: 'column-0' })).toBeUndefined()
})

test('every Signature result shares the look: the mark and a headline', KEY, async ($, on) => {
  const status = { domain: 'Bookshop', published: true, sources: [{ name: 'books', kind: 'file', location: '/x' }], open_questions: [] }
  const ui = await $.ui.mount(resultSite('get_status', structured(status)))
  expect(await ui.find({ type: 'Text', text: '◆' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Bookshop · published' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Data: books' })).toBeDefined()
})

test('a call says what Signature is doing', KEY, async ($, on) => {
  const ui = await $.ui.mount({
    plugin: 'signature', component: 'ToolUse', requestId: 'call-1', surface: 'terminal', viewport: VIEWPORT,
    props: { tool_use_id: 'call-1', tool: signatureTool('ask_question'), input: { question: 'Which books sell best?' }, isRunning: true, isErrored: false, isInterrupted: false },
  })
  expect(await ui.find({ type: 'Text', text: 'asking “Which books sell best?”…' })).toBeDefined()
})

test("another plugin's tools are left as Claude Code draws them", KEY, async ($, on) => {
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const ui = await $.ui.mount({ ...resultSite('x', 'hello'), props: { tool_use_id: 'c', tool: 'Bash', isErrored: false, output: {} } })
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
})

test('/signature-answer opens the last answer with every row and copies it as CSV', KEY, async ($, on) => {
  on('ui.open', () => ({ value: { isPlaced: true } }))
  const copied: string[] = []
  on('ui.copy', ($, e) => {
    copied.push(e.text)
    return { value: { isCopied: true } }
  })
  on('ui.toast', () => ({ value: undefined }))
  await $.ui.mount(resultSite('ask_question', structured(ANSWER)))
  await $.command.run({
    command: 'signature-answer', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 120 },
  })
  const pane = await $.ui.mount({
    plugin: 'signature', component: 'Pane', requestId: 'signature-answer', surface: 'terminal', viewport: VIEWPORT,
    props: { title: 'Signature answer', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  })
  expect(await pane.find({ type: 'Text', text: /^Signature read it as: the set of rows/ })).toBeDefined()
  await pane.press({ key: 'copy-csv' })
  expect(copied[0]).toBe('book,average_rating\nUlysses,1\nThe Hobbit,4.333333333333333\nDune,4.5')
})

test('a folded run of Signature calls is drawn call by call, the answer under its question', KEY, async ($, on) => {
  const ui = await $.ui.mount(groupSite([call(signatureTool('ask_question'), { question: ANSWER.question }, structured(ANSWER))]))
  expect(await ui.find({ type: 'Text', text: 'asking “What is the average rating of each book?”' })).toBeDefined()
  expect((await columnsOf(ui, 2))[1]?.text).toBe('Average rating4.54.331')
})

test('a folded run that mixes in other tools is left as Claude Code draws it', KEY, async ($, on) => {
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const ui = await $.ui.mount(groupSite([call(signatureTool('get_status'), {}), call('Read', { file_path: 'a' })]))
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
})

test('a run that mixes in other tools keeps Claude Code’s line, with its answer drawn under it', KEY, async ($, on) => {
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const ui = await $.ui.mount(groupSite([
    call('Read', { file_path: 'a' }),
    call(signatureTool('ask_question'), { question: ANSWER.question }, JSON.stringify(ANSWER)),
  ]))
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  expect((await columnsOf(ui, 2))[1]?.text).toBe('Average rating4.54.331')
})

test('Claude sees Signature’s tools from the start, not behind a search', KEY, async ($, on) => {
  // The engine lists every MCP tool behind ToolSearch
  on('tool.describe', ($, e) => ({ description: e.description, isDeferred: true }))
  const described = await $.tool.describe({ tool: signatureTool('ask_question'), description: 'Asks Signature', isDeferred: true,
    provider: { plugin: 'mcp:signature', tier: 'user' } })
  expect(described.isDeferred).toBe(false)
})

test('Claude is told an answer is drawn already, so that it does not show it again', KEY, async ($, on) => {
  on('tool.call', () => ({ result: structured(ANSWER) }))
  const called = await $.tool.call({ tool: signatureTool('ask_question'), tool_use_id: 'call-1', question: ANSWER.question })
  expect(called.context?.join('\n')).toContain('drawn this result for the customer')
})

test("Claude reads another tool's result as it is", KEY, async ($, on) => {
  on('tool.call', () => ({ result: 'files' }))
  const called = await $.tool.call({ tool: signatureTool('add_data_files'), tool_use_id: 'call-2', paths: [] })
  expect(called.context ?? []).toHaveLength(0)
})
