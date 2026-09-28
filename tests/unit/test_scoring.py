from app.memory.retrieval import compute_final_score, compute_mismatch_flags
from app.models import Cue


def test_scoring_formula():
    # Test formula: base = 0.35*vec + 0.15*fts + 0.20*fp + 0.15*svc + 0.15*code
    # final = base * weight * (0.85 + 0.30 * runbook_p)
    vec = 0.8
    fts = 0.6
    fp = 1.0
    svc = 1.0
    code = 0.0

    # base = 0.35*0.8 + 0.15*0.6 + 0.20*1.0 + 0.15*1.0 + 0.15*0.0
    # base = 0.28 + 0.09 + 0.20 + 0.15 + 0 = 0.72
    # final = 0.72 * 1.0 * (0.85 + 0.30*0.5) = 0.72 * 1.0 = 0.72
    final, flags = compute_final_score(
        vec=vec, fts=fts, fp=fp, svc=svc, code=code,
        incident_weight=1.0, runbook_p=0.5, fix_worked=True,
        w_vec=0.35, w_fts=0.15, w_fp=0.20, w_svc=0.15, w_code=0.15
    )
    assert round(final, 2) == 0.72
    assert "fix_did_not_work" not in flags


def test_scoring_fix_worked_false_penalty():
    final, flags = compute_final_score(
        vec=0.8, fts=0.6, fp=1.0, svc=1.0, code=0.0,
        incident_weight=1.0, runbook_p=0.5, fix_worked=False,
        w_vec=0.35, w_fts=0.15, w_fp=0.20, w_svc=0.15, w_code=0.15
    )
    # 0.72 * 0.7 = 0.504
    assert round(final, 3) == 0.504
    assert "fix_did_not_work" in flags


def test_mismatch_flags():
    cue = Cue(
        text="checkout-api latency spike",
        services=["checkout-api"],
        trigger_type="deploy"
    )

    # 1. Matching services and trigger
    flags = compute_mismatch_flags(
        cue=cue,
        inc_services=["checkout-api", "postgres-primary"],
        inc_trigger_type="deploy",
        inc_epoch=1,
        inc_weight=1.0,
    )
    assert flags == []

    # 2. Service mismatch
    flags_svc = compute_mismatch_flags(
        cue=cue,
        inc_services=["payments-gateway"],
        inc_trigger_type="deploy",
        inc_epoch=1,
        inc_weight=1.0,
    )
    assert "service_mismatch" in flags_svc

    # 3. Trigger mismatch
    flags_trig = compute_mismatch_flags(
        cue=cue,
        inc_services=["checkout-api"],
        inc_trigger_type="traffic_spike",
        inc_epoch=1,
        inc_weight=1.0,
    )
    assert "trigger_mismatch" in flags_trig

    # 4. Old flag when weight < 0.6
    flags_old = compute_mismatch_flags(
        cue=cue,
        inc_services=["checkout-api"],
        inc_trigger_type="deploy",
        inc_epoch=1,
        inc_weight=0.4,
    )
    assert "old" in flags_old
