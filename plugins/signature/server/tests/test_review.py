from signature_plugin.pages import TEMPLATES
from signature_plugin.review import Section, review_of

SNAPSHOT = {
    'entities': [
        {
            'id': 'e1',
            'name': 'Order',
            'plural': 'Orders',
            'doc': 'A purchase a customer placed.',
            'invariants': [{'id': 'i1', 'expression': '…', 'english': 'An order total is never negative.'}],
        },
    ],
    'fields': [
        {'id': 'f1', 'entityId': 'e1', 'name': 'total', 'type': {'kind': 'named', 'name': 'money'}, 'doc': 'In cents.'},
        {
            'id': 'f2',
            'entityId': 'e1',
            'name': 'refunds',
            'type': {'kind': 'set', 'item': {'kind': 'named', 'name': 'Refund'}},
        },
    ],
    'functions': [
        {
            'id': 'g1',
            'name': 'revenue',
            'doc': 'Money kept from paid orders.',
            'pre': [],
            'post': [{'id': 'p1', 'expression': '…', 'english': 'Refunded orders do not count.'}],
        },
    ],
    'axioms': [{'id': 'a1', 'expression': '…', 'english': 'Every order has one customer.'}],
    'sources': [{'id': 's1'}],
    'databaseEntities': [{'id': 't1', 'relation': 'orders'}],
    'mappings': [{'id': 'm1', 'entityId': 'e1', 'databaseEntityId': 't1'}],
}


def test_the_review_lists_each_thing_its_rules_and_where_it_comes_from() -> None:
    review = review_of(SNAPSHOT)

    assert review.summary == 'Signature knows about 1 kind of thing, holds to 2 rules, and draws on 1 source.'
    assert review.sections == [
        Section(
            title='Orders',
            intro='A purchase a customer placed.',
            points=['total (money): In cents.', 'refunds (set of Refund)', 'An order total is never negative.'],
        ),
        Section(
            title='Rules',
            intro=None,
            points=[
                'Every order has one customer.',
                'revenue: Money kept from paid orders. Refunded orders do not count.',
            ],
        ),
        Section(title='Where the data comes from', intro=None, points=['Order comes from orders']),
    ]


def test_an_empty_model_still_reviews() -> None:
    review = review_of({})

    assert review.sections == []
    assert 'knows about 0 kinds of thing' in review.summary


def test_the_page_shows_the_review_escaped() -> None:
    snapshot = SNAPSHOT | {'axioms': [{'id': 'a1', 'expression': '…', 'english': 'Totals < 1,000 <b>never</b>'}]}

    page = TEMPLATES.get_template('review.html').render(domain_name='Acme', review=review_of(snapshot))

    assert 'Review Acme' in page
    assert 'A purchase a customer placed.' in page
    assert 'Totals &lt; 1,000 &lt;b&gt;never&lt;/b&gt;' in page
