import { BoxIcon, CheckIcon, ChevronDownIcon, DatabaseIcon, LinkIcon, ShieldCheckIcon, SigmaIcon, XIcon } from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { submit } from './api'
import { Notice } from './App'
import { ConnectionsDiagram } from './ConnectionsDiagram'
import { type Snapshot, type Thing, type Understanding, understandingOf } from './review'
import { Button, Card, IconBadge, Row, SectionHeading, Tag } from './ui'

type ReviewPageProps = { domain: string; snapshot: Snapshot }
type Verdict = 'right' | 'wrong'
type Item = { key: string; subject: string }

const CONNECTIONS: Item = { key: 'connections', subject: 'How it fits together' }

export function ReviewPage({ domain, snapshot }: ReviewPageProps) {
  const understanding = useMemo(() => understandingOf(snapshot), [snapshot])
  const items = useMemo(() => itemsOf(understanding), [understanding])
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<'published' | 'changes' | null>(null)

  const judge = (item: Item) => (verdict: Verdict) => {
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
    return <Notice title={`${domain} is published`} body="Go back to Claude to ask your questions." />
  if (decided === 'changes')
    return <Notice title="Changes sent" body="Go back to Claude. It brings you back here once they are in." />

  const checked = items.filter((item) => verdicts[item.key] === 'right').length
  const flagged = items.filter((item) => verdicts[item.key] === 'wrong').length

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[56rem] items-center gap-3 px-6">
          <p className="font-semibold" translate="no">
            Signature
          </p>
          <span className="text-faint">/</span>
          <p className="min-w-0 flex-1 truncate text-muted-foreground">{domain}</p>
          <p className="hidden text-muted-foreground tabular-nums sm:block" aria-live="polite">
            {checked} of {items.length} checked
          </p>
          {flagged > 0 ? (
            <Button variant="primary" onClick={() => setNote((current) => current ?? '')}>
              Send {flagged} to fix
            </Button>
          ) : (
            <Button variant="primary" disabled={sending} onClick={() => decide('publish')}>
              Publish
            </Button>
          )}
        </div>
        {error && note === null ? (
          <p role="alert" className="mx-auto max-w-[56rem] px-6 pb-3 text-destructive">
            {error}
          </p>
        ) : null}
      </header>

      <main className="mx-auto max-w-[56rem] px-6 pt-8 pb-24">
        <h1 className="text-heading-2xl text-balance">Review {domain}</h1>

        {understanding.connections.length > 0 ? (
          <section className="mt-10">
            <SectionHeading actions={<Verdicts verdict={verdicts[CONNECTIONS.key]} onJudge={judge(CONNECTIONS)} />}>
              How it fits together
            </SectionHeading>
            <Card>
              <div className="h-56 border-b border-border">
                <ConnectionsDiagram understanding={understanding} selected={open} onSelect={setOpen} />
              </div>
              {understanding.connections.map((connection) => (
                <Row key={connection.sentence}>
                  <IconBadge tone="attr">
                    <LinkIcon />
                  </IconBadge>
                  <p className="pt-1.5">{connection.sentence}</p>
                </Row>
              ))}
            </Card>
          </section>
        ) : null}

        <section className="mt-10">
          <SectionHeading>Things</SectionHeading>
          <Card>
            {understanding.things.map((thing) => (
              <ThingRow
                key={thing.id}
                thing={thing}
                open={open === thing.id}
                onToggle={() => setOpen((current) => (current === thing.id ? null : thing.id))}
                verdict={verdicts[thing.id]}
                onJudge={judge({ key: thing.id, subject: thing.name })}
              />
            ))}
          </Card>
        </section>

        {understanding.calculations.length > 0 ? (
          <section className="mt-10">
            <SectionHeading>Calculations</SectionHeading>
            <Card>
              {understanding.calculations.map((calculation) => (
                <Row key={calculation.id}>
                  <IconBadge tone="calc">
                    <SigmaIcon />
                  </IconBadge>
                  <Words title={calculation.name} lines={[calculation.meaning, ...calculation.conditions]} />
                  <Verdicts
                    verdict={verdicts[calculation.id]}
                    onJudge={judge({ key: calculation.id, subject: calculation.name })}
                  />
                </Row>
              ))}
            </Card>
          </section>
        ) : null}

        {understanding.assumptions.length > 0 ? (
          <section className="mt-10">
            <SectionHeading>Always true</SectionHeading>
            <Card>
              {understanding.assumptions.map((assumption, index) => {
                const item = { key: `assumption-${index}`, subject: assumption }
                return (
                  <Row key={item.key}>
                    <IconBadge tone="fact">
                      <ShieldCheckIcon />
                    </IconBadge>
                    <p className="min-w-0 flex-1 pt-1.5">{assumption}</p>
                    <Verdicts verdict={verdicts[item.key]} onJudge={judge(item)} />
                  </Row>
                )
              })}
            </Card>
          </section>
        ) : null}
      </main>

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

function Words({ title, lines }: { title: string; lines: (string | undefined)[] }) {
  return (
    <div className="min-w-0 flex-1 pt-1">
      <p className="font-medium">{title}</p>
      {lines.filter(Boolean).map((line) => (
        <p key={line} className="mt-0.5 text-muted-foreground">
          {line}
        </p>
      ))}
    </div>
  )
}

type ThingRowProps = {
  thing: Thing
  open: boolean
  onToggle: () => void
  verdict: Verdict | undefined
  onJudge: (verdict: Verdict) => void
}

function ThingRow({ thing, open, onToggle, verdict, onJudge }: ThingRowProps) {
  const row = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    row.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'nearest' })
  }, [open])

  return (
    <div ref={row} className={`scroll-mt-20 border-t border-border first:border-t-0 ${open ? 'bg-selected' : ''}`}>
      <div className="flex flex-wrap items-start gap-3 px-4 py-3">
        <IconBadge tone="type">
          <BoxIcon />
        </IconBadge>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="focus-ring min-w-0 flex-1 rounded-(--radius-row) pt-1 text-left"
        >
          <span className="flex items-center gap-1.5 font-medium">
            {thing.name}
            <ChevronDownIcon className={`size-4 text-faint transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
          </span>
          {thing.meaning ? <span className="mt-0.5 block text-muted-foreground">{thing.meaning}</span> : null}
        </button>
        <Verdicts verdict={verdict} onJudge={onJudge} />
      </div>
      {open ? <ThingDetails thing={thing} /> : null}
    </div>
  )
}

function ThingDetails({ thing }: { thing: Thing }) {
  return (
    <div className="space-y-4 px-4 pb-4 pl-14">
      {thing.tracked.length > 0 ? (
        <table className="w-full overflow-hidden rounded-(--radius-row) border border-border bg-card text-left">
          <thead className="bg-band text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Detail</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 font-medium">Meaning</th>
            </tr>
          </thead>
          <tbody>
            {thing.tracked.map((detail) => (
              <tr key={detail.name} className="border-t border-border align-top">
                <td className="px-3 py-2 font-medium break-words">{detail.name}</td>
                <td className="px-3 py-2">
                  <span className="flex flex-wrap gap-1">
                    <Tag>{detail.kind}</Tag>
                    {detail.canBeEmpty ? <Tag>Can be empty</Tag> : null}
                  </span>
                </td>
                <td className="px-3 py-2 break-words text-muted-foreground">{detail.meaning ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {thing.assumptions.map((assumption) => (
        <p key={assumption} className="flex gap-2">
          <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-fact-text" aria-hidden />
          {assumption}
        </p>
      ))}
      {thing.from ? (
        <Tag tone="outline">
          <DatabaseIcon aria-hidden />
          From {thing.from}
        </Tag>
      ) : null}
    </div>
  )
}

function Verdicts({ verdict, onJudge }: { verdict: Verdict | undefined; onJudge: (verdict: Verdict) => void }) {
  return (
    <div className="flex shrink-0 gap-1.5">
      <Choice pressed={verdict === 'right'} tone="right" onClick={() => onJudge('right')} icon={<CheckIcon />}>
        Looks right
      </Choice>
      <Choice pressed={verdict === 'wrong'} tone="wrong" onClick={() => onJudge('wrong')} icon={<XIcon />}>
        Not quite
      </Choice>
    </div>
  )
}

function Choice({
  pressed,
  tone,
  onClick,
  icon,
  children,
}: {
  pressed: boolean
  tone: Verdict
  onClick: () => void
  icon: ReactNode
  children: ReactNode
}) {
  const on = tone === 'right' ? 'border-transparent bg-success-soft text-success' : 'border-transparent bg-destructive-soft text-destructive'
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`focus-ring inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-xs font-medium transition-colors [&>svg]:size-3.5 ${
        pressed ? on : 'border-input bg-card text-muted-foreground hover:bg-muted hover:text-foreground'
      }`}
    >
      {icon}
      {children}
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
      className="fixed inset-x-3 bottom-3 z-20 rounded-(--radius-surface) border border-border bg-card shadow-overlay sm:inset-x-auto sm:top-[4.5rem] sm:right-4 sm:bottom-4 sm:w-[24rem]"
      aria-label="What to fix"
    >
      <div className="flex h-full flex-col p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-heading-sm">What to fix</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close">
            <XIcon />
          </Button>
        </div>
        <textarea
          ref={field}
          value={note}
          onChange={(event) => onChange(event.target.value)}
          placeholder="A refunded order should not count as revenue…"
          className="mt-3 min-h-36 flex-1 resize-none overscroll-contain rounded-(--radius-row) border border-input bg-card p-3 text-body-reading focus:border-ring focus:outline-none sm:min-h-0"
        />
        {error ? (
          <p role="alert" className="mt-3 rounded-(--radius-row) bg-destructive-soft px-3 py-2 text-destructive">
            {error}
          </p>
        ) : null}
        <Button variant="primary" className="mt-3 justify-center" disabled={sending || note.trim() === ''} onClick={onSend}>
          Send to Signature
        </Button>
      </div>
    </aside>
  )
}
