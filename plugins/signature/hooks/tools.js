// Every Signature tool's call and result in the house style: a call as one line saying what Signature is doing, and
// its result as a card saying what came of it, in the customer's words rather than the tool's data.

import { card, counted, ACCENT, MARK } from './cards.js'

/** The line a Signature tool call is drawn as: the mark, then what is happening. */
export function callLine({ Box, Text }, tool, input, isRunning) {
  return Box({
    flexDirection: 'row',
    columnGap: 1,
    children: [
      Text({ color: ACCENT, bold: true, children: [MARK] }),
      Text({ children: ['Signature'] }),
      Text({ dimColor: true, wrap: 'truncate-end', children: [doing(tool, input ?? {}) + (isRunning ? '…' : '')] }),
    ],
  })
}

function doing(tool, input) {
  switch (tool) {
    case 'get_status':
      return 'checking where your domain stands'
    case 'add_data_files':
      return `adding ${listed((input.paths ?? []).map(fileName))}`
    case 'connect_database':
      return 'connecting a database'
    case 'remove_source':
      return `removing ${input.name ?? 'a source'}`
    case 'build':
      return 'building your domain'
    case 'answer_questions':
      return `answering ${counted((input.answers ?? []).length, 'question')}`
    case 'wait_for_build':
      return 'waiting for the build'
    case 'review':
      return 'opening the review'
    case 'ask_question':
      return `asking “${input.question ?? ''}”`
    default:
      return tool.replaceAll('_', ' ')
  }
}

/** The card a Signature tool's result is drawn as, or null where the default drawing says it as well. */
export function resultCard(elements, tool, result) {
  switch (tool) {
    case 'get_status':
      return statusCard(elements, result)
    case 'add_data_files':
      return addedCard(elements, Array.isArray(result) ? result : [result])
    case 'connect_database':
      return 'source' in result ? addedCard(elements, [result]) : noticeCard(elements, result)
    case 'remove_source':
      return typeof result === 'string' ? card(elements, result) : null
    case 'build':
    case 'answer_questions':
    case 'wait_for_build':
      return buildCard(elements, result)
    case 'review':
      return reviewCard(elements, result)
    default:
      return null
  }
}

function statusCard(elements, status) {
  const sources = status.sources ?? []
  const questions = status.open_questions ?? []
  return card(elements, `${status.domain} · ${status.published ? 'published' : 'not published yet'}`, [
    sources.length === 0 ? 'No data added yet' : `Data: ${listed(sources.map((source) => source.name))}`,
    ...(questions.length > 0 ? [`Signature is waiting on ${counted(questions.length, 'answer')} from you`] : []),
  ])
}

function addedCard(elements, added) {
  const headline = added.length === 0 ? 'Nothing new to add' : `Added ${listed(added.map((entry) => entry.source))}`
  return card(elements, headline, added.map((entry) =>
    `${entry.source}: ${counted(entry.tables, 'table')}, ${counted(entry.columns, 'column')}`))
}

function buildCard(elements, progress) {
  const questions = progress.open_questions ?? []
  switch (progress.state) {
    case 'built':
      return card(elements, 'Built your domain', progress.reply ? [progress.reply] : [])
    case 'questions':
      return card(elements, `Signature has ${counted(questions.length, 'question')}`,
        questions.map((question) => `${question.number}. ${question.question}`))
    case 'building':
      return card(elements, 'Still building', ['Signature is still working; this picks up where it left off.'])
    case 'failed':
      return card(elements, "The build didn't finish", progress.reply ? [progress.reply] : [], 'error')
    default:
      return null
  }
}

function reviewCard(elements, reviewed) {
  switch (reviewed.state) {
    case 'published':
      return card(elements, 'Published', [readiness(reviewed.note ?? '')])
    case 'changes_requested':
      return card(elements, 'Changes sent', ['Signature is rebuilding with what you asked for.'])
    default:
      return noticeCard(elements, reviewed)
  }
}

function readiness(note) {
  if (note.includes('could not get ready')) return note.split('. Tell the customer')[0]
  if (note.includes('still getting ready')) return 'Signature is still getting ready to answer; a question asked now waits for it.'
  return 'Ready for your questions.'
}

function noticeCard(elements, result) {
  if (result.state === 'waiting') return card(elements, 'Waiting for you in the browser')
  if (result.state === 'declined') return card(elements, 'The page was not opened')
  return null
}

function fileName(path) {
  return String(path).split('/').filter(Boolean).pop() ?? String(path)
}

/** Names as a sentence lists them: `a`, `a and b`, `a, b and c`. */
function listed(names) {
  if (names.length <= 1) return names[0] ?? 'nothing'
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}
