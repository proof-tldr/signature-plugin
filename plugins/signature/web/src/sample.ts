// A sample domain for working on the pages with `npm run dev`; never part of the build's runtime path.
import type { PageData } from './api'

export function samplePage(query: URLSearchParams): PageData {
  if (query.get('page') === 'connect') return { page: 'connect', suggestedName: 'sales' }
  const statement = (id: string, english: string) => ({ id, english })
  return {
    page: 'review',
    domain: 'Acme Supply',
    snapshot: {
      entities: [
        { id: 'c', name: 'Customer', plural: 'Customers', doc: 'A company that buys from Acme Supply.',
          invariants: [statement('i1', 'Test accounts are not customers.')] },
        { id: 'o', name: 'Order', plural: 'Orders', doc: 'A purchase a customer placed.',
          invariants: [statement('i2', 'An order total is never negative.')] },
        { id: 'l', name: 'OrderLine', plural: 'Order lines', doc: 'One product on an order, with its quantity.' },
        { id: 'p', name: 'Product', plural: 'Products', doc: 'Something Acme Supply sells.' },
        { id: 'r', name: 'Region', plural: 'Regions', doc: 'Where a customer is based.' },
      ],
      fields: [
        { id: 'f1', entityId: 'c', name: 'name', type: { kind: 'named', name: 'text' } },
        { id: 'f2', entityId: 'c', name: 'region', type: { kind: 'named', name: 'Region' } },
        { id: 'f3', entityId: 'o', name: 'customer', type: { kind: 'named', name: 'Customer' } },
        { id: 'f4', entityId: 'o', name: 'placed on', type: { kind: 'named', name: 'date' } },
        { id: 'f5', entityId: 'o', name: 'status', type: { kind: 'named', name: 'text' },
          doc: 'Pending, paid, refunded or cancelled.' },
        { id: 'f6', entityId: 'o', name: 'total', type: { kind: 'named', name: 'money' }, doc: 'In US cents, after discounts.' },
        { id: 'f7', entityId: 'l', name: 'order', type: { kind: 'named', name: 'Order' } },
        { id: 'f8', entityId: 'l', name: 'product', type: { kind: 'named', name: 'Product' } },
        { id: 'f9', entityId: 'l', name: 'quantity', type: { kind: 'named', name: 'whole number' } },
        { id: 'f10', entityId: 'p', name: 'title', type: { kind: 'named', name: 'text' } },
        { id: 'f11', entityId: 'p', name: 'price', type: { kind: 'optional', item: { kind: 'named', name: 'money' } } },
        { id: 'f12', entityId: 'r', name: 'name', type: { kind: 'named', name: 'text' } },
      ],
      functions: [
        { id: 'g1', name: 'Revenue', doc: 'Money kept from paid orders in a period.',
          post: [statement('p1', 'Refunded and cancelled orders do not count.')] },
        { id: 'g2', name: 'New customers', doc: 'Customers whose first paid order falls in a period.' },
      ],
      axioms: [statement('a1', 'Every order belongs to exactly one customer.'),
               statement('a2', 'A product listed without a price has never been sold.')],
      sources: [
        { id: 's1', kind: 'PostgreSQL', connection: 'sales' },
        { id: 's2', kind: 'CSV file', file: 'products.csv' },
      ],
      databaseEntities: [
        { id: 't1', sourceId: 's1', relation: 'public.customers' },
        { id: 't2', sourceId: 's1', relation: 'public.orders' },
        { id: 't3', sourceId: 's1', relation: 'public.order_lines' },
        { id: 't4', sourceId: 's1', relation: 'public.regions' },
        { id: 't5', sourceId: 's2', relation: 'products' },
      ],
      mappings: [
        { id: 'm1', entityId: 'c', databaseEntityId: 't1' },
        { id: 'm2', entityId: 'o', databaseEntityId: 't2' },
        { id: 'm3', entityId: 'l', databaseEntityId: 't3' },
        { id: 'm4', entityId: 'r', databaseEntityId: 't4' },
        { id: 'm5', entityId: 'p', databaseEntityId: 't5' },
      ],
    },
  }
}
