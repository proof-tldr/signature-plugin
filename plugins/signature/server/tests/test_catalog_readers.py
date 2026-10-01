"""A source the plugin cannot read is refused before any connection is made."""

import asyncio

import pytest

from catalog_readers import read_structure
from local_sources import LocalSource, SourceNotUsable


def test_an_adapter_the_plugin_cannot_read_is_refused():
    with pytest.raises(SourceNotUsable, match='mongodb'):
        asyncio.run(read_structure(LocalSource('logs', 'mongodb', 'mongodb://unused')))
