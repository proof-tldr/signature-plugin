"""The domain as the customer reviews it before publishing, drawn from Signature's model snapshot: each kind of
thing it knows about and what it records about it, the rules it holds to, and which data each thing comes from."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Section:
    title: str
    intro: str | None
    points: list[str]


@dataclass(frozen=True)
class Review:
    summary: str
    sections: list[Section]


def review_of(snapshot: dict[str, Any]) -> Review:
    entities: list[dict[str, Any]] = snapshot.get('entities', [])
    rules = [axiom['english'] for axiom in snapshot.get('axioms', [])]
    rules += [_function_rule(function) for function in snapshot.get('functions', [])]
    sections = [_entity_section(entity, snapshot) for entity in entities]
    if rules:
        sections.append(Section(title='Rules', intro=None, points=rules))
    origins = _origins(snapshot)
    if origins:
        sections.append(Section(title='Where the data comes from', intro=None, points=origins))
    return Review(summary=_summary(len(entities), len(rules), len(snapshot.get('sources', []))), sections=sections)


def _entity_section(entity: dict[str, Any], snapshot: dict[str, Any]) -> Section:
    fields = [field for field in snapshot.get('fields', []) if field['entityId'] == entity['id']]
    points = [_field_point(field) for field in fields]
    points += [invariant['english'] for invariant in entity.get('invariants', [])]
    return Section(title=entity.get('plural') or entity['name'], intro=entity.get('doc'), points=points)


def _field_point(field: dict[str, Any]) -> str:
    described = f': {field["doc"]}' if field.get('doc') else ''
    return f'{field["name"]} ({_type_name(field["type"])}){described}'


def _function_rule(function: dict[str, Any]) -> str:
    explanation = [function['doc']] if function.get('doc') else []
    explanation += [condition['english'] for condition in function.get('pre', []) + function.get('post', [])]
    return f'{function["name"]}: {" ".join(explanation)}'


def _origins(snapshot: dict[str, Any]) -> list[str]:
    entities = {entity['id']: entity['name'] for entity in snapshot.get('entities', [])}
    tables = {table['id']: table['relation'] for table in snapshot.get('databaseEntities', [])}
    return [
        f'{entities[mapping["entityId"]]} comes from {tables[mapping["databaseEntityId"]]}'
        for mapping in snapshot.get('mappings', [])
    ]


def _type_name(type_expression: dict[str, Any]) -> str:
    match type_expression:
        case {'kind': 'named', 'name': name}:
            return name
        case {'kind': 'optional', 'item': item}:
            return f'optional {_type_name(item)}'
        case {'kind': kind, 'item': item}:
            return f'{kind} of {_type_name(item)}'
        case {'kind': 'tuple', 'items': items}:
            return f'({", ".join(_type_name(item) for item in items)})'
        case _:
            return 'value'


def _summary(entities: int, rules: int, sources: int) -> str:
    return (
        f'Signature knows about {entities} kind{"s" if entities != 1 else ""} of thing, holds to {rules} '
        f'rule{"s" if rules != 1 else ""}, and draws on {sources} source{"s" if sources != 1 else ""}.'
    )
