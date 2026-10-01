import { useEffect, useState } from 'react'

import { loadPage, type PageData } from './api'
import { ConnectPage } from './ConnectPage'
import { ReviewPage } from './ReviewPage'

export function App() {
  const [page, setPage] = useState<PageData | { failed: string } | null>(null)

  useEffect(() => {
    loadPage().then(setPage, (failure: Error) => setPage({ failed: failure.message }))
  }, [])

  if (page === null) return null
  if ('failed' in page) return <Notice title="This page has expired" body={page.failed} />
  return page.page === 'review' ? <ReviewPage domain={page.domain} snapshot={page.snapshot} /> : <ConnectPage suggestedName={page.suggestedName} />
}

export function Notice({ title, body }: { title: string; body: string }) {
  return (
    <main className="mx-auto flex min-h-full max-w-xl flex-col justify-center px-6 py-16">
      <p className="mb-10 text-sm font-semibold text-muted" translate="no">
        Signature
      </p>
      <h1 className="font-serif text-4xl leading-tight text-balance">{title}</h1>
      <p className="mt-4 text-lg text-muted">{body}</p>
    </main>
  )
}
