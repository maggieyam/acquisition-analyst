import pytest

from acquisition_analyst import AnalysisRequest, EngagementContext


@pytest.fixture
def sample_engagement() -> EngagementContext:
    return EngagementContext(
        buyer_label="Test Buyer",
        weights={
            "arr_growth": 0.20, "nrr": 0.15, "rule_of_40": 0.10,
            "magic_number": 0.10, "burn_multiple": 0.10, "gross_margin": 0.10,
            "ltv_cac": 0.10, "grr": 0.05, "cac_payback_months": 0.05,
            "ebitda_margin": 0.05,
        },
    )


@pytest.fixture
def sample_request() -> AnalysisRequest:
    """Strong growth-stage vertical SaaS target with an exact benchmark cohort."""
    return AnalysisRequest(
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
