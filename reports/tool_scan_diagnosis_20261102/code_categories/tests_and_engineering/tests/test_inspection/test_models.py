import json

import pytest

from anylabeling.services.inspection.models import (
    Decision,
    InspectionIssue,
    InspectionProfile,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    RuleConfig,
    VerificationState,
    canonical_relation_key,
)


def _profile() -> InspectionProfile:
    return InspectionProfile(
        profile_id="p1",
        name="Profile",
        description="desc",
        stage="post_label",
        rules=(RuleConfig("label_required"),),
        relations={canonical_relation_key("a", "b"): "mutually_exclusive"},
    )


def test_profile_round_trip_and_fingerprint_is_stable():
    profile = _profile()
    restored = InspectionProfile.from_dict(profile.to_dict())
    assert restored == profile
    assert restored.fingerprint() == profile.fingerprint()


def test_profile_rejects_unknown_stage():
    data = _profile().to_dict()
    data["stage"] = "unknown"
    with pytest.raises(ValueError):
        InspectionProfile.from_dict(data)


def test_profile_requires_identifier_and_name():
    data = _profile().to_dict()
    data["profile_id"] = ""
    with pytest.raises(ValueError):
        InspectionProfile.from_dict(data)
    data = _profile().to_dict()
    data["name"] = ""
    with pytest.raises(ValueError):
        InspectionProfile.from_dict(data)


def test_issue_round_trip_preserves_independent_states():
    issue = InspectionIssue(
        issue_id="i1",
        family_key="f1",
        title="title",
        message="message",
        severity=IssueSeverity.WARNING,
        location=IssueLocation(
            relative_path="a.jpg",
            object_ids=("id1", "id2"),
            region=(0, 0, 10, 10),
        ),
        evidence=(
            IssueEvidence(
                rule_id="duplicate_boxes",
                implementation_version="1.0.0",
                rule_name="dup",
                message="overlap",
            ),
        ),
        decision=Decision.FALSE_POSITIVE,
        verification=VerificationState.STALE,
    )
    restored = InspectionIssue.from_dict(issue.to_dict())
    assert restored.decision is Decision.FALSE_POSITIVE
    assert restored.verification is VerificationState.STALE
    assert restored.location.object_ids == ("id1", "id2")
    assert json.dumps(restored.to_dict(), ensure_ascii=False)


def test_canonical_relation_key_is_order_independent():
    assert canonical_relation_key("b", "a") == canonical_relation_key("a", "b")
