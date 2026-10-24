import pytest
from dse_knowledge.pipeline import safe_material_id

@pytest.mark.parametrize('value',['/tmp/outside','../outside','..','a/b','a\\b',''])
def test_candidate_id_cannot_escape_cache(value):
    with pytest.raises(ValueError):safe_material_id(value)

def test_registered_material_id_is_preserved():
    assert safe_material_id('mat-32494794ad99fab9a2f68fe4')=='mat-32494794ad99fab9a2f68fe4'
