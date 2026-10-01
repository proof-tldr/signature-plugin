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
   Signature should know. Tell the customer in a line what Signature did.

5. **Signature's questions.** When `build` returns questions, answer the ones you can from what the
   customer said or gave you, with `from_customer` set to whether they told you. Ask the customer the rest
   in one message, then call `answer_questions`. Repeat until nothing is open. If a call says Signature is
   still building, call `wait_for_build`.

6. **Review.** Call `review`. The customer reads the domain in their browser and either publishes it or
   says what's wrong; a requested change comes back as another build, so handle its questions and review
   again.

7. **Ask.** Once published, the customer's questions go through `ask_question`. The answer is shown to
   them directly; you can't see it, so don't guess or restate it.
