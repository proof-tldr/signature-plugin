import { useEffect, useMemo, useRef, useState } from 'react'

import { submit } from './api'
import { Notice } from './App'
import { ConnectionsDiagram } from './ConnectionsDiagram'
import { type Snapshot, type Thing, type Understanding, understandingOf } from './review'

type ReviewPageProps = { domain: string; snapshot: Snapshot }
type Verdict = 'right' | 'wrong'
type Item = { key: string; subject: string }

const CONNECTIONS: Item = { key: 'connections', subject: 'How my business fits together' }

export function ReviewPage({ domain, snapshot }: ReviewPageProps) {
  const understanding = useMemo(() => understandingOf(snapshot), [snapshot])
  const items = useMemo(() => itemsOf(understanding), [understanding])
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<'published' | 'changes' | null>(null)

  const judge = (item: Item, verdict: Verdict) => {
    setVerdicts((current) => ({ ...current, [item.key]: verdict }))
    if (verdict === 'wrong')
      setNote((current) => {
        const opening = `${item.subject}: `
        if (current?.includes(opening)) return current
        return current ? `${current.trimEnd()}\n${opening}` : opening
      })
  }

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
    return (
      <Notice
        title="Signature is fixing what you flagged"
        body="Go back to Claude. It will bring you back here to check again once the changes are in."
      />
    )

  const checked = items.filter((item) => verdicts[item.key] === 'right').length
  const flagged = items.filter((item) => verdicts[item.key] === 'wrong').length
  const judgeItem = (item: Item) => (verdict: Verdict) => judge(item, verdict)

  return (
    <div className="min-h-full pb-28">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[46rem] items-center gap-3 px-5 py-3">
          <p className="text-sm font-semibold text-muted" translate="no">
            Signature
          </p>
          <p className="min-w-0 truncate font-serif text-lg">{domain}</p>
        </div>
      </header>

      <main className="mx-auto max-w-[46rem] px-5 pt-12">
        <h1 className="font-serif text-[2.1rem] leading-tight text-balance sm:text-[2.5rem]">
          Check what Signature understood about {domain}
        </h1>

        {understanding.connections.length > 0 ? (
          <Part
            title="How your business fits together"
          >
            <div className="mt-2 h-64 overflow-hidden rounded-lg bg-canvas">
              <ConnectionsDiagram understanding={understanding} selected={selected} onSelect={setSelected} />
            </div>
            <ul className="mt-6 space-y-2 font-serif text-[1.15rem] leading-relaxed">
              {understanding.connections.map((connection) => (
                <li key={connection.sentence}>{connection.sentence}</li>
              ))}
            </ul>
            <Verdicts verdict={verdicts[CONNECTIONS.key]} onJudge={judgeItem(CONNECTIONS)} />
          </Part>
        ) : null}

        <Part title="Each thing in detail">
          {understanding.things.map((thing) => (
            <ThingEntry
              key={thing.id}
              thing={thing}
              selected={selected === thing.id}
              verdict={verdicts[thing.id]}
              onJudge={judgeItem({ key: thing.id, subject: thing.name })}
            />
          ))}
        </Part>

        {understanding.calculations.length > 0 ? (
          <Part title="What you can ask about">
            {understanding.calculations.map((calculation) => (
              <Entry key={calculation.id}>
                <h3 className="font-serif text-[1.5rem] leading-tight text-balance">{calculation.name}</h3>
                {calculation.meaning ? <Prose>{calculation.meaning}</Prose> : null}
                {calculation.conditions.map((condition) => (
                  <Prose key={condition}>{condition}</Prose>
                ))}
                <Verdicts
                  verdict={verdicts[calculation.id]}
                  onJudge={judgeItem({ key: calculation.id, subject: calculation.name })}
                />
              </Entry>
            ))}
          </Part>
        ) : null}

        {understanding.assumptions.length > 0 ? (
          <Part
            title="What Signature assumes is always true"
          >
            {understanding.assumptions.map((assumption, index) => {
              const item = { key: `assumption-${index}`, subject: assumption }
              return (
                <Entry key={item.key}>
                  <Prose>{assumption}</Prose>
                  <Verdicts verdict={verdicts[item.key]} onJudge={judgeItem(item)} />
                </Entry>
              )
            })}
          </Part>
        ) : null}
      </main>

      <footer className="fixed inset-x-0 bottom-0 border-t border-line bg-paper/95 backdrop-blur">
        <div className="mx-auto flex max-w-[46rem] flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
          <p className="flex-1 text-[15px] text-muted" aria-live="polite">
            <span className="font-semibold text-ink tabular-nums">
              {checked} of {items.length}
            </span>{' '}
            checked
            {flagged > 0 ? (
              <>
                , <span className="font-semibold text-flag tabular-nums">{flagged}</span> to fix
              </>
            ) : null}
          </p>
          {error && note === null ? (
            <p role="alert" className="w-full text-sm text-flag sm:order-last">
              {error}
            </p>
          ) : null}
          {flagged > 0 ? (
            <button
              type="button"
              onClick={() => setNote((current) => current ?? '')}
              className="rounded-md bg-ink px-4 py-2 text-sm font-semibold text-paper hover:bg-ink/85"
            >
              Tell Signature what to fix
            </button>
          ) : (
            <button
              type="button"
              disabled={sending}
              onClick={() => decide('publish')}
              className="rounded-md bg-signature px-4 py-2 text-sm font-semibold text-signature-ink hover:brightness-110 disabled:opacity-60"
            >
              {checked === items.length ? 'Publish' : 'Publish anyway'}
            </button>
          )}
        </div>
      </footer>

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

function itemsOf(understanding: Understanding): Item[] {
  return [
    ...(understanding.connections.length > 0 ? [CONNECTIONS] : []),
    ...understanding.things.map((thing) => ({ key: thing.id, subject: thing.name })),
    ...understanding.calculations.map((calculation) => ({ key: calculation.id, subject: calculation.name })),
    ...understanding.assumptions.map((assumption, index) => ({ key: `assumption-${index}`, subject: assumption })),
  ]
}

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-16">
      <h2 className="mb-4 font-serif text-[1.75rem] leading-tight text-balance">{title}</h2>
      {children}
    </section>
  )
}

function Entry({ children }: { children: React.ReactNode }) {
  return <div className="border-t border-line py-6">{children}</div>
}

function Prose({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 max-w-[38rem] font-serif text-[1.15rem] leading-relaxed">{children}</p>
}

type ThingEntryProps = {
  thing: Thing
  selected: boolean
  verdict: Verdict | undefined
  onJudge: (verdict: Verdict) => void
}

function ThingEntry({ thing, selected, verdict, onJudge }: ThingEntryProps) {
  const entry = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!selected) return
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    entry.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
  }, [selected])

  return (
    <div ref={entry} className={`scroll-mt-6 border-t py-6 ${selected ? 'border-signature' : 'border-line'}`}>
      <h3 className={`font-serif text-[1.5rem] leading-tight text-balance ${selected ? 'text-signature' : ''}`}>
        {thing.name}
      </h3>
      {thing.meaning ? <Prose>{thing.meaning}</Prose> : null}
      {thing.tracked.length > 0 ? (
        <>
          <p className="mt-4 text-[15px] text-muted">Signature keeps track of:</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[16px] leading-relaxed marker:text-line">
            {thing.tracked.map((line) => (
              <li key={line} className="break-words">
                {line}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {thing.assumptions.length > 0 ? (
        <>
          <p className="mt-4 text-[15px] text-muted">It assumes:</p>
          {thing.assumptions.map((assumption) => (
            <Prose key={assumption}>{assumption}</Prose>
          ))}
        </>
      ) : null}
      {thing.from ? <p className="mt-4 text-sm text-muted">Comes from {thing.from}.</p> : null}
      <Verdicts verdict={verdict} onJudge={onJudge} />
    </div>
  )
}

function Verdicts({ verdict, onJudge }: { verdict: Verdict | undefined; onJudge: (verdict: Verdict) => void }) {
  return (
    <div className="mt-5 flex gap-2">
      <button
        type="button"
        aria-pressed={verdict === 'right'}
        onClick={() => onJudge('right')}
        className={`rounded-full border px-3.5 py-1.5 text-sm ${
          verdict === 'right' ? 'border-signature bg-signature text-signature-ink' : 'border-line hover:border-ink/40'
        }`}
      >
        {verdict === 'right' ? '✓ Looks right' : 'Looks right'}
      </button>
      <button
        type="button"
        aria-pressed={verdict === 'wrong'}
        onClick={() => onJudge('wrong')}
        className={`rounded-full border px-3.5 py-1.5 text-sm ${
          verdict === 'wrong' ? 'border-flag bg-flag-wash text-flag' : 'border-line hover:border-ink/40'
        }`}
      >
        Not quite
      </button>
    </div>
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
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper shadow-[0_-12px_32px_-24px_rgb(0_0_0/0.35)] sm:inset-x-auto sm:top-0 sm:right-0 sm:w-[26rem] sm:border-t-0 sm:border-l"
      aria-label="What Signature should fix"
    >
      <div className="flex h-full flex-col p-6">
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-2xl">What should Signature fix?</h2>
          <button type="button" onClick={onClose} className="text-sm text-muted hover:text-ink">
            Close
          </button>
        </div>
        <p className="mt-2 text-sm text-muted">
          Say what is wrong in your own words. Signature fixes it, then you check again.
        </p>
        <textarea
          ref={field}
          value={note}
          onChange={(event) => onChange(event.target.value)}
          placeholder="For example: a refunded order should not count as revenue…"
          className="mt-4 min-h-40 flex-1 resize-none overscroll-contain rounded-md border border-line bg-paper p-3 font-serif text-[1.05rem] leading-relaxed sm:min-h-0"
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
          Send to Signature
        </button>
      </div>
    </aside>
  )
}
