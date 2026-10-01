import {
  BoxIcon,
  CheckIcon,
  ChevronDownIcon,
  DatabaseIcon,
  LinkIcon,
  NetworkIcon,
  ShieldCheckIcon,
  SigmaIcon,
  XIcon,
} from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { submit } from './api'
import { Notice } from './App'
import { RelationsDiagram } from './RelationsDiagram'
import { type Examples, type Fact, type Snapshot, type Thing, type Understanding, understandingOf } from './review'
import { Button, Card, IconBadge, Row, SectionHeading, Tag } from './ui'

type ReviewPageProps = { domain: string; snapshot: Snapshot; examples?: Examples }
type Verdict = 'right' | 'wrong'
type Item = { key: string; subject: string }

export function ReviewPage({ domain, snapshot, examples }: ReviewPageProps) {
  const understanding = useMemo(() => understandingOf(snapshot, examples), [snapshot, examples])
  const items = useMemo(() => itemsOf(understanding), [understanding])
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [fixes, setFixes] = useState<Record<string, string>>({})
  const [fixing, setFixing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [decided, setDecided] = useState<'published' | 'changes' | null>(null)

  const judge = (item: Item) => (verdict: Verdict) => {
    setVerdicts((current) => ({ ...current, [item.key]: verdict }))
    if (verdict === 'wrong') setFixing(true)
  }

  const flaggedItems = items.filter((item) => verdicts[item.key] === 'wrong')
  const reviewed = items.filter((item) => verdicts[item.key]).length

  const decide = async (decision: 'publish' | 'change') => {
    setSending(true)
    const changes = flaggedItems
      .filter((item) => fixes[item.key]?.trim())
      .map((item) => `${item.subject}: ${fixes[item.key]!.trim()}`)
      .join('\n')
    const outcome = await submit({ decision, changes })
    setSending(false)
    if ('error' in outcome) setError(outcome.error)
    else setDecided(decision === 'publish' ? 'published' : 'changes')
  }

  if (decided === 'published')
    return <Notice title={`${domain} is published`} body="Go back to Claude to ask your questions." />
  if (decided === 'changes')
    return <Notice title="Your corrections are with Signature" body="Go back to Claude. It brings you back here once they are in." />

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-border bg-background">
        <div className="mx-auto flex h-14 max-w-[56rem] items-center gap-3 px-6">
          <p className="font-semibold" translate="no">
            Signature
          </p>
          <span className="text-faint">/</span>
          <p className="min-w-0 flex-1 truncate text-muted-foreground">{domain}</p>
          <p className="hidden text-muted-foreground tabular-nums sm:block" aria-live="polite">
            {reviewed} of {items.length} reviewed
          </p>
          {flaggedItems.length > 0 ? (
            <Button variant="primary" onClick={() => setFixing(true)}>
              Send {flaggedItems.length} {flaggedItems.length === 1 ? 'correction' : 'corrections'}
            </Button>
          ) : (
            <Button variant="primary" onClick={() => setConfirming(true)}>
              Publish
            </Button>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[56rem] px-6 pt-8 pb-24">
        <h1 className="text-heading-2xl text-balance">Review {domain}</h1>
        <p className="mt-1 text-body-reading text-muted-foreground">
          Mark each item Correct or Wrong. Examples come from your own data.
        </p>

        {understanding.facts.length > 0 ? (
          <section className="mt-10">
            <SectionHeading>How things relate</SectionHeading>
            <Card>
              <div className="h-64 border-b border-border">
                <RelationsDiagram understanding={understanding} selected={open} onSelect={setOpen} />
              </div>
              {understanding.facts.map((fact) => (
                <FactRow
                  key={fact.id}
                  fact={fact}
                  selected={open === fact.id || fact.members.includes(open ?? '')}
                  verdict={verdicts[fact.id]}
                  onJudge={judge({ key: fact.id, subject: fact.title })}
                />
              ))}
            </Card>
          </section>
        ) : null}

        <section className="mt-10">
          <SectionHeading>What Signature knows about</SectionHeading>
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
                  <Lines title={calculation.name} lines={[calculation.meaning, ...calculation.conditions]} />
                  <Verdicts
                    verdict={verdicts[calculation.id]}
                    onJudge={judge({ key: calculation.id, subject: calculation.name })}
                  />
                </Row>
              ))}
            </Card>
          </section>
        ) : null}

        {understanding.rules.length > 0 ? (
          <section className="mt-10">
            <SectionHeading>Rules Signature relies on</SectionHeading>
            <Card>
              {understanding.rules.map((rule, index) => {
                const item = { key: `rule-${index}`, subject: rule }
                return (
                  <Row key={item.key}>
                    <IconBadge tone="fact">
                      <ShieldCheckIcon />
                    </IconBadge>
                    <p className="min-w-0 flex-1 pt-1.5">{rule}</p>
                    <Verdicts verdict={verdicts[item.key]} onJudge={judge(item)} />
                  </Row>
                )
              })}
            </Card>
          </section>
        ) : null}
      </main>

      {confirming ? (
        <Panel title={`Publish ${domain}?`} onClose={() => setConfirming(false)}>
          <p className="text-body-reading text-muted-foreground">
            People your company gives access to can then ask Signature about {domain}. You can correct it and publish
            again at any time.
          </p>
          {reviewed < items.length ? (
            <p className="mt-3 text-body-reading">
              {items.length - reviewed} of {items.length} items are not reviewed yet.
            </p>
          ) : null}
          {error ? <Problem>{error}</Problem> : null}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={() => setConfirming(false)}>Keep reviewing</Button>
            <Button variant="primary" disabled={sending} onClick={() => decide('publish')}>
              Publish
            </Button>
          </div>
        </Panel>
      ) : null}

      {fixing && flaggedItems.length > 0 ? (
        <Panel title="What is wrong?" onClose={() => setFixing(false)}>
          <div className="space-y-4">
            {flaggedItems.map((item, index) => (
              <label key={item.key} className="block">
                <span className="mb-1.5 block font-medium">{item.subject}</span>
                <textarea
                  autoFocus={index === flaggedItems.length - 1}
                  value={fixes[item.key] ?? ''}
                  onChange={(event) => setFixes((current) => ({ ...current, [item.key]: event.target.value }))}
                  placeholder="Say what is wrong and what is right, in your own words…"
                  className="min-h-20 w-full resize-y overscroll-contain rounded-(--radius-row) border border-input bg-card p-3 text-body-reading focus:border-ring focus:outline-none"
                />
              </label>
            ))}
          </div>
          {error ? <Problem>{error}</Problem> : null}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={() => setFixing(false)}>Keep reviewing</Button>
            <Button
              variant="primary"
              disabled={sending || !flaggedItems.some((item) => fixes[item.key]?.trim())}
              onClick={() => decide('change')}
            >
              Send to Signature
            </Button>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function itemsOf(understanding: Understanding): Item[] {
  return [
    ...understanding.facts.map((fact) => ({ key: fact.id, subject: fact.title })),
    ...understanding.things.map((thing) => ({ key: thing.id, subject: thing.name })),
    ...understanding.calculations.map((calculation) => ({ key: calculation.id, subject: calculation.name })),
    ...understanding.rules.map((rule, index) => ({ key: `rule-${index}`, subject: rule })),
  ]
}

function Lines({ title, lines }: { title: string; lines: (string | undefined)[] }) {
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

function ForExample({ cases }: { cases: string[] }) {
  if (cases.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-faint">For example</span>
      {cases.map((example) => (
        <Tag key={example} tone="outline">
          {example}
        </Tag>
      ))}
    </div>
  )
}

type FactRowProps = { fact: Fact; selected: boolean; verdict: Verdict | undefined; onJudge: (verdict: Verdict) => void }

function FactRow({ fact, selected, verdict, onJudge }: FactRowProps) {
  return (
    <div className={`border-t border-border first:border-t-0 ${selected ? 'bg-selected' : ''}`}>
      <div className="flex flex-wrap items-start gap-3 px-4 py-3">
        <IconBadge tone="attr">{fact.kind === 'pair' ? <LinkIcon /> : <NetworkIcon />}</IconBadge>
        <div className="min-w-0 flex-1 pt-1">
          <p className="font-medium">{fact.title}</p>
          {fact.readings.map((reading) => (
            <p key={reading} className="mt-0.5">
              {reading}
            </p>
          ))}
          {fact.meaning ? <p className="mt-0.5 text-muted-foreground">{fact.meaning}</p> : null}
          <ForExample cases={fact.examples} />
        </div>
        <Verdicts verdict={verdict} onJudge={onJudge} />
      </div>
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
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="focus-ring w-full rounded-(--radius-row) pt-1 text-left"
          >
            <span className="flex items-center gap-1.5 font-medium">
              {thing.name}
              <ChevronDownIcon className={`size-4 text-faint transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
            </span>
            {thing.meaning ? <span className="mt-0.5 block text-muted-foreground">{thing.meaning}</span> : null}
          </button>
          <ForExample cases={thing.examples} />
        </div>
        <Verdicts verdict={verdict} onJudge={onJudge} />
      </div>
      {open ? <ThingDetails thing={thing} /> : null}
    </div>
  )
}

function ThingDetails({ thing }: { thing: Thing }) {
  return (
    <div className="space-y-4 px-4 pb-4 pl-14">
      {thing.details.length > 0 ? (
        <table className="w-full overflow-hidden rounded-(--radius-row) border border-border bg-card text-left">
          <thead className="bg-band text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Detail</th>
              <th className="px-3 py-2 font-medium">Holds</th>
              <th className="px-3 py-2 font-medium">Meaning</th>
            </tr>
          </thead>
          <tbody>
            {thing.details.map((detail) => (
              <tr key={detail.name} className="border-t border-border align-top">
                <td className="px-3 py-2 font-medium break-words">{detail.name}</td>
                <td className="px-3 py-2">
                  <span className="flex flex-wrap gap-1">
                    <Tag>{detail.holds}</Tag>
                    {detail.canBeEmpty ? <Tag>Can be empty</Tag> : null}
                  </span>
                </td>
                <td className="px-3 py-2 break-words text-muted-foreground">{detail.meaning ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {thing.rules.map((rule) => (
        <p key={rule} className="flex gap-2">
          <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-fact-text" aria-hidden />
          {rule}
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
        Correct
      </Choice>
      <Choice pressed={verdict === 'wrong'} tone="wrong" onClick={() => onJudge('wrong')} icon={<XIcon />}>
        Wrong
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

function Panel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <aside
      role="dialog"
      aria-label={title}
      onKeyDown={(event) => event.key === 'Escape' && onClose()}
      className="fixed inset-x-3 bottom-3 z-20 max-h-[80vh] overflow-y-auto rounded-(--radius-surface) border border-border bg-card p-4 shadow-overlay sm:inset-x-auto sm:top-[4.5rem] sm:right-4 sm:bottom-auto sm:w-[26rem]"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-heading-sm">{title}</h2>
        <Button variant="ghost" onClick={onClose} aria-label="Close">
          <XIcon />
        </Button>
      </div>
      {children}
    </aside>
  )
}

function Problem({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="mt-3 rounded-(--radius-row) bg-destructive-soft px-3 py-2 text-destructive">
      {children}
    </p>
  )
}
