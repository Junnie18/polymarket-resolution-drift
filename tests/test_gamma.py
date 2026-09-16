from polydrift.gamma import parse_outcomes, winning_outcome_index


def test_parse_outcomes_basic():
    market = {
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.98", "0.02"]',
        "clobTokenIds": '["111", "222"]',
    }
    parsed = parse_outcomes(market)
    assert parsed["outcomes"] == ["Yes", "No"]
    assert parsed["outcome_prices"] == ["0.98", "0.02"]
    assert parsed["clob_token_ids"] == ["111", "222"]


def test_parse_outcomes_malformed():
    market = {"outcomes": "not json", "outcomePrices": None, "clobTokenIds": '["1"]'}
    parsed = parse_outcomes(market)
    assert parsed["outcomes"] == []
    assert parsed["outcome_prices"] == []
    assert parsed["clob_token_ids"] == ["1"]


def test_winning_outcome_index_clear_winner():
    market = {"outcomePrices": '["0.995", "0.005"]'}
    assert winning_outcome_index(market) == 0

    market2 = {"outcomePrices": '["0.01", "0.99"]'}
    assert winning_outcome_index(market2) == 1


def test_winning_outcome_index_unsettled():
    market = {"outcomePrices": '["0.55", "0.45"]'}
    assert winning_outcome_index(market) is None


def test_winning_outcome_index_missing():
    assert winning_outcome_index({}) is None
