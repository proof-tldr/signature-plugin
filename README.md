# Signature for Claude Code

Connects Claude Code to Signature's MCP server. Answers to your questions print in your
terminal and are withheld from the model.

```sh
claude plugin marketplace add proof-tldr/signature-plugin
claude plugin install signature@signature
```

Claude Code asks for your API key during install (create one under Settings → API keys in
Signature) and keeps it in your system keychain.

## What's here

- `plugins/signature/.mcp.json` — the Signature MCP server, authenticated with your key.
- `plugins/signature/hooks/show-answer.mjs` — after `ask_question`, waits for the answer and
  shows it to you; the model only learns that it was shown.
- `plugins/signature/hooks/hooks.json` — wires that hook and stops the model reading answers
  through `get_answer`.

Requires Node.js 18 or later.
