# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The PostToolUse hook after ask_question: shows the member the answer the server left for that question. The
model never receives it. Claude Code runs it only when ask_question succeeded."""

import json
import sys

import answer_handoff

NOT_SHOWN = 'Signature answered, but the answer could not be shown. Ask the question again.'


def main() -> None:
    asked = json.loads(json.load(sys.stdin)['tool_response'])
    shown = answer_handoff.take(asked['turn_id']) or NOT_SHOWN
    json.dump({'systemMessage': shown}, sys.stdout, ensure_ascii=False)


if __name__ == '__main__':
    main()
