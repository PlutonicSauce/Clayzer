from clayzer.retrieval import hit_at_1


def _query(ranked, relevant):
    return {"query": "q", "ranked": ranked, "relevant": relevant}


def test_a_stored_hit_at_1_is_used_as_is():
    assert hit_at_1({"hit@1": 0.25, "queries": [_query(["a"], ["a"])]}) == 0.25


def test_an_older_row_gets_hit_at_1_from_its_rankings():
    # 30 solar Cases: the top result is one of them, so the search worked, though recall@1 is 1/30
    solar = [f"solar-{i}" for i in range(30)]
    row = {"recall@1": 1 / 30, "queries": [_query(solar + ["neg-1"], solar)]}
    assert hit_at_1(row) == 1.0


def test_queries_whose_top_result_is_wrong_count_against_it():
    row = {"queries": [_query(["a", "b"], ["a"]), _query(["a", "b"], ["b"])]}
    assert hit_at_1(row) == 0.5


def test_a_row_without_rankings_has_no_hit_at_1():
    assert hit_at_1({"queries": []}) is None
    assert hit_at_1({}) is None
