"""Lossless, portable declarative room instructions."""
from __future__ import annotations

from copy import deepcopy
from .engine import RoomSpec

SCHEMA = 'earnest.room-instructions.v1'

def make_instructions(document):
    RoomSpec.from_dict(document)
    return {'schema': SCHEMA, 'description': 'Apply each set instruction to a new room document, then validate.',
            'instructions': [{'operation': 'set', 'field': key, 'value': deepcopy(value)}
                             for key, value in document.items()]}

def apply_instructions(plan):
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA or not isinstance(plan.get('instructions'), list):
        raise ValueError('expected earnest.room-instructions.v1 instructions')
    document = {}
    for entry in plan['instructions']:
        if not isinstance(entry, dict) or entry.get('operation') != 'set' or not isinstance(entry.get('field'), str) or not entry['field'] or 'value' not in entry:
            raise ValueError('each instruction must set a named top-level field to a value')
        if entry['field'] in document:
            raise ValueError('duplicate instruction field: %s' % entry['field'])
        document[entry['field']] = deepcopy(entry['value'])
    RoomSpec.from_dict(document)
    return document
