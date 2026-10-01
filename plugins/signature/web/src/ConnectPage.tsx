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
      <p className="mb-10 text-sm font-semibold text-muted" translate="no">
        Signature
      </p>
      <h1 className="font-serif text-4xl leading-tight text-balance">Connect a database</h1>
      <p className="mt-4 text-lg leading-relaxed text-muted">
        Signature reads this database's structure and runs its queries here, on your computer. The password goes
        into your system keychain; Claude never sees it and it is never sent to Signature.
      </p>

      <form onSubmit={connect} className="mt-10 space-y-5">
        <fieldset>
          <legend className="mb-2 text-sm font-semibold">Database</legend>
          <div className="flex gap-2">
            {ENGINES.map((choice) => (
              <label
                key={choice.value}
                className={`cursor-pointer rounded-md border px-3.5 py-2 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-signature ${
                  engine === choice.value ? 'border-signature bg-signature-wash' : 'border-line'
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
        <p className="text-sm text-muted">A read-only user is best: Signature only ever reads.</p>
        {error ? (
          <p role="alert" className="rounded-md bg-flag-wash px-3.5 py-2.5 text-sm text-flag">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={sending}
          className="rounded-md bg-signature px-5 py-2.5 text-sm font-semibold text-signature-ink hover:brightness-110 disabled:opacity-60"
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
      <span className="mb-1.5 block text-sm font-semibold">{label}</span>
      <input
        name={name}
        required={required}
        autoComplete="off"
        spellCheck={false}
        {...input}
        className="w-full rounded-md border border-line bg-paper px-3 py-2.5 text-[15px] focus:border-signature"
      />
      {hint ? <span className="mt-1.5 block text-sm text-muted">{hint}</span> : null}
    </label>
  )
}
