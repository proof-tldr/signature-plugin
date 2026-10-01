"""The PostToolUse hook after ask_question: shows the customer the answer the server left, in their terminal.
Claude never receives it. Claude Code passes the tool's result as its JSON text, and runs this only when
ask_question succeeded."""

import json
import sys

from signature_plugin import handoff

NOT_SHOWN = 'Signature answered, but the answer could not be shown. Ask the question again.'


def main() -> None:
    asked = json.loads(json.load(sys.stdin)['tool_response'])
    shown = handoff.take(asked['query_id']) or NOT_SHOWN
    json.dump({'systemMessage': shown}, sys.stdout, ensure_ascii=False)


if __name__ == '__main__':
    main()
