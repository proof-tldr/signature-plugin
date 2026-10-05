---
name: setup
description: Set up the customer's Signature domain from their data and documents, then have them review and publish it. Use when the customer asks to set up, configure or build Signature, or to give Signature their data or documents.
---

# Set up Signature

The customer's API key opens one domain; you never choose or create one. Keep the customer's effort low:
ask only what you need from them, and do the rest with the Signature tools.

The plugin draws each step for the customer as it happens: what was added, the build's progress, what it came
to. Don't narrate tool calls or restate what a card shows. Speak only when the customer has something to do or
decide, in one short sentence. A Signature call Claude Code moves to the background is still working, and the
plugin shows its progress: say nothing about it, and go on when its result arrives.

1. **Orient.** Call `get_status`. If the domain already has sources or open questions, say so in one line and
   pick up from there rather than starting over; otherwise say nothing about it.

2. **Set up.** Call `set_up` at once, without asking the customer anything or saying anything first: it asks them
   itself, in forms Claude Code shows them, for the documents explaining their business, their data, and the
   documents explaining it, then builds. When it returns, tell the customer in one sentence what Signature built:
   at most the main kinds of things, never every detail, which the review page shows. If they stopped it, ask in
   one sentence whether they want to go on, and call it again when they do.

3. **Without forms.** If `set_up` says this Claude Code cannot show its forms, gather the same three things in
   chat, one short question at a time and in that order, then build:
   - Files (CSV, TSV, XLSX, Parquet, JSON, or folders of them): call `add_data_files` with absolute paths.
   - A PostgreSQL or MySQL database: call `connect_database`. When the customer names a file holding its
     connection, pass that path as `connection_file` exactly as they wrote it, and never open, read, print or
     look for the file yourself: it holds a password. Otherwise the customer enters the connection on a page in
     their browser, which explains itself. Never ask for a password in chat.
   - Anything else (another database, a warehouse, an API): tell them it isn't supported yet and ask for an
     export to a file instead.
   - Documents: keep their paths exactly as given, without searching for more, then call `build` with those
     explaining the business as `documents` and those explaining the data as `data_documents`, once the customer
     says that is everything.

4. **Signature's questions.** When `set_up` or `build` returns questions, they are numbered. Answer the ones you can
   from what the customer said or gave you, with `from_customer` set to whether they told you. Ask the
   customer the rest in one message, then call `answer_questions` with the numbers. Repeat until nothing is
   open. If a call says Signature is still building, call `wait_for_build`.

5. **Review.** Call `review`. The customer is shown a link to a page where they read the domain and either
   publish it or say what's wrong. If they decline to open it, ask when they want to review. A requested
   change comes back as another build, so handle its questions and review again.

6. **Ask.** Once published, tell the customer they can ask questions; don't invent example questions for
   them. Their questions go through `ask_question`, which draws the answer as a table under the call for the
   customer; you are told only that it was drawn. Don't restate, guess at or comment on it, since Signature's
   proven answer is the whole answer, and send any question about it, or anything needing other numbers, back
   to Signature. For a refinement of the last question, set `follow_up`. `/signature-answer` opens the last
   answer in full.
