"""The databases the member has declared on this machine. The config file names each source and the environment
variable holding its connection string; the string itself is read only here, and never leaves the plugin."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path('~/.config/signature/sources.json')


class SourceNotUsable(Exception):
    """A local source that cannot be reported, with a reason that names no secret."""


@dataclass(frozen=True)
class LocalSource:
    name: str
    adapter: str
    connection_string: str


def local_source(name: str, config_path: Path | None = None) -> LocalSource:
    """The declared source called `name`, with its connection string taken from the environment."""
    path = (config_path or Path(os.environ.get('SIGNATURE_SOURCES_FILE', DEFAULT_CONFIG))).expanduser()
    try:
        text = path.read_text()
    except OSError as failure:
        raise SourceNotUsable(f'No sources are declared. Create {path} with a "sources" object.') from failure
    try:
        declared = json.loads(text)['sources']
        source = declared.get(name)
        known = sorted(declared)
    except (ValueError, KeyError, TypeError, AttributeError) as failure:
        raise SourceNotUsable(f'{path} is not a JSON object with a "sources" object.') from failure
    if source is None:
        raise SourceNotUsable(f'No source called {name}. Declared sources: {", ".join(known) or "none"}.')
    try:
        variable, adapter = source['connection_env'], source['adapter']
    except (KeyError, TypeError) as failure:
        raise SourceNotUsable(f'Source {name} needs an "adapter" and a "connection_env".') from failure
    if variable not in os.environ:
        raise SourceNotUsable(f'Source {name} reads its connection from the environment variable {variable}, '
                              'which is not set where Claude Code runs.')
    return LocalSource(name=name, adapter=adapter, connection_string=os.environ[variable])
