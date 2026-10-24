from dse_knowledge.retrieval import reciprocal_rank_fusion

def test_fusion_deduplicates_and_is_order_invariant():
    a={'dense':[{'chunk_id':'a'},{'chunk_id':'b'}],'lexical':[{'chunk_id':'b'}]}
    x=reciprocal_rank_fusion(a)
    y=reciprocal_rank_fusion(dict(reversed(list(a.items()))))
    assert [i['chunk_id'] for i in x]==['b','a']==[i['chunk_id'] for i in y]
    assert set(x[0]['scores'])=={'dense','lexical'}
