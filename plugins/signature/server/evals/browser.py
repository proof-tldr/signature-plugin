"""Stands in for the customer's browser during evaluations: Python's webbrowser runs this through BROWSER with the
page's address, and it sends the page the decision named by EVAL_PAGE_FORM (JSON), or does nothing when that is
unset."""

import os
import sys
import urllib.request


def main() -> None:
    form = os.environ.get('EVAL_PAGE_FORM')
    if not form:
        return
    decision = urllib.request.Request(
        f'{sys.argv[1]}/decision', data=form.encode(), headers={'content-type': 'application/json'}
    )
    urllib.request.urlopen(decision, timeout=30)


if __name__ == '__main__':
    main()
