// Signature's look in Claude Code: every Signature tool call and result is drawn as one kind of card, a mark and a
// headline with quiet detail under it, and an answer as a table the customer reads at a glance. Claude is told
// what is drawn, so that it does not show it again, and sees the tool that asks Signature from the start.

import { toolName, payloadOf, TOOL_PREFIX } from './cards.js'
import { answerCard, answerPane, csvOf } from './answers.js'
import { resultCard, callLine } from './tools.js'

const PANE = 'signature-answer'
const DRAWN = "Signature has drawn this result for the customer under the call, which overrides the result's note: "
  + 'do not show, restate or point to it. Reply with one sentence on what stands out, or what they can do next.'
// The last answer drawn, which /signature-answer opens in full.
let lastAnswer = null

/** What came of a Signature call, drawn as its card; an answer is kept for /signature-answer. */
function outcomeOf(elements, tool, result) {
  if (tool !== 'ask_question') return resultCard(elements, tool, result)
  if (result.state === 'answered') lastAnswer = result
  return answerCard(elements, result)
}

/** A Signature call and what came of it, as a folded run shows it. */
function drawnCall(elements, call, index) {
  const tool = toolName(call.tool)
  const result = resultOf(call)
  const outcome = result === null ? null : outcomeOf(elements, tool, result)
  return elements.Box({
    key: call.tool_use_id ?? 'call-' + index,
    flexDirection: 'column',
    children: [callLine(elements, tool, call.input, call.isRunning), ...(outcome === null ? [] : [outcome])],
  })
}

/** What a finished call in a folded run came to, as data; null while it runs or when it failed. */
function resultOf(call) {
  return call.isRunning || call.isErrored ? null : payloadOf(call.output)
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'signature-answer',
      description: "Open Signature's last answer in full: how it read the question, every row, and a copy as CSV",
    })
    return next(e)
  })

  on('command.run', { command: 'signature-answer' }, async ($) => {
    if (lastAnswer === null) return { text: 'Signature has not answered a question in this session yet.' }
    await $.ui.open({ id: PANE, title: 'Signature answer', focus: true, closeOnEscape: true })
    return {}
  })

  // Claude is told to show the customer each answer and status itself, since without this module nothing would;
  // with it, they are drawn under the call already, and Claude is told so where it reads the result.
  on('tool.call', { tool: new RegExp(`^${TOOL_PREFIX}(ask_question|get_status)$`) }, async ($, e, next) => {
    const called = await next(e)
    return called.deny === undefined ? { ...called, context: [...(called.context ?? []), DRAWN] } : called
  })

  // Claude sees Signature's few tools from the start rather than finding them behind a search: asking Signature is
  // how the customer's data questions are answered, and a tool behind a search loses to reading the files directly.
  on('tool.describe', { tool: new RegExp(`^${TOOL_PREFIX}`) }, async ($, e, next) => ({ ...(await next(e)), isDeferred: false }))

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const tool = toolName(e.props.tool)
    if (tool === null) return next(e)
    return callLine($.ui.resolve(e), tool, e.props.input, e.props.isRunning)
  })

  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    const tool = toolName(e.props.tool)
    if (tool === null || e.props.isErrored) return next(e)
    const result = payloadOf(e.props.output)
    if (result === null) return next(e)
    return outcomeOf($.ui.resolve(e), tool, result) ?? next(e)
  })

  // Claude Code folds a run of calls into one line, which would hide an answer. A run of Signature's own calls is
  // drawn call by call instead, each with what came of it; any other run keeps Claude Code's line, with the answers
  // it holds drawn under it.
  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    const calls = e.props.calls
    const elements = $.ui.resolve(e)
    if (calls.length > 0 && calls.every((call) => toolName(call.tool) !== null)) {
      return elements.Box({ flexDirection: 'column', rowGap: 1, children: calls.map((call, index) => drawnCall(elements, call, index)) })
    }
    const answers = calls.filter((call) => toolName(call.tool) === 'ask_question').map(resultOf)
      .filter((result) => result !== null)
    if (answers.length === 0) return next(e)
    return elements.Box({ flexDirection: 'column', rowGap: 1, children: [await next(e), ...answers.map((result) => outcomeOf(elements, 'ask_question', result))] })
  })

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE || lastAnswer === null) return next(e)
    const answer = lastAnswer
    return answerPane($.ui.resolve(e), answer, async () => {
      await $.ui.copy({ text: csvOf(answer) })
      await $.ui.toast('Copied the answer as CSV')
    })
  })
}
