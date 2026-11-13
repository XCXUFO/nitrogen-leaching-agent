import pytest
from fastapi import HTTPException

from src.api.literature import validate_tag_selection
from src.api.literature_tagging import available_taxonomy, merge_tag_suggestions
from src.agent.tag_matching import TagIndex
from src.utils.taxonomy import enabled_tag_ids


def test_effective_tag_availability_handles_missing_ancestors_cycles_and_dimensions():
    taxonomy = {'dimensions': [{'id': 'on', 'enabled': True}, {'id': 'off', 'enabled': False}], 'tags': [
        {'id': 'root', 'dimension_id': 'on', 'enabled': False, 'parent_id': None},
        {'id': 'child', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'root'},
        {'id': 'leaf', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'child'},
        {'id': 'orphan', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'missing'},
        {'id': 'cycle-a', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'cycle-b'},
        {'id': 'cycle-b', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'cycle-a'},
        {'id': 'other-dimension', 'dimension_id': 'off', 'enabled': True, 'parent_id': None},
        {'id': 'cross-dimension', 'dimension_id': 'on', 'enabled': True, 'parent_id': 'other-dimension'},
        {'id': 'valid', 'dimension_id': 'on', 'enabled': True, 'parent_id': None, 'name': '有效标签'},
    ]}
    assert enabled_tag_ids(taxonomy) == {'valid'}
    assert {item['id'] for item in available_taxonomy(taxonomy)['tags']} == {'valid'}
    assert TagIndex(taxonomy, {'entries': []}, {}).enabled == {'valid'}
    assert merge_tag_suggestions(taxonomy, [], ['child', 'leaf', 'orphan']) == []


def test_inactive_previous_label_cannot_satisfy_a_required_dimension():
    taxonomy = {'dimensions': [{'id': 'd', 'name': '主题', 'enabled': True, 'selection': 'multiple', 'required': True}],
                'tags': [{'id': 'parent', 'dimension_id': 'd', 'enabled': False, 'parent_id': None},
                         {'id': 'child', 'dimension_id': 'd', 'enabled': True, 'parent_id': 'parent'}]}
    class Catalog:
        def taxonomy(self): return taxonomy
        def descendants(self, identifier, tags): return {identifier}

    validate_tag_selection(Catalog(), ['child'], previous=['child'])
    with pytest.raises(HTTPException) as error:
        validate_tag_selection(Catalog(), ['child'], previous=['child'], require_dimensions=True)
    assert error.value.detail['code'] == 'required_tag'
