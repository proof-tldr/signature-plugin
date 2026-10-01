"""A source the plugin cannot read is refused before any connection is made."""

import asyncio

import pytest

from catalog_readers import SourceNotUsable, read_structure


def test_an_adapter_the_plugin_cannot_read_is_refused():
    with pytest.raises(SourceNotUsable, match='mongodb'):
        asyncio.run(read_structure('mongodb', 'logs'))


def test_an_undefined_service_is_refused_naming_only_the_service():
    with pytest.raises(SourceNotUsable, match='nowhere') as refusal:
        asyncio.run(read_structure('postgresql', 'nowhere'))
    assert 'host' not in str(refusal.value).lower().replace('~/.pg_service.conf', '')
