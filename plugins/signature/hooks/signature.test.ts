import { expect, mock, test, type Engine, type FoundElement, type ElementQuery } from 'claude-code/testing'
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

test('an answer is drawn as a table alone, under readable headers, its numbers tidy and its rows in order', KEY, async ($, on) => {
  mock.store(on)
  const ui = await $.ui.mount(resultSite('ask_question', structured(ANSWER)))
  expect(await columnsOf(ui, 2)).toEqual([
    { text: 'BookDuneThe HobbitUlysses', alignItems: 'flex-start' },
    { text: 'Average rating4.54.331', alignItems: 'flex-end' },
  ])
  expect(await ui.find({ type: 'Text', text: /the set of rows/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^✓ Proven by Signature · ran on your data · 3 rows$/ })).toBeDefined()
})

test('an answer read from the text of the result is drawn as well', KEY, async ($, on) => {
  mock.store(on)
  const ui = await $.ui.mount(resultSite('ask_question', [{ type: 'text', text: JSON.stringify(ANSWER) }]))
  expect((await columnsOf(ui, 1))[0]?.text).toBe('BookDuneThe HobbitUlysses')
})

test('a single value is drawn on its own, not as a table of one cell', KEY, async ($, on) => {
  mock.store(on)
  const count = { ...ANSWER, question: 'How many books are there?', reading: 'the number of books B', columns: ['int'], rows: [[8]], row_count: 1 }
  const ui = await $.ui.mount(resultSite('ask_question', structured(count)))
  expect(await ui.find({ type: 'Text', text: '8' })).toBeDefined()
  expect(await ui.find({ key: 'column-0' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'Int' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^✓ Proven by Signature · ran on your data$/ })).toBeDefined()
})

test('a question Signature could not prove an answer to says so, and what to do, in the customer’s words', KEY, async ($, on) => {
  mock.store(on)
  const unproven = { ...ANSWER, state: 'unproven', rows: [], columns: [], reading: null, reason: 'the checker refuted it' }
  const ui = await $.ui.mount(resultSite('ask_question', structured(unproven)))
  expect(await ui.find({ type: 'Text', text: "Signature couldn't prove an answer, so nothing ran" })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Asking it more simply, one part at a time, usually works.' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /refuted/ })).toBeUndefined()
  expect(await ui.find({ key: 'column-0' })).toBeUndefined()
})

test('every Signature result shares the look: the mark and a headline', KEY, async ($, on) => {
  mock.store(on)
  const status = { domain: 'Bookshop', published: true, sources: [{ name: 'books', kind: 'file', location: '/x' }], open_questions: [] }
  const ui = await $.ui.mount(resultSite('get_status', structured(status)))
  expect(await ui.find({ type: 'Text', text: '◆' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Bookshop · published' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Data: books' })).toBeDefined()
})

test('a call says what Signature is doing', KEY, async ($, on) => {
  mock.store(on)
  const ui = await $.ui.mount({
    plugin: 'signature', component: 'ToolUse', requestId: 'call-1', surface: 'terminal', viewport: VIEWPORT,
    props: { tool_use_id: 'call-1', tool: signatureTool('ask_question'), input: { question: 'Which books sell best?' }, isRunning: true, isErrored: false, isInterrupted: false },
  })
  expect(await ui.find({ type: 'Text', text: 'asking “Which books sell best?”…' })).toBeDefined()
})

test('a guided setup is drawn as the build it ends in, or as stopped when the customer stops it', KEY, async ($, on) => {
  mock.store(on)
  const built = { state: 'built', reply: 'Built orders and customers.', open_questions: [], note: '' }
  const ended = await $.ui.mount(resultSite('set_up', structured(built)))
  expect(await ended.find({ type: 'Text', text: 'Built your domain' })).toBeDefined()
  const declined = resultSite('set_up', structured({ state: 'declined', note: '' }))
  const stopped = await $.ui.mount({ ...declined, requestId: 'call-2', props: { ...declined.props, tool_use_id: 'call-2' } })
  expect(await stopped.find({ type: 'Text', text: 'Setup stopped' })).toBeDefined()
})

test("another plugin's tools are left as Claude Code draws them", KEY, async ($, on) => {
  mock.store(on)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const ui = await $.ui.mount({ ...resultSite('x', 'hello'), props: { tool_use_id: 'c', tool: 'Bash', isErrored: false, output: {} } })
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
})

test('/signature-answer opens the last answer with every row and copies it as CSV', KEY, async ($, on) => {
  mock.store(on)
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
  expect((await columnsOf(pane, 2))[0]?.text).toBe('BookDuneThe HobbitUlysses')
  expect(await pane.find({ type: 'Text', text: /the set of rows/ })).toBeUndefined()
  await pane.press({ key: 'copy-csv' })
  expect(copied[0]).toBe('book,average_rating\nUlysses,1\nThe Hobbit,4.333333333333333\nDune,4.5')
})

test('a folded run of Signature calls is drawn call by call, the answer under its question', KEY, async ($, on) => {
  mock.store(on)
  const ui = await $.ui.mount(groupSite([call(signatureTool('ask_question'), { question: ANSWER.question }, structured(ANSWER))]))
  expect(await ui.find({ type: 'Text', text: 'asking “What is the average rating of each book?”' })).toBeDefined()
  expect((await columnsOf(ui, 2))[1]?.text).toBe('Average rating4.54.331')
})

test('a folded run that mixes in other tools keeps Claude Code’s line, with each Signature call drawn under it', KEY, async ($, on) => {
  mock.store(on)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const added = structured({ result: [{ source: 'orders', tables: 1, columns: 3 }] })
  const ui = await $.ui.mount(groupSite([call(signatureTool('add_data_files'), { paths: ['/data/orders.csv'] }, added), call('Read', { file_path: 'a' })]))
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Added orders' })).toBeDefined()
})

test('a run that mixes in other tools keeps Claude Code’s line, with its answer drawn under it', KEY, async ($, on) => {
  mock.store(on)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  const ui = await $.ui.mount(groupSite([
    call('Read', { file_path: 'a' }),
    call(signatureTool('ask_question'), { question: ANSWER.question }, JSON.stringify(ANSWER)),
  ]))
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  expect((await columnsOf(ui, 2))[1]?.text).toBe('Average rating4.54.331')
})

test('Claude sees Signature’s tools from the start, not behind a search', KEY, async ($, on) => {
  mock.store(on)
  // The engine lists every MCP tool behind ToolSearch
  on('tool.describe', ($, e) => ({ description: e.description, isDeferred: true }))
  const described = await $.tool.describe({ tool: signatureTool('ask_question'), description: 'Asks Signature', isDeferred: true,
    provider: { plugin: 'mcp:signature', tier: 'user' } })
  expect(described.isDeferred).toBe(false)
})

test('Claude is never given an answer’s rows, and the customer still sees them drawn', KEY, async ($, on) => {
  mock.store(on)
  on('tool.call', () => ({ result: JSON.stringify(ANSWER) }))
  const called = await $.tool.call({ tool: signatureTool('ask_question'), tool_use_id: 'call-1', question: ANSWER.question })
  expect(String(called.result)).not.toContain('Hobbit')
  expect(String(called.result)).toContain('Its rows are not given to you')
  const ui = await $.ui.mount(resultSite('ask_question', called.result))
  expect((await columnsOf(ui, 2))[1]?.text).toBe('Average rating4.54.331')
})

test('Claude is told a status is drawn already, so that it does not show it again', KEY, async ($, on) => {
  mock.store(on)
  on('tool.call', () => ({ result: structured({ domain: 'Bookshop', published: true, sources: [], open_questions: [] }) }))
  const called = await $.tool.call({ tool: signatureTool('get_status'), tool_use_id: 'call-3' })
  expect(called.context?.join('\n')).toContain('writing nothing more about it')
})

test('when there is no answer, Claude is told the reason is drawn, not that an answer was shown', KEY, async ($, on) => {
  mock.store(on)
  const unproven = { ...ANSWER, state: 'unproven', rows: [], columns: [], reading: null, reason: 'timeout' }
  on('tool.call', () => ({ result: JSON.stringify(unproven) }))
  const called = await $.tool.call({ tool: signatureTool('ask_question'), tool_use_id: 'call-4', question: ANSWER.question })
  const context = called.context?.join('\n') ?? ''
  expect(context).toContain('why it has no answer')
  expect(context).not.toContain('drawn this result')
})

test('an answer no longer kept says so rather than drawing nothing', KEY, async ($, on) => {
  mock.store(on)
  const outline = JSON.stringify({ state: 'drawn', question: ANSWER.question, row_count: 3, note: '' })
  const ui = await $.ui.mount({ ...resultSite('ask_question', outline), requestId: 'old', props: { tool_use_id: 'old', tool: signatureTool('ask_question'), output: outline, isErrored: false } })
  expect(await ui.find({ type: 'Text', text: 'This answer is no longer kept' })).toBeDefined()
})

test("Claude reads another tool's result as it is", KEY, async ($, on) => {
  mock.store(on)
  on('tool.call', () => ({ result: 'files' }))
  const called = await $.tool.call({ tool: signatureTool('add_data_files'), tool_use_id: 'call-2', paths: [] })
  expect(called.context ?? []).toHaveLength(0)
})

// The band above the prompt, where the plugin draws what Signature is doing; only the props it reads are given.
const bandSite = {
  plugin: 'signature', component: 'AbovePrompt' as const, requestId: 'band', surface: 'terminal' as const, viewport: VIEWPORT,
  props: { hasSurvey: false, isWorking: true, maxRows: 3, bodyColumns: 120 },
} as unknown as Parameters<Engine['ui']['mount']>[0]

// An interactive session starting in the terminal, which starts the plugin's build watch
const SESSION = { cwd: '/work', surface: 'terminal' as const, isInteractive: true }

/** The server's build board as the hooks find it on disk: a file under SIGNATURE_DATA_DIR, written at `writtenAt`. */
function boardOn(on: Parameters<typeof mock.store>[0], board: { content: unknown; writtenAt: number }) {
  const path = '/plugin-data/activity.json'
  mock.env(on, { SIGNATURE_DATA_DIR: '/plugin-data' })
  on('fs.exists', ($, e) => ({ value: e.path === path }))
  on('fs.read', () => ({ value: JSON.stringify(board.content) }))
  on('fs.stat', () => ({ value: { kind: 'file' as const, size: 1, mtimeMs: board.writtenAt, isLink: false } }))
}

test('running work shows its stage and time above the prompt, and a build is announced once when it ends', KEY, async ($, on) => {
  mock.store(on)
  const start = Date.parse('2026-10-03T08:00:00Z')
  const clock = mock.clock(on, { now: start + 125_000 })
  const board = { content: { state: 'running', stage: 'Checking your model', started_at: '2026-10-03T08:00:00Z', stages: ['Reading sources', 'Checking your model'] } as unknown, writtenAt: start + 124_000 }
  boardOn(on, board)
  const toasts: string[] = []
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['no band'] }))
  on('ui.toast', ($, e) => { toasts.push(e.text); return { value: undefined } })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  await $.session.start(SESSION)
  const band = await $.ui.mount(bandSite)

  await clock.advance(1000)
  expect(await band.find({ type: 'Text', text: 'Reading sources ✓ ·' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: 'Checking your model…' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: '2m 06s' })).toBeDefined()

  board.content = { state: 'questions', ended_at: '2026-10-03T08:02:07Z' }
  await clock.advance(1000)
  await clock.advance(1000)
  expect(await band.find({ type: 'Text', text: /Signature/ })).toBeUndefined()
  expect(toasts).toEqual(['Signature finished building and has questions for you.'])
})

test('a build the server stopped following is not shown, and an old ending is not announced', KEY, async ($, on) => {
  mock.store(on)
  const now = Date.parse('2026-10-03T09:00:00Z')
  const clock = mock.clock(on, { now })
  const board = { content: { state: 'running', stage: 'Updating your model', started_at: null } as unknown, writtenAt: now - 60_000 }
  boardOn(on, board)
  const toasts: string[] = []
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['no band'] }))
  on('ui.toast', ($, e) => { toasts.push(e.text); return { value: undefined } })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  await $.session.start(SESSION)
  const band = await $.ui.mount(bandSite)

  await clock.advance(1000)
  board.content = { state: 'built', ended_at: '2026-10-03T08:59:00Z' }
  await clock.advance(1000)
  expect(await band.find({ type: 'Text', text: /Signature/ })).toBeUndefined()
  expect(toasts).toEqual([])
})

test('a domain not yet started says nothing at the start of a setup, and one with data says where it stands', KEY, async ($, on) => {
  mock.store(on)
  const fresh = await $.ui.mount(resultSite('get_status', structured({ domain: 'Untitled data model', published: false, sources: [], open_questions: [] })))
  expect(await fresh.find({ type: 'Text', text: /Untitled data model/ })).toBeUndefined()
  const started = await $.ui.mount({ ...resultSite('get_status', structured({ domain: 'Fuel', published: false, sources: [{ name: 'orders' }], open_questions: [] })), requestId: 'call-2' })
  expect(await started.find({ type: 'Text', text: 'Fuel · not published yet' })).toBeDefined()
})
