// The values Signature's hooks keep for the session.

/** What Signature is doing now: the stages it has been through, the one it is in, and how long it has run when known. */
export type Work = { done: string[]; stage: string; elapsed: string | null }

declare module 'claude-code' {
  interface PluginState {
    signature: { working: Work | null }
  }
}
