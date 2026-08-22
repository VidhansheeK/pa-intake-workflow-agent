"""Generate the synthetic PA intake dataset: members, packets, and golden labels.

Everything is fabricated. No real people, providers, or PHI. Deterministic
(fixed seed) so the dataset and golden labels are reproducible:

    python data/generate_packets.py
"""
import json
import random
from pathlib import Path

SEED = 42
DATA_DIR = Path(__file__).parent
PACKETS_DIR = DATA_DIR / "packets"

FIRST_NAMES = ["Asha", "Rohan", "Meera", "Kabir", "Nina", "Dev", "Sara", "Arjun",
               "Priya", "Vikram", "Tara", "Ishan", "Leela", "Omar", "Zoya"]
LAST_NAMES = ["Sharma", "Patel", "Rao", "Khan", "Iyer", "Das", "Mehta", "Singh",
              "Nair", "Bose", "Kaur", "Joshi", "Reddy", "Gupta", "Verma"]
PROVIDER_NAMES = ["Dr. A. Menon", "Dr. B. Kulkarni", "Dr. C. D'Souza", "Dr. D. Pillai",
                  "Dr. E. Chatterjee", "Dr. F. Bhat", "Dr. G. Saxena", "Dr. H. Thomas"]
PLANS = ["UHC Choice Plus", "UHC Navigate", "UHC Options PPO"]

# Clinical note fragments per CPT, keyed by policy requirement id. Notes are
# assembled from these; omitting one fragment creates a ground-truth
# "clinical_notes_insufficient" case.
NOTE_FRAGMENTS = {
    "27447": {
        "base": "58-year-old patient with chronic right knee pain worsening over 2 years.",
        "conservative_therapy": "Completed 4 months of physical therapy and daily NSAID (naproxen) with no lasting relief.",
        "imaging_findings": "Weight-bearing X-ray shows severe medial joint space narrowing, bone-on-bone contact.",
        "bmi_documented": "BMI 31.2.",
    },
    "64483": {
        "base": "Patient reports low back pain for 5 months.",
        "radicular_pain": "Pain is radicular, radiating down the left leg to the foot.",
        "conservative_therapy": "8 weeks of physical therapy and ibuprofen without improvement.",
        "imaging_correlation": "MRI lumbar spine shows L4-L5 disc herniation with foraminal stenosis on the left.",
    },
    "70553": {
        "base": "Patient presents with recurrent symptoms.",
        "neuro_symptoms": "Persistent headache with intermittent vision change and left arm numbness.",
        "duration_or_workup": "Symptoms persisting for 6 weeks; prior CT unremarkable, further workup indicated.",
    },
    "J0135": {
        "base": "Patient with progressive joint symptoms.",
        "confirmed_diagnosis": "Seropositive rheumatoid arthritis confirmed by rheumatology.",
        "first_line_failure": "Methotrexate 20mg weekly for 6 months with inadequate response.",
        "tb_screening": "Quantiferon TB screen negative this month.",
    },
    "93458": {
        "base": "Patient followed by cardiology.",
        "abnormal_testing": "Exertional chest pain; nuclear stress test shows reversible ischemia.",
        "current_medications": "Current medications: aspirin 81mg, atorvastatin (statin), metoprolol.",
    },
    "99213": {
        "base": "Routine follow-up visit for stable chronic condition.",
    },
}

EXPEDITED_JUSTIFICATION = ("Expedited review requested: delay poses imminent risk of "
                           "serious deterioration in the member's condition per the attending physician.")

rng = random.Random(SEED)


def npi_check_digit(first9: str) -> str:
    """Luhn check digit over '80840' + 9 digits (real NPI algorithm)."""
    digits = [int(d) for d in "80840" + first9]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:  # rightmost of the 14 gets doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def make_npi() -> str:
    first9 = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return first9 + npi_check_digit(first9)


def make_members(n=15):
    members = []
    for i in range(n):
        members.append({
            "member_id": f"M{100000000 + i * 7919}",
            "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "dob": f"{rng.randint(1950, 2000)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "plan": rng.choice(PLANS),
            "active": True,
        })
    return members


def make_notes(cpt: str, omit: str | None = None) -> str:
    frags = NOTE_FRAGMENTS[cpt]
    parts = [frags["base"]] + [v for k, v in frags.items() if k != "base" and k != omit]
    return " ".join(parts)


DIAGNOSES = {
    "27447": ("M17.11", "Unilateral primary osteoarthritis, right knee"),
    "64483": ("M54.16", "Radiculopathy, lumbar region"),
    "70553": ("R51.9", "Headache, unspecified"),
    "J0135": ("M05.79", "Rheumatoid arthritis with rheumatoid factor"),
    "93458": ("I25.10", "Atherosclerotic heart disease"),
    "99213": ("E11.9", "Type 2 diabetes mellitus without complications"),
}


def base_packet(case_num: int, cpt: str, member: dict, urgency="standard") -> dict:
    icd, icd_desc = DIAGNOSES[cpt]
    policies = json.loads((DATA_DIR / "policies.json").read_text())
    return {
        "case_id": f"PA-2026-{case_num:04d}",
        "received_at": f"2026-08-{rng.randint(15, 21):02d}T{rng.randint(8, 17):02d}:{rng.randint(0, 59):02d}:00",
        "channel": rng.choice(["portal", "fax", "phone"]),
        "member": {
            "member_id": member["member_id"],
            "name": member["name"],
            "dob": member["dob"],
            "plan": member["plan"],
        },
        "provider": {
            "npi": make_npi(),
            "name": rng.choice(PROVIDER_NAMES),
            "specialty": policies[cpt]["specialty_queue"] or "primary_care",
            "phone": f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
        },
        "request": {
            "procedure_cpt": cpt,
            "procedure_description": policies[cpt]["description"],
            "diagnosis_icd10": icd,
            "diagnosis_description": icd_desc,
            "urgency": urgency,
            "expedited_justification": EXPEDITED_JUSTIFICATION if urgency == "expedited" else None,
        },
        "clinical_notes": make_notes(cpt),
    }


def main():
    PACKETS_DIR.mkdir(exist_ok=True)
    for old in PACKETS_DIR.glob("PA-*.json"):
        old.unlink()

    members = make_members()
    (DATA_DIR / "members.json").write_text(json.dumps(members, indent=2))

    packets, labels = [], {}
    num = 0

    def add(packet, scenario, findings, route):
        nonlocal num
        packets.append(packet)
        labels[packet["case_id"]] = {
            "scenario": scenario,
            "expected_findings": sorted(findings),
            "expected_route": route,
        }

    def nxt():
        nonlocal num
        num += 1
        return num

    def queue(cpt, prefix="clinical_review"):
        policies = json.loads((DATA_DIR / "policies.json").read_text())
        return f"{prefix}::{policies[cpt]['specialty_queue']}"

    # 1. Complete, standard urgency — one per PA-required CPT (5)
    for cpt in ["27447", "64483", "70553", "J0135", "93458"]:
        p = base_packet(nxt(), cpt, rng.choice(members))
        add(p, "complete_standard", [], queue(cpt))

    # 2. Complete, expedited with justification (2)
    for cpt in ["93458", "70553"]:
        p = base_packet(nxt(), cpt, rng.choice(members), urgency="expedited")
        add(p, "complete_expedited", [], queue(cpt, "expedited_clinical_review"))

    # 3. Missing member ID (2)
    for cpt in ["27447", "J0135"]:
        p = base_packet(nxt(), cpt, rng.choice(members))
        p["member"]["member_id"] = None
        add(p, "missing_member_id", ["member_id_missing"], "provider_outreach")

    # 4. Member ID present but not found in eligibility (2)
    for cpt in ["64483", "93458"]:
        p = base_packet(nxt(), cpt, rng.choice(members))
        p["member"]["member_id"] = f"M{999000000 + num}"
        add(p, "member_not_found", ["member_not_found"], "eligibility_review")

    # 5. Invalid NPI (2)
    p = base_packet(nxt(), "70553", rng.choice(members))
    p["provider"]["npi"] = "12345"  # wrong length
    add(p, "invalid_npi", ["npi_invalid"], "provider_outreach")
    p = base_packet(nxt(), "27447", rng.choice(members))
    bad = p["provider"]["npi"]
    p["provider"]["npi"] = bad[:9] + str((int(bad[9]) + 1) % 10)  # break check digit
    add(p, "invalid_npi", ["npi_invalid"], "provider_outreach")

    # 6. Missing diagnosis (2)
    for cpt in ["64483", "J0135"]:
        p = base_packet(nxt(), cpt, rng.choice(members))
        p["request"]["diagnosis_icd10"] = None
        p["request"]["diagnosis_description"] = None
        add(p, "missing_diagnosis", ["diagnosis_missing"], "provider_outreach")

    # 7. Malformed ICD-10 (1)
    p = base_packet(nxt(), "93458", rng.choice(members))
    p["request"]["diagnosis_icd10"] = "25.10"  # dropped leading letter
    add(p, "invalid_icd10", ["diagnosis_invalid"], "provider_outreach")

    # 8. Clinical notes missing a required element (3)
    for cpt, omit in [("27447", "conservative_therapy"), ("J0135", "tb_screening"),
                      ("64483", "imaging_correlation")]:
        p = base_packet(nxt(), cpt, rng.choice(members))
        p["clinical_notes"] = make_notes(cpt, omit=omit)
        add(p, f"notes_missing_{omit}", ["clinical_notes_insufficient"], "provider_outreach")

    # 9. Expedited without justification (2)
    for cpt in ["27447", "93458"]:
        p = base_packet(nxt(), cpt, rng.choice(members), urgency="expedited")
        p["request"]["expedited_justification"] = None
        add(p, "expedited_no_justification", ["expedited_justification_missing"], "provider_outreach")

    # 10. CPT that does not require PA (2)
    for _ in range(2):
        p = base_packet(nxt(), "99213", rng.choice(members))
        add(p, "no_pa_required", [], "no_auth_required")

    # 11. Missing DOB (1)
    p = base_packet(nxt(), "70553", rng.choice(members))
    p["member"]["dob"] = None
    add(p, "missing_dob", ["member_dob_missing"], "provider_outreach")

    # 12. Multiple issues at once (1)
    p = base_packet(nxt(), "27447", rng.choice(members))
    p["member"]["member_id"] = None
    p["provider"]["npi"] = "abc"
    add(p, "multi_issue", ["member_id_missing", "npi_invalid"], "provider_outreach")

    # 13. Empty clinical notes entirely (1)
    p = base_packet(nxt(), "64483", rng.choice(members))
    p["clinical_notes"] = ""
    add(p, "empty_notes", ["clinical_notes_missing"], "provider_outreach")

    for p in packets:
        (PACKETS_DIR / f"{p['case_id']}.json").write_text(json.dumps(p, indent=2))
    (DATA_DIR / "golden_labels.json").write_text(json.dumps(labels, indent=2))
    print(f"Wrote {len(packets)} packets, {len(members)} members, {len(labels)} golden labels.")


if __name__ == "__main__":
    main()
