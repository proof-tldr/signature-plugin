// The one look every Signature card shares: a mark in the accent colour and a bold headline, with quiet detail
// lines under it. Elements come from the site being drawn ($.ui.resolve), so a card is drawn alike in the terminal
// and the Desktop app.

export const MARK = '◆'
export const ACCENT = '#7C8CF8'
export const TOOL_PREFIX = 'mcp__plugin_signature_signature__'

/** The Signature tool a call names, or null for anyone else's tool. */
export function toolName(tool) {
  return typeof tool === 'string' && tool.startsWith(TOOL_PREFIX) ? tool.slice(TOOL_PREFIX.length) : null
}

/** A Signature tool's result as data: its structured result, or the JSON its text holds; null when it has neither. */
export function payloadOf(output) {
  const structured = output?.structuredContent ?? null
  if (structured !== null && typeof structured === 'object') return unwrapped(structured)
  const blocks = Array.isArray(output) ? output : Array.isArray(output?.content) ? output.content : []
  const text = blocks.find((block) => block?.type === 'text')?.text ?? (typeof output === 'string' ? output : null)
  if (text === null) return null
  try {
    return unwrapped(JSON.parse(text))
  } catch {
    return null
  }
}

// A tool whose result is not an object, such as a list, is wrapped as { result }.
function unwrapped(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 1
    && 'result' in value ? value.result : value
}

/** A card: the mark, a bold headline, then each detail on its own quiet line. `tone` colours the headline. */
export function card({ Box, Text }, headline, details = [], tone = undefined) {
  return Box({
    flexDirection: 'column',
    children: [
      Box({
        flexDirection: 'row',
        columnGap: 1,
        children: [
          Text({ color: ACCENT, bold: true, children: [MARK] }),
          Text({ bold: true, color: tone, wrap: 'wrap', children: [headline] }),
        ],
      }),
      ...details.map((detail) => line({ Text, Box }, detail)),
    ],
  })
}

/** One quiet line under a card's headline, indented past the mark. */
export function line({ Box, Text }, text) {
  return Box({ paddingLeft: 2, children: [Text({ dimColor: true, wrap: 'wrap', children: [text] })] })
}

/** A count with its noun, `1 table`, `3 columns`. */
export function counted(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}
