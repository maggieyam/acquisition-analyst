from acquisition_analyst.scoring import validate


def test_valid_request_passes(sample_request):
    result = validate(sample_request)
    assert result.valid
    assert result.missing == []


def test_invalid_enum_fields_block(sample_request):
    req = sample_request.model_copy(update={"stage": "seed"})
    result = validate(req)
    assert not result.valid
    assert any("stage" in m for m in result.missing)


def test_nrr_below_grr_warns(sample_request):
    req = sample_request.model_copy(update={"nrr": 90.0, "grr": 94.0})
    result = validate(req)
    assert result.valid  # warning, not a block
    assert any("NRR" in w and "GRR" in w for w in result.warnings)


def test_out_of_range_metric_warns(sample_request):
    req = sample_request.model_copy(update={"arr_growth": 950.0})
    result = validate(req)
    assert result.valid
    assert any("arr_growth" in w for w in result.warnings)


def test_high_customer_concentration_warns(sample_request):
    req = sample_request.model_copy(update={"customer_concentration_top10_pct": 65.0})
    result = validate(req)
    assert any("concentration" in w.lower() for w in result.warnings)
