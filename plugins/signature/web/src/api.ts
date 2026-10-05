// The plugin's local server: the page's data, and where the customer's decision goes. Every page lives at its
// own private address, and its data and decision sit beside it.
import type { Examples, Snapshot } from './review'

export type PageData =
  | { page: 'review'; domain: string; snapshot: Snapshot; examples?: Examples }
  | { page: 'connect'; suggestedName: string | null }

export type Outcome = { done: true } | { error: string }

const address = window.location.pathname.replace(/\/$/, '')

export async function loadPage(): Promise<PageData> {
  if (import.meta.env.DEV) return (await import('./sample')).samplePage(new URLSearchParams(window.location.search))
  const response = await fetch(`${address}/data`)
  if (!response.ok) throw new Error('This page has expired. Ask Claude to open it again.')
  return response.json()
}

export async function submit(decision: Record<string, string>): Promise<Outcome> {
  if (import.meta.env.DEV) return { done: true }
  const response = await fetch(`${address}/decision`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(decision),
  })
  if (response.ok) return { done: true }
  if (response.status === 422) return response.json()
  return { error: 'This page has expired. Ask Claude to open it again.' }
}
