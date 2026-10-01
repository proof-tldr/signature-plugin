// The handful of Signature-Frontend components these pages need, in its own recipes: a hairline card of compact
// rows, an icon on a soft tone badge, a pill tag, pill buttons with the ink as primary, and its heading ramp.
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Tone = 'type' | 'fact' | 'calc' | 'attr'

const TONES: Record<Tone, string> = {
  type: 'bg-type-soft text-type-text',
  fact: 'bg-fact-soft text-fact-text',
  calc: 'bg-calc-soft text-calc-text',
  attr: 'bg-attr-soft text-attr-text',
}

export function Card({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-(--radius-surface) border border-border bg-card shadow-low">{children}</div>
}

export function Row({ children, divided = true }: { children: ReactNode; divided?: boolean }) {
  return <div className={`flex flex-wrap items-start gap-3 px-4 py-3 ${divided ? 'border-t border-border first:border-t-0' : ''}`}>{children}</div>
}

export function IconBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-(--radius-row) [&>svg]:size-4 ${TONES[tone]}`} aria-hidden>
      {children}
    </span>
  )
}

export function Tag({ children, tone = 'quiet' }: { children: ReactNode; tone?: 'quiet' | 'outline' }) {
  const look = tone === 'outline' ? 'border-input bg-card text-foreground' : 'border-border bg-control text-muted-foreground'
  return (
    <span className={`inline-flex h-5 items-center gap-1 rounded-full border px-2 text-2xs font-medium whitespace-nowrap [&>svg]:size-3 ${look}`}>
      {children}
    </span>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'outline' | 'ghost' }

const BUTTONS = {
  primary: 'bg-primary text-primary-foreground hover:bg-primary-hover',
  outline: 'border border-input bg-card text-foreground hover:bg-muted',
  ghost: 'text-muted-foreground hover:bg-muted hover:text-foreground',
}

export function Button({ variant = 'outline', className = '', ...button }: ButtonProps) {
  return (
    <button
      type="button"
      {...button}
      className={`focus-ring inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&>svg]:size-4 ${BUTTONS[variant]} ${className}`}
    />
  )
}

export function SectionHeading({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <h2 className="text-heading-sm">{children}</h2>
      {actions}
    </div>
  )
}
