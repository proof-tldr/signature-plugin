"""Real cases from the customer's own data for the review page, found on this machine: a few records of each thing
Signature knows about, and a few pairs for each relationship between two things. People judge concrete cases far
more reliably than general statements, and the rows never leave the machine.

The model snapshot says which table each thing is read from, by its name in the local DuckDB
(`catalog.schema.name`, as the plugin reported it), which columns identify a record and which column each detail
is read from; this turns that into small SELECTs over the local sources."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from signature_plugin.local_data import LocalData
from signature_plugin.sources import Source

PER_ITEM = 3
NAMING_FIELDS = ('name', 'title', 'label', 'full_name', 'display_name')


@dataclass(frozen=True)
class Placed:
    """A thing's records in the local sources: the table, the identity column other records refer to it by, and
    how a person would call one record: its name column if it has one, else the thing's name and its identity."""

    table: str
    identity: str
    naming: str | None
    noun: str

    def label(self, alias: str) -> str:
        if self.naming:
            return f'CAST({alias}.{self.naming} AS VARCHAR)'
        return f"'{self.noun} ' || CAST({alias}.{self.identity} AS VARCHAR)"


def examples_of(snapshot: dict[str, Any], local: LocalData, sources: Sequence[Source]) -> dict[str, Any]:
    """{things: {entity id: [labels]}, links: {field id: [[from label, to label]]}}, as far as the local data
    answers; a thing or relationship whose records cannot be found has no examples."""
    places = _places(snapshot)
    entities = {entity['name']: entity['id'] for entity in snapshot.get('entities', [])}
    thing_queries = {entity_id: _records(place) for entity_id, place in places.items()}
    link_queries: dict[str, str] = {}
    columns = _field_columns(snapshot)
    for field in snapshot.get('fields', []):
        owner, target = places.get(field['entityId']), places.get(entities.get(_leaf(field['type']) or '', ''))
        column = columns.get(field['id'])
        if owner and target and column and field['type'].get('kind') in ('named', 'optional'):
            link_queries[field['id']] = (
                f'SELECT {owner.label("o")}, {target.label("t")} FROM {owner.table} o '
                f'JOIN {target.table} t ON CAST(o.{_quoted(column)} AS VARCHAR) = CAST(t.{target.identity} AS VARCHAR) '
                f'LIMIT {PER_ITEM}'
            )
    results = local.run_each(sources, [*thing_queries.values(), *link_queries.values()])
    thing_results, link_results = results[: len(thing_queries)], results[len(thing_queries) :]
    return {
        'things': {
            entity_id: [str(row[0]) for row in result.rows]
            for entity_id, result in zip(thing_queries, thing_results, strict=True)
            if result and result.rows
        },
        'links': {
            field_id: [[str(row[0]), str(row[1])] for row in result.rows]
            for field_id, result in zip(link_queries, link_results, strict=True)
            if result and result.rows
        },
    }


def _records(place: Placed) -> str:
    label = place.label('t')
    return f'SELECT DISTINCT {label} FROM {place.table} t WHERE {label} IS NOT NULL LIMIT {PER_ITEM}'


def _places(snapshot: dict[str, Any]) -> dict[str, Placed]:
    tables = {table['id']: table for table in snapshot.get('databaseEntities', [])}
    columns = {column['id']: _column_name(column) for column in snapshot.get('columns', [])}
    fields = {field['id']: field for field in snapshot.get('fields', [])}
    entity_names = {entity['id']: entity['name'] for entity in snapshot.get('entities', [])}
    naming = _naming_columns(snapshot, fields, columns)
    places: dict[str, Placed] = {}
    for mapping in snapshot.get('mappings', []):
        table = tables.get(mapping['databaseEntityId'])
        identity = [columns[part['columnId']] for part in mapping.get('identity', []) if part['columnId'] in columns]
        if not table or not identity or mapping['entityId'] in places:
            continue
        named_by = naming.get(mapping['id'])
        places[mapping['entityId']] = Placed(
            table='.'.join(_quoted(part) for part in table['relation'].split('.')),
            identity=_quoted(identity[0]),
            naming=_quoted(named_by) if named_by else None,
            noun=_words(entity_names[mapping['entityId']]).replace("'", "''"),
        )
    return places


def _naming_columns(
    snapshot: dict[str, Any], fields: dict[str, dict[str, Any]], columns: dict[str, str]
) -> dict[str, str]:
    """For each mapping, the column holding the field a person would call a record by, such as its name."""
    naming: dict[str, str] = {}
    for mapped in snapshot.get('mappingFields', []):
        field = fields.get(mapped['target'].get('fieldId', ''))
        if field and field['name'].lower() in NAMING_FIELDS and mapped['columnId'] in columns:
            naming.setdefault(mapped['mappingId'], columns[mapped['columnId']])
    return naming


def _field_columns(snapshot: dict[str, Any]) -> dict[str, str]:
    columns = {column['id']: _column_name(column) for column in snapshot.get('columns', [])}
    return {
        mapped['target']['fieldId']: columns[mapped['columnId']]
        for mapped in snapshot.get('mappingFields', [])
        if mapped['target'].get('kind') == 'field' and mapped['columnId'] in columns
    }


def _column_name(column: dict[str, Any]) -> str:
    storage = column.get('storage', {})
    return storage.get('column') or column['name']


def _leaf(type_expression: dict[str, Any]) -> str | None:
    if type_expression.get('kind') == 'named':
        return type_expression['name']
    item: dict[str, Any] | None = type_expression.get('item')
    return _leaf(item) if item else None


def _words(name: str) -> str:
    spaced = ''.join(f' {char}' if char.isupper() else char for char in name).replace('_', ' ').strip()
    return spaced[:1].upper() + spaced[1:].lower()


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
