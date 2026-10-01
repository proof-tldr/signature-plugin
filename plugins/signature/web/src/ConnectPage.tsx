import { type FormEvent, useState } from 'react'

import { submit } from './api'
import { Notice } from './App'

const ENGINES = [
  { value: 'postgres', label: 'PostgreSQL', port: '5432' },
  { value: 'mysql', label: 'MySQL or MariaDB', port: '3306' },
] as const

export function ConnectPage({ suggestedName }: { suggestedName: string | null }) {
  const [engine, setEngine] = useState<(typeof ENGINES)[number]['value']>('postgres')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [connected, setConnected] = useState<string | null>(null)

  const connect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = Object.fromEntries(new FormData(event.currentTarget)) as Record<string, string>
    setSending(true)
    const outcome = await submit({ ...form, engine })
    setSending(false)
    if ('error' in outcome) setError(outcome.error)
    else setConnected(form.name ?? engine)
  }

  if (connected)
    return <Notice title={`${connected} is connected`} body="Go back to Claude. It will carry on setting up Signature." />

  const port = ENGINES.find((choice) => choice.value === engine)?.port

  return (
    <main className="mx-auto max-w-xl px-6 py-14">
      <p className="mb-8 font-semibold" translate="no">
        Signature
      </p>
      <h1 className="text-heading-2xl text-balance">Connect a database</h1>
      <p className="mt-2 text-body-reading text-muted-foreground">
        Signature reads this database's structure and runs its queries here, on your computer. The password goes
        into your system keychain; Claude never sees it and it is never sent to Signature.
      </p>

      <form onSubmit={connect} className="mt-10 space-y-5">
        <fieldset>
          <legend className="mb-2 font-medium">Database</legend>
          <div className="flex gap-2">
            {ENGINES.map((choice) => (
              <label
                key={choice.value}
                className={`cursor-pointer rounded-full border px-3.5 py-1.5 text-sm font-medium has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring ${
                  engine === choice.value ? 'border-transparent bg-primary text-primary-foreground' : 'border-input bg-card hover:bg-muted'
                }`}
              >
                <input
                  type="radio"
                  name="engine-choice"
                  value={choice.value}
                  checked={engine === choice.value}
                  onChange={() => setEngine(choice.value)}
                  className="sr-only"
                />
                {choice.label}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Name" name="name" defaultValue={suggestedName ?? ''} hint="How you and Signature will refer to it." />
        <div className="grid grid-cols-[minmax(0,1fr)_7rem] gap-3">
          <Field label="Host" name="host" defaultValue="localhost" />
          <Field label="Port" name="port" defaultValue="" placeholder={port} inputMode="numeric" required={false} />
        </div>
        <Field label="Database name" name="database" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="User" name="user" autoComplete="username" spellCheck={false} />
          <Field label="Password" name="password" type="password" autoComplete="current-password" required={false} />
        </div>
        <p className="text-muted-foreground">A read-only user is best: Signature only ever reads.</p>
        {error ? (
          <p role="alert" className="rounded-(--radius-row) bg-destructive-soft px-3 py-2 text-destructive">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={sending}
          className="focus-ring inline-flex h-8 items-center rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
        >
          {sending ? 'Connecting…' : 'Connect'}
        </button>
      </form>
    </main>
  )
}

type FieldProps = React.InputHTMLAttributes<HTMLInputElement> & { label: string; name: string; hint?: string }

function Field({ label, name, hint, required = true, ...input }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-medium">{label}</span>
      <input
        name={name}
        required={required}
        autoComplete="off"
        spellCheck={false}
        {...input}
        className="h-9 w-full rounded-full border border-input bg-card px-3.5 focus:border-ring focus:outline-none"
      />
      {hint ? <span className="mt-1.5 block text-muted-foreground">{hint}</span> : null}
    </label>
  )
}
