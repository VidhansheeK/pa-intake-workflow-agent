import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import completeness, router  # noqa: E402

POLICIES = completeness.load_policies()


def make_packet(cpt="27447", urgency="standard"):
    return {"case_id": "PA-TEST", "request": {"procedure_cpt": cpt, "urgency": urgency}}


def test_no_pa_required_wins_over_everything():
    decision = router.route(make_packet(cpt="99213"), [{"code": "member_dob_missing"}], POLICIES)
    assert decision["queue"] == "no_auth_required"


def test_eligibility_beats_outreach():
    findings = [{"code": "member_not_found"}, {"code": "npi_invalid"}]
    assert router.route(make_packet(), findings, POLICIES)["queue"] == "eligibility_review"


def test_any_finding_routes_to_outreach():
    findings = [{"code": "diagnosis_missing"}]
    assert router.route(make_packet(), findings, POLICIES)["queue"] == "provider_outreach"


def test_complete_standard_routes_to_specialty():
    assert router.route(make_packet(), [], POLICIES)["queue"] == "clinical_review::musculoskeletal"
    assert router.route(make_packet(cpt="J0135"), [], POLICIES)["queue"] == "clinical_review::pharmacy"


def test_complete_expedited_routes_to_expedited_queue():
    decision = router.route(make_packet(cpt="93458", urgency="expedited"), [], POLICIES)
    assert decision["queue"] == "expedited_clinical_review::cardiology"


def test_duplicate_beats_eligibility_and_outreach():
    findings = [{"code": "possible_duplicate", "detail": "dup of PA-X"},
                {"code": "member_not_found"}, {"code": "npi_invalid"}]
    assert router.route(make_packet(), findings, POLICIES)["queue"] == "duplicate_review"
