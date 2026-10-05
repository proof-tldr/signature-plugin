"""The plugin has one version: the server's package carries the release the plugin manifest names."""

import json
from importlib.metadata import version
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[2] / '.claude-plugin' / 'plugin.json'


def test_the_server_package_is_the_release_the_manifest_names() -> None:
    assert version('signature-plugin') == json.loads(MANIFEST.read_text(encoding='utf-8'))['version']
