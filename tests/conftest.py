import pytest

from acquisition_analyst import AnalysisRequest


@pytest.fixture
def sample_request() -> AnalysisRequest:
    """Strong growth-stage vertical SaaS target with an exact benchmark cohort."""
    return AnalysisRequest(
        buyer_segment="growth_equity",
        thesis_tags=["vertical-saas"],
        price=None,
        return_target=25.0,
        hold_years=5,
        stage="growth",
        vertical="vertical_saas",
        size_band="25-50M",
        arr=25.2,
        arr_growth=52.0,
        nrr=118.0,
        grr=94.0,
        cac_payback_months=16.0,
        ltv_cac=3.8,
        magic_number=1.1,
        burn_multiple=0.7,
        gross_margin=76.0,
        ebitda_margin=-15.0,
        customer_concentration_top10_pct=32.0,
    )
