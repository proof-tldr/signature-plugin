// After ask_question, waits for Signature's answer and shows it to the person in their
// terminal; the model receives only a note that the answer was shown.
import { readFileSync } from 'node:fs';

const POLL_INTERVAL_MS = 1_000;
const DEADLINE_MS = 580_000;

// The plugin's own server declaration is the one place its address is written.
const { signature: server } = JSON.parse(
  readFileSync(new URL('../.mcp.json', import.meta.url), 'utf8'),
);
const apiKey = process.env.CLAUDE_PLUGIN_OPTION_API_KEY;

const readStdin = async () => {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  return JSON.parse(raw);
};

const toolJson = (content) => JSON.parse(content.find((part) => part.type === 'text').text);

// One stateless MCP call; the server may answer as JSON or as a one-event stream.
const callTool = async (name, args) => {
  const response = await fetch(server.url, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${apiKey}`,
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: { name, arguments: args },
    }),
  });
  const body = await response.text();
  const message = response.headers.get('content-type')?.includes('text/event-stream')
    ? JSON.parse(body.split('\n').find((line) => line.startsWith('data:')).slice(5))
    : JSON.parse(body);
  if (message.error || message.result.isError) throw new Error(body);
  return toolJson(message.result.content);
};

const waitForAnswer = async (question) => {
  const deadline = Date.now() + DEADLINE_MS;
  while (Date.now() < deadline) {
    const turn = await callTool('get_answer', question);
    if (turn.state !== 'pending') return turn;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  return { state: 'timed-out' };
};

const shown = (toUser, toModel) =>
  process.stdout.write(
    JSON.stringify({
      systemMessage: toUser,
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        updatedMCPToolOutput: [{ type: 'text', text: toModel }],
      },
    }),
  );

const input = await readStdin();
const accepted = toolJson(input.tool_response);
// A refused question carries no turn; the model reads the refusal as the tool returned it.
if (!accepted.turnId) process.exit(0);
const question = {
  domainId: input.tool_input.domainId,
  threadId: accepted.threadId,
  turnId: accepted.turnId,
};
const followUp = `For a follow-up, call ask_question with threadId ${question.threadId}.`;
const turn = await waitForAnswer(question);

if (turn.state === 'answered') {
  shown(
    turn.answer,
    `The answer was shown directly to the user. You cannot see it and must not try to read it: do not call get_answer, guess, restate or summarise it. ${followUp}`,
  );
} else if (turn.state === 'failed') {
  shown(
    'Signature couldn’t answer this question.',
    `Signature couldn’t answer this question, and the user was told. ${followUp}`,
  );
} else {
  shown(
    'Signature is still working on this answer. Ask again in a moment.',
    'Signature did not answer within ten minutes, and the user was told.',
  );
}
