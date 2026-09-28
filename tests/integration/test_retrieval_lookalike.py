from app.memory.retrieval import compute_final_score
from app.models import Cue


def test_retrieval_lookalike_ranking():
    """
    Scenario D Look-alike test:
    checkout-api 503s and timeouts, but logs show 'no such host' for postgres-primary.
    The DNS incident must rank above the pool-exhaustion incident.
    """
    cue = Cue(
        text="checkout-api 503s connection timed out: dial tcp: lookup postgres-primary: no such host",
        services=["checkout-api"],
        error_messages=["dial tcp: lookup postgres-primary: no such host"],
    )

    # Simulated candidate 1: INC-0019 (DNS failure)
    # Has matching error message keywords and matching service
    dns_vec = 0.85
    dns_fts = 0.90
    dns_fp = 1.0  # exact fingerprint match
    dns_svc = 1.0
    dns_code = 0.0

    score_dns, flags_dns = compute_final_score(
        vec=dns_vec, fts=dns_fts, fp=dns_fp, svc=dns_svc, code=dns_code,
        incident_weight=1.0, runbook_p=0.5, fix_worked=True
    )

    # Simulated candidate 2: INC-0007 (Pool exhaustion)
    # Similar symptoms but different error message and fingerprint
    pool_vec = 0.70
    pool_fts = 0.30
    pool_fp = 0.0  # fingerprint mismatch
    pool_svc = 1.0
    pool_code = 0.0

    score_pool, flags_pool = compute_final_score(
        vec=pool_vec, fts=pool_fts, fp=pool_fp, svc=pool_svc, code=pool_code,
        incident_weight=1.0, runbook_p=0.5, fix_worked=True
    )

    # Assert DNS incident strictly outranks pool exhaustion
    assert cue.services == ["checkout-api"]
    assert score_dns > score_pool
    assert score_dns >= 0.70
