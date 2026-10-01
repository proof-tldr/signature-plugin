# Setup experience plan

Drafted with Ethan, 2026-10-01; not built yet. It covers the customer's experience from the
moment their Claude Code has the plugin installed with a domain-scoped API key, through to
asking their first question. It refines [vision.md](vision.md).

This describes what the experience should be, not how to build it. The implementation is
yours to work out.

## Principles

- **The customer runs nothing.** They talk to Claude and click in a browser page.
- **Pass things on as they are.** The customer hands over their documents; Claude doesn't go
  searching for more, and it passes schemas and documents to Signature as they are.
- **The key decides the domain.** There is no "which domain?" step.

## The flow

1. **Orient.** The customer asks Claude to set up Signature. Claude says which domain it's
   working on and where it stands.
2. **Data sources.** Claude asks where the customer's data lives. Expect a mix of files and
   databases, very likely including some kind of SQL server.
3. **Look at them.** Claude and the plugin look at each source enough to understand what it
   holds. What Signature needs to know about a source is not settled; work it out.
4. **Documents.** The customer gives Claude their documents.
5. **Build.** Claude hands Signature the schemas and documents as they are, and Signature builds
   the domain.
6. **Questions during the build.** Signature can stop and ask when it needs to, for example
   when documents contradict each other. There will be other cases; work out which. Claude
   answers what it can and brings the rest to the customer.
7. **Review on localhost.** The customer sees the domain in plain terms and confirms it, which
   publishes it.
8. **Ask.** The customer asks questions; answers appear in their terminal, not to Claude.

## Requirements

- **The local server must be able to query the customer's sources**: files and databases, SQL
  servers included. Signature's queries run there, not in Claude (see vision.md).
- **Credentials stay on the customer's machine** and never pass through Claude.
- **The local pages are for this customer only.** Nothing else on the machine or network
  should be able to use them.
- **The plugin needs no setup from the customer** beyond the API key.

## Decided

- No check-in page before the build: the customer picks the documents themselves (2026-10-01).
- Signature sends ready SQL for one DuckDB on the customer's machine, which opens their files and attaches
  their PostgreSQL and MySQL databases; nothing else runs their queries (2026-10-01).
- The backend endpoints the plugin needs are stubbed by a stand-in until they exist; see
  [backend-contract.md](backend-contract.md).

## Open questions

- What does Signature actually need to know about each source?
- When should Signature stop the build to ask a question, beyond contradictions?
- Should Claude also ask which questions the customer wants answered, to focus the domain?
