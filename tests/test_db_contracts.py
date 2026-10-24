import pytest
from dse_knowledge.db import vector_literal,identity

def test_vector_rejects_invalid():
    for value in ([0.0]*767,[float('nan')]*768,[True]*768):
        with pytest.raises(ValueError): vector_literal(value)

def test_identity_stable_and_separated():
    assert identity('a','bc')!=identity('ab','c')
    assert identity('a','b')==identity('a','b')
