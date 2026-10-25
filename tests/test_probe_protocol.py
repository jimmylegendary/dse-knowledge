import importlib.util
import json
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[1] / 'scripts' / 'evaluate-decision-probes.py'
spec = importlib.util.spec_from_file_location('probe_protocol', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_expected_labels_and_source_qrels_never_enter_model_payload():
    case = {'id': 'neg-hidden-label-sentinel', 'answerability': 'unsupported',
            'expected_material_ids': ['gold-source-sentinel'],
            'query': 'What is known about this workload?',
            'input': {'expected_status': 'insufficient_evidence'},
            'reason': 'private-gold-rationale'}
    payload = module.build_probe_payload(case)
    assert payload == {'kind': 'knowledge', 'question': case['query'], 'input': {}}
    serialized = json.dumps(payload)
    assert all(value not in serialized for value in ['neg-hidden-label-sentinel', 'unsupported',
        'gold-source-sentinel', 'insufficient_evidence', 'private-gold-rationale'])


def test_all_answerability_classes_use_the_same_model_visible_kind_and_input():
    for label in ['answerable', 'unsupported']:
        payload = module.build_probe_payload({'query': 'A factual question?', 'answerability': label})
        assert payload['kind'] == 'knowledge'
        assert payload['input'] == {}


@pytest.mark.parametrize('query', ['', '  ', None, 'x' * 4001])
def test_probe_question_contract_is_bounded(query):
    with pytest.raises(ValueError):
        module.build_probe_payload({'query': query})


def test_outer_whitespace_cannot_bypass_the_model_visible_question_bound():
    payload = module.build_probe_payload({'query': ' ' * 5000 + 'A factual question?  '})
    assert payload['question'] == 'A factual question?'
