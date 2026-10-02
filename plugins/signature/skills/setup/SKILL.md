---
name: setup
description: Set up the customer's Signature domain from their data and documents, then have them review and publish it. Use when the customer asks to set up, configure or build Signature, or to give Signature their data or documents.
---

# Set up Signature

The customer's API key opens one domain; you never choose or create one. Keep the customer's effort low:
ask only what you need from them, and do the rest with the Signature tools.

1. **Orient.** Call `get_status` and tell the customer in one line which domain this is and where it stands.
   If it already has sources or open questions, pick up from there rather than starting over.

2. **Data sources.** Ask where their data lives: files, databases, or both.
   - Files (CSV, TSV, XLSX, Parquet, JSON, or folders of them): call `add_data_files` with absolute paths.
   - A PostgreSQL or MySQL database: call `connect_database`. The customer enters the connection in their
     browser; never ask them for a password in chat. Call it once per database.
   - Anything else (another database, a warehouse, an API): tell them it isn't supported yet and ask for an
     export to a file instead.

3. **Documents.** Ask for the documents that explain their business and data: policies, specs, data
   dictionaries, notes. Use exactly the files they give you; don't search for more.

4. **Build.** Call `build` with the document paths and, as `note`, anything the customer told you that
   Signature should know. Tell the customer in one sentence what Signature built: at most the main kinds of
   things, never every detail, which the review page shows.

5. **Signature's questions.** When `build` returns questions, they are numbered. Answer the ones you can
   from what the customer said or gave you, with `from_customer` set to whether they told you. Ask the
   customer the rest in one message, then call `answer_questions` with the numbers. Repeat until nothing is
   open. If a call says Signature is still building, call `wait_for_build`.

6. **Review.** Call `review`. The customer is shown a link to a page where they read the domain and either
   publish it or say what's wrong. If they decline to open it, ask when they want to review. A requested
   change comes back as another build, so handle its questions and review again.

7. **Ask.** Once published, tell the customer they can ask questions; don't invent example questions for
   them. Their questions go through `ask_question`, which draws the answer as a table under the call. You see
   the same rows: don't repeat or comment on them, since Signature's proven answer is the whole answer, and send
   any question about them, or anything needing other numbers, back to Signature. For a refinement of the
   last question, set `follow_up`. `/signature-answer` opens the last answer in full.
