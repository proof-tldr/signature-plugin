import { useEffect, useMemo, useRef, useState } from 'react'

import { submit } from './api'
import { Notice } from './App'
import { SourceMap } from './SourceMap'
import { type Concept, type Measure, reviewOf, type Snapshot } from './review'

type ReviewPageProps = { domain: string; snapshot: Snapshot }

export function ReviewPage({ domain, snapshot }: ReviewPageProps) {
  const review = useMemo(() => reviewOf(snapshot), [snapshot])
  const [selected, setSelected] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<'published' | 'changes' | null>(null)
  const names = useMemo(() => new Map(review.concepts.map((concept) => [concept.id, concept.name])), [review])

  const flag = (subject: string) =>
    setNote((current) => {
      const opening = `${subject}: `
      if (current?.includes(opening)) return current
      return current ? `${current.trimEnd()}\n${opening}` : opening
    })

  const decide = async (decision: 'publish' | 'change') => {
    setSending(true)
    const outcome = await submit({ decision, changes: note ?? '' })
    setSending(false)
    if ('error' in outcome) setError(outcome.error)
    else setDecided(decision === 'publish' ? 'published' : 'changes')
  }

  if (decided === 'published')
    return <Notice title={`${domain} is published`} body="Go back to Claude to ask Signature your questions." />
  if (decided === 'changes')
    return <Notice title="Your changes are with Signature" body="Go back to Claude. It will show you the review again once they are in." />

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-line bg-paper px-4 py-3 sm:gap-4 sm:px-5">
        <p className="hidden text-sm font-semibold text-muted sm:block" translate="no">
          Signature
        </p>
        <p className="min-w-0 flex-1 truncate font-serif text-lg">{domain}</p>
        <button
          type="button"
          onClick={() => setNote((current) => current ?? '')}
          className="hidden rounded-md border border-line px-4 py-2 text-sm font-medium hover:border-ink/40 sm:block"
        >
          Something is wrong
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={() => decide('publish')}
          className="rounded-md bg-signature px-4 py-2 text-sm font-semibold text-signature-ink hover:brightness-110 disabled:opacity-60"
        >
          Publish
        </button>
      </header>
      {error && note === null ? (
        <p role="alert" className="border-b border-line bg-flag-wash px-5 py-2.5 text-sm text-flag">
          {error}
        </p>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[45vh_minmax(0,1fr)] lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:grid-rows-1">
        <section className="min-h-0 border-b border-line lg:border-r lg:border-b-0" aria-label="Where your data goes">
          <SourceMap review={review} selected={selected} onSelect={setSelected} />
        </section>

        <article className="min-h-0 overflow-y-auto">
          <div className="mx-auto max-w-[44rem] px-4 pt-10 pb-24 sm:px-6 lg:px-12 lg:pt-12">
            <h1 className="font-serif text-[2rem] leading-[1.1] tracking-tight text-balance sm:text-[2.5rem]">{domain}</h1>
            <p className="mt-4 max-w-[38rem] text-lg leading-relaxed text-muted">
              This is how Signature understood your data and documents. Pick a concept on the map to see where its
              data comes from. Flag anything that is wrong, and publish when it is right.
            </p>

            <Part title="What Signature knows about">
              {review.concepts.map((concept) => (
                <ConceptEntry
                  key={concept.id}
                  concept={concept}
                  names={names}
                  selected={selected === concept.id}
                  onSelect={setSelected}
                  onFlag={flag}
                />
              ))}
            </Part>

            {review.measures.length > 0 ? (
              <Part title="What it can calculate">
                {review.measures.map((measure) => (
                  <MeasureEntry key={measure.id} measure={measure} onFlag={flag} />
                ))}
              </Part>
            ) : null}

            {review.rules.length > 0 ? (
              <Part title="What always holds">
                {review.rules.map((rule) => (
                  <div key={rule} className="group border-t border-line py-4">
                    <p className="font-serif text-[1.15rem] leading-relaxed">{rule}</p>
                    <FlagButton subject={rule} onFlag={flag} />
                  </div>
                ))}
              </Part>
            ) : null}
          </div>
        </article>
      </div>

      {note !== null ? (
        <ChangeNote
          note={note}
          error={error}
          sending={sending}
          onChange={setNote}
          onSend={() => decide('change')}
          onClose={() => {
            setNote(null)
            setError(null)
          }}
        />
      ) : null}
    </div>
  )
}

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-16">
      <h2 className="mb-2 text-[15px] font-semibold text-muted">{title}</h2>
      {children}
    </section>
  )
}

type ConceptEntryProps = {
  concept: Concept
  names: Map<string, string>
  selected: boolean
  onSelect: (id: string) => void
  onFlag: (subject: string) => void
}

function ConceptEntry({ concept, names, selected, onSelect, onFlag }: ConceptEntryProps) {
  const entry = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!selected) return
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    entry.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
  }, [selected])

  return (
    <div
      ref={entry}
      className={`group scroll-mt-6 border-t py-6 transition-colors ${selected ? 'border-signature' : 'border-line'}`}
    >
      <h3 className="font-serif text-[1.6rem] leading-tight text-balance break-words">
        <button
          type="button"
          onClick={() => onSelect(concept.id)}
          aria-pressed={selected}
          className={`text-left ${selected ? 'text-signature' : 'hover:text-signature'}`}
        >
          {concept.name}
        </button>
      </h3>
      {concept.meaning ? <p className="mt-2 font-serif text-[1.15rem] leading-relaxed">{concept.meaning}</p> : null}
      {concept.readFrom.length > 0 ? (
        <p className="mt-2 text-sm text-muted">Read from {concept.readFrom.join(' and ')}</p>
      ) : null}
      {concept.fields.length > 0 ? (
        <dl className="mt-5 grid grid-cols-[minmax(7rem,max-content)_minmax(0,1fr)] gap-x-6 gap-y-2 text-[15px]">
          {concept.fields.map((field) => (
            <div key={field.name} className="contents">
              <dt className="font-medium break-words">{field.name}</dt>
              <dd className="break-words text-muted">
                {field.linksTo ? (
                  <button type="button" onClick={() => onSelect(field.linksTo!)} className="text-signature hover:underline">
                    {names.get(field.linksTo) ?? field.holds}
                  </button>
                ) : (
                  <span className="text-ink">{field.holds}</span>
                )}
                {field.meaning ? `. ${field.meaning}` : null}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {concept.rules.map((rule) => (
        <p key={rule} className="mt-4 border-l-2 border-ink pl-3.5 font-serif text-[1.05rem] leading-relaxed">
          {rule}
        </p>
      ))}
      <FlagButton subject={concept.name} onFlag={onFlag} />
    </div>
  )
}

function MeasureEntry({ measure, onFlag }: { measure: Measure; onFlag: (subject: string) => void }) {
  return (
    <div className="group border-t border-line py-6">
      <h3 className="font-serif text-[1.6rem] leading-tight text-balance break-words">{measure.name}</h3>
      {measure.meaning ? <p className="mt-2 font-serif text-[1.15rem] leading-relaxed">{measure.meaning}</p> : null}
      {measure.conditions.map((condition) => (
        <p key={condition} className="mt-4 border-l-2 border-ink pl-3.5 font-serif text-[1.05rem] leading-relaxed">
          {condition}
        </p>
      ))}
      <FlagButton subject={measure.name} onFlag={onFlag} />
    </div>
  )
}

function FlagButton({ subject, onFlag }: { subject: string; onFlag: (subject: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onFlag(subject)}
      className="mt-4 text-sm text-muted underline-offset-4 opacity-100 hover:text-flag hover:underline focus-visible:opacity-100 lg:opacity-0 lg:group-hover:opacity-100"
    >
      This is wrong
    </button>
  )
}

type ChangeNoteProps = {
  note: string
  error: string | null
  sending: boolean
  onChange: (note: string) => void
  onSend: () => void
  onClose: () => void
}

function ChangeNote({ note, error, sending, onChange, onSend, onClose }: ChangeNoteProps) {
  const field = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const area = field.current
    if (!area) return
    area.focus()
    area.setSelectionRange(area.value.length, area.value.length)
  }, [note.split('\n').length])

  return (
    <aside
      onKeyDown={(event) => event.key === 'Escape' && onClose()}
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper shadow-[0_-12px_32px_-24px_rgb(0_0_0/0.35)] lg:inset-x-auto lg:top-[57px] lg:right-0 lg:w-[26rem] lg:border-t-0 lg:border-l"
      aria-label="What should change"
    >
      <div className="flex h-full flex-col p-6">
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-2xl">What should change?</h2>
          <button type="button" onClick={onClose} className="text-sm text-muted hover:text-ink">
            Close
          </button>
        </div>
        <p className="mt-2 text-sm text-muted">Signature reads this and fixes the domain, then you review it again.</p>
        <textarea
          ref={field}
          value={note}
          onChange={(event) => onChange(event.target.value)}
          placeholder="For example: a refunded order should not count as revenue…"
          className="mt-4 min-h-40 flex-1 resize-none overscroll-contain rounded-md border border-line bg-paper p-3 font-serif text-[1.05rem] leading-relaxed lg:min-h-0"
        />
        {error ? (
          <p role="alert" className="mt-3 rounded-md bg-flag-wash px-3 py-2 text-sm text-flag">
            {error}
          </p>
        ) : null}
        <button
          type="button"
          disabled={sending || note.trim() === ''}
          onClick={onSend}
          className="mt-4 rounded-md bg-ink px-4 py-2.5 text-sm font-semibold text-paper hover:bg-ink/85 disabled:opacity-40"
        >
          Send changes
        </button>
      </div>
    </aside>
  )
}
