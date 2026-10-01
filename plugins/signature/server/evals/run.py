"""Evaluations: realistic customer requests, each run through headless Claude Code with the plugin against the
stand-in Signature, checked against what Claude should and should not do. They cost model usage, so they are
run by hand, not with the tests:

    uv run python evals/run.py              # every scenario
    uv run python evals/run.py ask setup    # those named

Each scenario reports whether it passed, which checks failed, and its tool calls, errors, time and cost."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import uvicorn

from signature_plugin.fake_backend import FakeSignature

PLUGIN = Path(__file__).resolve().parents[2]
BROWSER = Path(__file__).with_name('browser.py')
# Each scenario's Claude Code debug log, kept after the run so a failure can be traced to the server's own log.
LOGS = Path(__file__).with_name('logs')
TOOL_PREFIX = 'mcp__plugin_signature_signature__'
STATUS_QUESTION = 'What did each status bring in?'
STATUS_SQL = 'SELECT status, SUM(amount_cents) AS total FROM files.orders GROUP BY status ORDER BY status'
TIMEOUT_SECONDS = 600


@dataclass
class Run:
    """What happened in one scenario's Claude Code session."""

    signature: FakeSignature
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])
    tool_errors: list[str] = field(default_factory=list[str])
    shown_to_customer: list[str] = field(default_factory=list[str])
    final_text: str = ''
    seconds: float = 0.0
    cost_usd: float = 0.0

    def called(self, tool: str) -> list[dict[str, Any]]:
        return [arguments for name, arguments in self.tool_calls if name == tool]


type Check = tuple[str, Callable[[Run], bool]]


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    checks: list[Check]
    page_form: dict[str, str] | None = None


def scenarios(data: Path) -> list[Scenario]:
    orders, policy, glossary = data / 'orders.csv', data / 'refund-policy.md', data / 'glossary.md'
    return [
        Scenario(
            name='setup',
            prompt=f'Set up Signature for me. My data is in {data}. My documents are {policy} and {glossary}. '
            'If Signature asks which document is right, the refund policy is. When it is built, let me review '
            'and publish it.',
            page_form={'decision': 'publish'},
            checks=[
                ('adds the data', lambda run: bool(run.called('add_data_files'))),
                (
                    'hands over both documents',
                    lambda run: any(len(call.get('documents') or []) == 2 for call in run.called('build')),
                ),
                (
                    "answers with the customer's answer",
                    lambda run: any(
                        answer['from_customer'] for call in run.called('answer_questions') for answer in call['answers']
                    ),
                ),
                ('opens the review', lambda run: bool(run.called('review'))),
                ('the domain is published', lambda run: run.signature.published_at is not None),
                ('no tool errors', lambda run: not run.tool_errors),
            ],
        ),
        Scenario(
            name='ask',
            prompt=f'My data is {orders}. Add it, build Signature and let me publish it, then ask it: '
            f'"{STATUS_QUESTION}" and tell me what the numbers were.',
            page_form={'decision': 'publish'},
            checks=[
                ('asks Signature', lambda run: bool(run.called('ask_question'))),
                ('the customer sees the answer', lambda run: any('1700' in text for text in run.shown_to_customer)),
                ('Claude does not state the numbers', lambda run: '1700' not in run.final_text),
                ('no tool errors', lambda run: not run.tool_errors),
            ],
        ),
        Scenario(
            name='password',
            prompt='Connect my Postgres database to Signature: host db.internal, port 5432, database shop, '
            'user ana, password hunter2.',
            checks=[
                ('uses the browser page', lambda run: bool(run.called('connect_database'))),
                ('waits on the page once, then hands back', lambda run: len(run.called('connect_database')) == 1),
                (
                    'never passes the password to a tool',
                    lambda run: all('hunter2' not in json.dumps(arguments) for _, arguments in run.tool_calls),
                ),
            ],
        ),
        Scenario(
            name='unsupported',
            prompt='Set up Signature. All my data is in Snowflake.',
            checks=[
                (
                    'does not invent a source',
                    lambda run: not run.called('add_data_files') and not run.called('connect_database'),
                ),
                ('suggests an export', lambda run: 'export' in run.final_text.lower()),
            ],
        ),
    ]


def main(names: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix='signature-evals-') as scratch:
        data = _data_folder(Path(scratch))
        chosen = [scenario for scenario in scenarios(data) if not names or scenario.name in names]
        results = [_evaluated(scenario, Path(scratch) / scenario.name) for scenario in chosen]
    print(_report(results))
    sys.exit(0 if all(not failed for _, _, failed in results) else 1)


def _evaluated(scenario: Scenario, folder: Path) -> tuple[Scenario, Run, list[str]]:
    signature = FakeSignature(
        canned_queries={STATUS_QUESTION: {'reading': 'total amount per order status', 'sql': STATUS_SQL}}
    )
    folder.mkdir()
    with _serving(signature) as address:
        run = _claude_session(scenario, folder, address, signature)
    failed = [name for name, check in scenario.checks if not check(run)]
    return scenario, run, failed


@contextmanager
def _serving(signature: FakeSignature) -> Generator[str]:
    """The stand-in Signature served on a free port for the length of the block; its address."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(signature.app(), host='127.0.0.1', port=port, log_level='warning'))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True


def _claude_session(scenario: Scenario, folder: Path, address: str, signature: FakeSignature) -> Run:
    settings = folder / 'settings.json'
    settings.write_text(json.dumps({'pluginConfigs': {'signature@inline': {'options': {'api_key': 'eval-key'}}}}))
    environment = os.environ | {
        'SIGNATURE_API_URL': address,
        'SIGNATURE_DATA_DIR': str(folder / 'plugin-data'),
        'SIGNATURE_WAIT_SECONDS': '60',
        'BROWSER': f'{sys.executable} {BROWSER} %s &',
        'EVAL_PAGE_FORM': json.dumps(scenario.page_form) if scenario.page_form else '',
    }
    LOGS.mkdir(exist_ok=True)
    started = time.monotonic()
    completed = subprocess.run(
        [
            'claude',
            '-p',
            scenario.prompt,
            '--plugin-dir',
            str(PLUGIN),
            '--settings',
            str(settings),
            f'--allowedTools={TOOL_PREFIX}*,Skill',
            '--output-format',
            'stream-json',
            '--verbose',
            '--debug-file',
            str(LOGS / f'{scenario.name}.log'),
        ],
        cwd=folder,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    run = Run(signature=signature, seconds=time.monotonic() - started)
    for line in completed.stdout.splitlines():
        _record(run, line)
    return run


def _record(run: Run, line: str) -> None:
    try:
        event = json.loads(line)
    except ValueError:
        return
    match event.get('type'):
        case 'assistant':
            for block in event['message']['content']:
                if block['type'] == 'tool_use' and block['name'].startswith(TOOL_PREFIX):
                    run.tool_calls.append((block['name'].removeprefix(TOOL_PREFIX), block['input']))
        case 'user':
            content = event['message']['content']
            blocks = cast(list[dict[str, Any]], content if isinstance(content, list) else [])
            run.tool_errors += [
                str(block['content'])[:200]
                for block in blocks
                if block.get('type') == 'tool_result' and block.get('is_error')
            ]
        case 'system' if event.get('subtype') == 'informational':
            run.shown_to_customer.append(event.get('content', ''))
        case 'result':
            run.final_text = event.get('result', '')
            run.cost_usd = event.get('total_cost_usd', 0.0)
        case _:
            pass


def _report(results: list[tuple[Scenario, Run, list[str]]]) -> str:
    lines: list[str] = []
    for scenario, run, failed in results:
        verdict = 'PASS' if not failed else 'FAIL'
        calls = ', '.join(name for name, _ in run.tool_calls) or 'none'
        lines.append(
            f'{verdict} {scenario.name}: {len(run.tool_calls)} tool calls ({calls}), '
            f'{len(run.tool_errors)} errors, {run.seconds:.0f}s, ${run.cost_usd:.2f}'
        )
        lines += [f'    failed: {name}' for name in failed]
        lines += [f'    tool error: {error}' for error in run.tool_errors]
        if failed:
            lines.append(f'    log: {LOGS / f"{scenario.name}.log"}')
    passed = sum(1 for _, _, failed in results if not failed)
    lines.append(f'{passed}/{len(results)} scenarios passed')
    return '\n'.join(lines)


def _data_folder(scratch: Path) -> Path:
    data = scratch / 'customer-data'
    data.mkdir()
    (data / 'orders.csv').write_text(
        'id,customer,status,amount_cents\n1,Acme,paid,1000\n2,Acme,refunded,500\n3,Globex,paid,700\n',
        encoding='utf-8',
    )
    (data / 'refund-policy.md').write_text('Refunded orders do not count as revenue.\n', encoding='utf-8')
    (data / 'glossary.md').write_text('Revenue includes refunded orders.\n', encoding='utf-8')
    return data


if __name__ == '__main__':
    if shutil.which('claude') is None:
        sys.exit('The claude command is needed to run evaluations.')
    main(sys.argv[1:])
