// An answer as the customer reads it: their question, how Signature read it, and the rows the proven query found on
// their data, as a table with readable headers and tidy numbers. The transcript shows the first rows; the
// /signature-answer pane shows every row and the full reading.

import { card, line, ACCENT, MARK, counted } from './cards.js'

const INLINE_ROWS = 12
const READING_LINES = 3
// The widest a text cell is drawn, so that one long value cannot push the other columns off the screen.
const CELL_WIDTH = 40

/** What is drawn under an ask_question call, whose line already shows the question: the answer, or why there is none. */
export function answerCard(elements, answer) {
  switch (answer.state) {
    case 'answered':
      return answeredCard(elements, answer)
    case 'unanswerable':
      return card(elements, "Signature can't answer this from your domain", [answer.reason ?? ''], 'warning')
    case 'unproven':
      // The reason is the checker's own words, for Claude; the customer is told what to do about it.
      return card(elements, "Signature couldn't prove an answer, so nothing ran", ['Asking it more simply, one part at a time, usually works.'], 'warning')
    case 'stale':
      return card(elements, 'Your data changed shape since the domain was published', ['Build and publish it again to ask about it.'], 'warning')
    default:
      return card(elements, 'Signature has no answer', [answer.reason ?? ''])
  }
}

function answeredCard(elements, answer) {
  const { Box } = elements
  const reading = readingLines(answer.reading)
  const shown = sortedRows(answer.rows).slice(0, INLINE_ROWS)
  const more = answer.row_count - shown.length
  return Box({
    flexDirection: 'column',
    children: [
      ...reading.slice(0, READING_LINES).map((text) => line(elements, text)),
      ...(reading.length > READING_LINES ? [line(elements, '…')] : []),
      Box({ paddingLeft: 2, paddingY: 1, children: [answerBody(elements, answer, shown)] }),
      line(elements, footer(answer, more)),
    ],
  })
}

/** Whether the answer is one value, such as a count, rather than rows. */
function isSingleValue(answer) {
  return answer.row_count === 1 && answer.columns.length === 1
}

/** The answer's rows as it shows them: a single value on its own, any other result as a table. */
function answerBody(elements, answer, rows) {
  if (rows.length === 0) return elements.Text({ dimColor: true, children: ['No rows match.'] })
  if (isSingleValue(answer)) return elements.Text({ bold: true, children: [cellText(rows[0][0])] })
  return tableOf(elements, answer.columns, rows)
}

/** The line under every answer: that it was proven and ran on the customer's data, and how many rows it has. */
function provenLine(answer) {
  return ['✓ Proven by Signature', 'ran on your data', ...(isSingleValue(answer) ? [] : [counted(answer.row_count, 'row')])].join(' · ')
}

/** The proven line under an answer in the transcript, pointing to the pane when the card leaves something out. */
function footer(answer, more) {
  const isCut = more > 0 || readingLines(answer.reading).length > READING_LINES
  return provenLine(answer) + (isCut ? ' · /signature-answer for all of it' : '')
}

/** The pane /signature-answer opens: the full reading, every row, and a button that copies them as CSV. */
export function answerPane(elements, answer, copy) {
  const { Box, Text, Button } = elements
  const rows = sortedRows(answer.rows)
  return Box({
    flexDirection: 'column',
    rowGap: 1,
    children: [
      Box({
        flexDirection: 'row',
        columnGap: 1,
        children: [Text({ color: ACCENT, bold: true, children: [MARK] }), Text({ bold: true, wrap: 'wrap', children: [answer.question] })],
      }),
      Text({ dimColor: true, wrap: 'wrap', children: [answer.reading ? `Signature read it as: ${answer.reading}` : ''] }),
      answerBody(elements, answer, rows),
      Text({ dimColor: true, children: [footerOfPane(answer)] }),
      Button({ key: 'copy-csv', label: 'Copy as CSV', hotkey: 'c', plain: true, onPress: copy }),
    ],
  })
}

function footerOfPane(answer) {
  const cut = answer.truncated ? ` · the first ${counted(answer.rows.length, 'row')} of a longer result` : ''
  return provenLine(answer) + cut
}

/** The answer's rows as CSV, under its headers, values as they are. */
export function csvOf(answer) {
  const field = (value) => {
    const text = value === null || value === undefined ? '' : String(value)
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
  }
  return [answer.columns, ...answer.rows].map((row) => row.map(field).join(',')).join('\n')
}

// ---- reading, rows and cells ---------------------------------------------------------------------------------

/** The reading's lines, without the bullets and blank lines signature-english sets it out with. */
function readingLines(reading) {
  if (!reading) return []
  return reading.split('\n').map((text) => text.trimEnd()).filter((text) => text.trim() !== '')
}

/** The rows in a stable order a person can scan: by the first column, then the next. */
function sortedRows(rows) {
  return [...rows].sort((left, right) => {
    for (let index = 0; index < left.length; index += 1) {
      const order = compared(left[index], right[index])
      if (order !== 0) return order
    }
    return 0
  })
}

function compared(left, right) {
  if (left === right) return 0
  if (left === null || left === undefined) return 1
  if (right === null || right === undefined) return -1
  if (typeof left === 'number' && typeof right === 'number') return left - right
  return String(left).localeCompare(String(right))
}

/** The rows as a table, one column of cells under each header: text aligned left, numbers right. */
function tableOf({ Box, Text }, columns, rows) {
  return Box({
    flexDirection: 'row',
    columnGap: 3,
    children: columns.map((name, index) => {
      const numeric = rows.some((row) => typeof row[index] === 'number')
        && rows.every((row) => row[index] === null || typeof row[index] === 'number')
      return Box({
        key: `column-${index}`,
        flexDirection: 'column',
        alignItems: numeric ? 'flex-end' : 'flex-start',
        children: [
          Text({ key: 'heading', bold: true, children: [heading(name)] }),
          ...rows.map((row, at) => Text({ key: `row-${at}`, wrap: 'truncate-end', children: [cellText(row[index])] })),
        ],
      })
    }),
  })
}

/** A column name as words: `average_rating` reads `Average rating`, `c0` reads `Value`. */
function heading(name) {
  if (/^c\d+$/.test(name)) return 'Value'
  const words = String(name).replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').trim().toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** A value as the table shows it: whole numbers grouped by thousands, others to two places, absence as a dash. */
function cellText(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString('en-US')
      : value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }
  const text = String(value).replaceAll('\n', ' ')
  return text.length > CELL_WIDTH ? text.slice(0, CELL_WIDTH - 1) + '…' : text
}
