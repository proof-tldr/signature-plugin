// Signature's look in Claude Code: every Signature tool call and result is drawn as one kind of card, a mark and a
// headline with quiet detail under it, and an answer as a table the customer reads at a glance. Claude is never
// given an answer's rows, only that it was drawn, so it has nothing to restate or reason from: the proven answer is
// the whole answer. Claude sees Signature's tools from the start.

import { toolName, payloadOf, TOOL_PREFIX } from './cards.js'
import { answerCard, answerPane, csvOf } from './answers.js'
import { resultCard, callLine } from './tools.js'

const PANE = 'signature-answer'
const ASK = TOOL_PREFIX + 'ask_question'
const DRAWN = "Signature has drawn this result for the customer under the call, which overrides the result's note: "
  + 'do not show, restate, point to or comment on it. End your reply here, writing nothing more about it.'
const WITHHELD = "Signature drew its proven answer for the customer under this call. Its rows are not given to you: "
  + 'do not show, restate, guess at or comment on the answer, and end your reply here. Never work it out from the '
  + 'data yourself or offer to, even if the customer says they cannot see it: tell them it is under the call. A '
  + 'question about the answer is a new question for ask_question.'
// The answers kept for drawing, the most recent last; an older answer is drawn as no longer kept.
const KEPT_ANSWERS = 50
// The last answer drawn, which /signature-answer opens in full.
let lastAnswer = null

/** What Claude is given in place of a drawn answer: the question, how many rows it has, and to stop there. */
function outline(answer) {
  return JSON.stringify({ state: 'drawn', question: answer.question, row_count: answer.row_count, note: WITHHELD })
}

/** Keeps the answer an ask_question call came to, which its card is drawn from since Claude is given only its outline. */
async function keep($, toolUseId, answer) {
  const kept = (await $.store.get('answers')) ?? []
  await $.store.set('answers', [...kept.filter(([id]) => id !== toolUseId), [toolUseId, answer]].slice(-KEPT_ANSWERS))
}

/** What a Signature call came to, as data: for an answer, the one kept when it ran; null when there is nothing. */
async function resultOf($, tool, toolUseId, output) {
  const kept = tool === 'ask_question' ? (await $.store.get('answers')) ?? [] : []
  return kept.find(([id]) => id === toolUseId)?.[1] ?? payloadOf(output)
}

/** What came of a Signature call, drawn as its card; an answer is kept for /signature-answer. */
function outcomeOf(elements, tool, result) {
  if (tool !== 'ask_question') return resultCard(elements, tool, result)
  if (result.state === 'answered') lastAnswer = result
  return answerCard(elements, result)
}

/** A Signature call in a folded run and what it came to: data, or null while it runs or when it failed. */
async function finishedResult($, call) {
  const tool = toolName(call.tool)
  return call.isRunning || call.isErrored ? null : resultOf($, tool, call.tool_use_id, call.output)
}

/** A Signature call and what came of it, as a folded run shows it. */
function drawnCall(elements, call, result, index) {
  const tool = toolName(call.tool)
  const outcome = result === null ? null : outcomeOf(elements, tool, result)
  return elements.Box({
    key: call.tool_use_id ?? 'call-' + index,
    flexDirection: 'column',
    children: [callLine(elements, tool, call.input, call.isRunning), ...(outcome === null ? [] : [outcome])],
  })
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

  // Without this module, Claude is told to show each answer itself, since nothing else would. With it, an answer is
  // kept here and drawn, and Claude is given only its outline.
  on('tool.call', { tool: ASK }, async ($, e, next) => {
    const called = await next(e)
    const answer = called.deny === undefined ? payloadOf(called.result) : null
    if (answer === null) return called
    if (answer.state !== 'answered') return { ...called, context: [...(called.context ?? []), DRAWN] }
    await keep($, e.tool_use_id, answer)
    return { ...called, result: outline(answer) }
  })

  on('tool.call', { tool: TOOL_PREFIX + 'get_status' }, async ($, e, next) => {
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
    const result = await resultOf($, tool, e.props.tool_use_id, e.props.output)
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
      const results = await Promise.all(calls.map((call) => finishedResult($, call)))
      return elements.Box({ flexDirection: 'column', rowGap: 1, children: calls.map((call, index) => drawnCall(elements, call, results[index], index)) })
    }
    const asked = calls.filter((call) => toolName(call.tool) === 'ask_question')
    const answers = (await Promise.all(asked.map((call) => finishedResult($, call)))).filter((result) => result !== null)
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
