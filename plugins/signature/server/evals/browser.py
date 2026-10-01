"""Stands in for the customer's browser during evaluations: Python's webbrowser runs this through BROWSER with the
page's address, and it submits the form named by EVAL_PAGE_FORM (JSON), or does nothing when that is unset."""

import json
import os
import sys
import urllib.parse
import urllib.request


def main() -> None:
    form = os.environ.get('EVAL_PAGE_FORM')
    if not form:
        return
    body = urllib.parse.urlencode(json.loads(form)).encode()
    urllib.request.urlopen(urllib.request.Request(sys.argv[1], data=body), timeout=30)


if __name__ == '__main__':
    main()
