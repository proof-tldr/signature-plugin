"""A source keeps its id across reports of the same domain and service, so a re-report replaces the last."""

from signature_api import source_id_of


def test_a_source_keeps_its_id_across_reports():
    assert source_id_of('d1', 'shop') == source_id_of('d1', 'shop')


def test_the_same_service_in_another_domain_is_another_source():
    assert source_id_of('d1', 'shop') != source_id_of('d2', 'shop')


def test_two_services_in_one_domain_are_two_sources():
    assert source_id_of('d1', 'shop') != source_id_of('d1', 'billing')
