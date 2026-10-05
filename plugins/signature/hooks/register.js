// Signature's look in Claude Code: every Signature tool call and result is drawn as one kind of card, a mark and a
// headline with quiet detail under it, and an answer as a table the customer reads at a glance. Claude is never
// given an answer's rows, only that it was drawn, so it has nothing to restate or reason from: the proven answer is
// the whole answer. Claude sees Signature's tools from the start. Signature's work in progress shows its stage under
// the prompt, and a build is announced when it ends.

import { toolName, payloadOf, TOOL_PREFIX } from './cards.js'
import { answerCard, answerPane, csvOf } from './answers.js'
import { resultCard, callLine } from './tools.js'
import { atom, read, update } from 'claude-code'
import { BOARD, READ_EVERY_MS, boardFolders, boardOf, endingOf, runningWork } from './activity.js'
import { ACCENT, MARK } from './cards.js'

const PANE = 'signature-answer'
const ASK = TOOL_PREFIX + 'ask_question'
const DRAWN = "Signature has drawn this result for the customer under the call, which overrides the result's note: "
  + 'do not show, restate, point to or comment on it. End your reply here, writing nothing more about it.'
const NO_ANSWER = 'Signature has drawn why it has no answer for the customer under the call, which overrides the '
  + "result's note: do not restate it. Offer, in one sentence, to ask it again more simply."
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

/** The server's build board, or null when no folder it may use holds one. */
async function readBoard($) {
  const [chosen, home, xdg, localAppData] = await Promise.all([
    $.env.get('SIGNATURE_DATA_DIR'), $.env.get('HOME'), $.env.get('XDG_DATA_HOME'), $.env.get('LOCALAPPDATA'),
  ])
  for (const folder of boardFolders({ chosen, home, xdg, localAppData })) {
    const path = `${folder}/${BOARD}`
    if (!(await $.fs.exists(path))) continue
    const [text, stat] = await Promise.all([$.fs.read(path), $.fs.stat(path)])
    return boardOf(text, stat.mtimeMs)
  }
  return null
}

// What Signature is doing for the customer now, drawn above the prompt; null when it is doing nothing.
const working = atom({ plugin: 'signature', key: 'working' }, null)

/** For the rest of the session, keeps the stage of Signature's running work above the prompt and announces a build
 * seen running once it ends, so the customer can look away while Signature works. */
function watchActivity($) {
  $.clock.every(READ_EVERY_MS, async () => {
    const board = await readBoard($)
    const work = runningWork(board, await $.clock.now())
    const wasWorking = (await read($, working)) !== null
    await update($, working, () => work)
    const ending = work === null && wasWorking ? endingOf(board) : null
    if (ending !== null) $.ui.toast(ending, { timeoutMs: 15_000 })
  })
}

/** The band above the prompt: the mark and Signature, each stage it has been through ticked, the one it is in
 * highlighted, and how long it has run. */
function workingBand({ Box, Text }, work) {
  return Box({
    flexDirection: 'row',
    columnGap: 1,
    children: [
      Text({ color: ACCENT, bold: true, children: [MARK] }),
      Text({ bold: true, children: ['Signature'] }),
      ...work.done.map((stage) => Text({ key: stage, dimColor: true, children: [`${stage} ✓ ·`] })),
      Text({ key: 'now', color: ACCENT, children: [`${work.stage}…`] }),
      ...(work.elapsed === null ? [] : [Text({ key: 'elapsed', dimColor: true, children: [work.elapsed] })]),
    ],
  })
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'signature-answer',
      description: "Open Signature's last answer in full: every row, and a copy as CSV",
    })
    watchActivity($)
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
    if (answer.state !== 'answered') return { ...called, context: [...(called.context ?? []), NO_ANSWER] }
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

  // Claude Code folds a run of calls into one line, which would hide what Signature did. A run of Signature's own
  // calls is drawn call by call instead, each with what came of it; a run mixing in other tools keeps Claude Code's
  // line, with each Signature call drawn under it.
  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    const calls = e.props.calls
    const elements = $.ui.resolve(e)
    if (calls.length > 0 && calls.every((call) => toolName(call.tool) !== null)) {
      const results = await Promise.all(calls.map((call) => finishedResult($, call)))
      return elements.Box({ flexDirection: 'column', rowGap: 1, children: calls.map((call, index) => drawnCall(elements, call, results[index], index)) })
    }
    const ours = calls.filter((call) => toolName(call.tool) !== null)
    if (ours.length === 0) return next(e)
    const results = await Promise.all(ours.map((call) => finishedResult($, call)))
    return elements.Box({ flexDirection: 'column', rowGap: 1, children: [await next(e), ...ours.map((call, index) => drawnCall(elements, call, results[index], index))] })
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const work = await read($, working)
    return work === null ? next(e) : workingBand($.ui.resolve(e), work)
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
