// What Signature is doing for the customer, a build or a question, as they see it while it runs and when a build
// ends. The server keeps it in activity.json at the top of its folder, rewritten every second while the work runs and
// left holding how it ended. register.js reads that file on a timer; this module says where the file may be and what
// to show from it.

export const BOARD = 'activity.json'
export const READ_EVERY_MS = 1000
// Running work the server has not rewritten for this long is no longer followed: its call ended or the server
// stopped. It is not shown until a call follows it again.
const STALE_AFTER_MS = 10_000
const ENDINGS = {
  built: 'Signature finished building. The review is next.',
  questions: 'Signature finished building and has questions for you.',
  replied: 'Signature replied without building yet.',
  failed: "Signature's build did not finish.",
}

/** The folders the server may keep activity.json in, from the environment: platformdirs' user data folder for
 * 'signature-plugin' on each platform, unless SIGNATURE_DATA_DIR names another. This mirrors settings.py because
 * Claude Code gives hooks no plugin data folder and no channel from the MCP server to say where its folder is. */
export function boardFolders({ chosen, home, xdg, localAppData }) {
  if (chosen) return [chosen]
  return [
    home && `${home}/Library/Application Support/signature-plugin`,
    xdg && `${xdg}/signature-plugin`,
    home && `${home}/.local/share/signature-plugin`,
    localAppData && `${localAppData}/signature-plugin/signature-plugin`,
  ].filter(Boolean)
}

/** The build board in a file's text, with when the file was written, or null when the text is not whole JSON. */
export function boardOf(text, writtenAt) {
  try {
    return { ...JSON.parse(text), writtenAt }
  } catch {
    return null // caught mid-write; the next read sees it whole
  }
}

/** What Signature is doing now, as the band above the prompt shows it: the stages it has been through, the one it is
 * in, and how long it has run when the board says; null when the board shows no work the server is following. */
export function runningWork(board, now) {
  if (board?.state !== 'running' || now - board.writtenAt >= STALE_AFTER_MS) return null
  const stage = board.stage ?? 'Building'
  const started = Date.parse(board.started_at ?? '')
  return {
    done: (board.stages ?? []).filter((label) => label !== stage),
    stage,
    elapsed: Number.isNaN(started) ? null : elapsed(now - started),
  }
}

/** What to tell the customer about how a build ended, or null when the board holds no build's ending. */
export function endingOf(board) {
  return ENDINGS[board?.state] ?? null
}

/** Minutes and seconds, as the status line shows how long the work has run. */
function elapsed(ms) {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
}
