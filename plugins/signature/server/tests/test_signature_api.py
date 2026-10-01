"""A source keeps its id across reports, so a re-report replaces the last."""

from signature_api import source_id_of


def test_a_source_keeps_its_id_across_reports():
    assert source_id_of('orders') == source_id_of('orders') != source_id_of('billing')
