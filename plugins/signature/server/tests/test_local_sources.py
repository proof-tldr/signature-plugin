"""A declared source is found by name; its connection string comes from the environment and is never in a refusal."""

import json

import pytest

from local_sources import SourceNotUsable, local_source

SECRET = 'postgresql://reader:hunter2@db.internal/shop'


@pytest.fixture
def declared(tmp_path, monkeypatch):
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps({'sources': {'shop': {'adapter': 'postgresql', 'connection_env': 'SHOP_URL'}}}))
    monkeypatch.setenv('SHOP_URL', SECRET)
    return path


def test_a_declared_source_is_resolved(declared):
    source = local_source('shop', declared)
    assert (source.adapter, source.connection_string) == ('postgresql', SECRET)


def test_an_undeclared_source_is_refused_naming_the_declared_ones(declared):
    with pytest.raises(SourceNotUsable, match='shop'):
        local_source('other', declared)


def test_a_source_whose_variable_is_unset_is_refused_without_the_secret(declared, monkeypatch):
    monkeypatch.delenv('SHOP_URL')
    with pytest.raises(SourceNotUsable, match='SHOP_URL') as refusal:
        local_source('shop', declared)
    assert 'hunter2' not in str(refusal.value)


def test_a_missing_config_file_is_refused(tmp_path):
    with pytest.raises(SourceNotUsable, match='No sources are declared'):
        local_source('shop', tmp_path / 'absent.json')


def test_a_malformed_config_is_refused_as_malformed(tmp_path):
    path = tmp_path / 'sources.json'
    path.write_text('{not json')
    with pytest.raises(SourceNotUsable, match='not a JSON object'):
        local_source('shop', path)
