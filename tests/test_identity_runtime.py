from __future__ import annotations

import unittest

from alpecca.identity_evidence import (
    AuthorizationReason,
    AuthenticatedAccountEvidence,
    AuthenticatedDeviceEvidence,
    AuthenticatedSessionEvidence,
    Contradiction,
    EvidenceProvenance,
    FaceFamiliarityEvidence,
    IdentityClaim,
    TextFamiliarityEvidence,
    VoiceFamiliarityEvidence,
)
from alpecca.identity_runtime import (
    IdentityRuntimeAdapter,
    MAX_AUTHENTICATION_EVIDENCE,
    PersonalizationReason,
    RuntimeIdentityStatus,
    evaluate_identity_runtime,
)


NOW = 20_000.0


def evidence(
    cls,
    evidence_id: str,
    *,
    claim: IdentityClaim = IdentityClaim.CREATOR,
    confidence: float = 1.0,
    observed_at: float = NOW - 10.0,
    expires_at: float = NOW + 300.0,
):
    return cls(
        evidence_id=evidence_id,
        claim=claim,
        confidence=confidence,
        observed_at=observed_at,
        expires_at=expires_at,
        provenance=EvidenceProvenance(
            source="house-hq",
            mechanism="signed-local-verifier",
            reference=evidence_id,
        ),
    )


class IdentityRuntimeAuthorizationTests(unittest.TestCase):
    def test_verified_account_device_and_session_can_authorize(self) -> None:
        for evidence_class in (
            AuthenticatedAccountEvidence,
            AuthenticatedDeviceEvidence,
            AuthenticatedSessionEvidence,
        ):
            item = evidence(evidence_class, evidence_class.__name__)
            result = evaluate_identity_runtime(
                authentication_evidence=[item], now=NOW
            )
            self.assertEqual(result.status, RuntimeIdentityStatus.AUTHENTICATED_CREATOR)
            self.assertTrue(result.creator_actions_authorized)
            self.assertTrue(result.creator_authenticated)
            self.assertTrue(result.may_execute_creator_action())
            self.assertEqual(
                result.authorization_reason,
                AuthorizationReason.AUTHORIZED_BY_AUTHENTICATION,
            )
            self.assertEqual(result.authorization_expires_at, item.expires_at)

    def test_face_voice_and_text_can_personalize_but_never_authenticate(self) -> None:
        for evidence_class in (
            FaceFamiliarityEvidence,
            VoiceFamiliarityEvidence,
            TextFamiliarityEvidence,
        ):
            item = evidence(evidence_class, evidence_class.__name__)
            result = evaluate_identity_runtime(
                familiarity_evidence=[item], now=NOW
            )
            self.assertEqual(result.status, RuntimeIdentityStatus.FAMILIAR_CREATOR)
            self.assertFalse(result.creator_actions_authorized)
            self.assertFalse(result.creator_authenticated)
            self.assertFalse(result.may_execute_creator_action())
            self.assertTrue(result.may_personalize_for_creator())
            self.assertEqual(
                result.authorization_reason,
                AuthorizationReason.NO_ACTIVE_AUTHENTICATION,
            )
            self.assertEqual(
                result.personalization_reason,
                PersonalizationReason.FAMILIARITY_THRESHOLD_MET,
            )

    def test_weak_familiarity_neither_authenticates_nor_personalizes(self) -> None:
        result = evaluate_identity_runtime(
            familiarity_evidence=[
                evidence(FaceFamiliarityEvidence, "weak-face", confidence=0.4)
            ],
            now=NOW,
        )
        self.assertEqual(result.status, RuntimeIdentityStatus.UNRECOGNIZED)
        self.assertFalse(result.creator_actions_authorized)
        self.assertFalse(result.personalization_allowed)
        self.assertEqual(
            result.personalization_reason,
            PersonalizationReason.INSUFFICIENT_FAMILIARITY,
        )

    def test_low_authentication_plus_familiarity_still_cannot_authorize(self) -> None:
        result = evaluate_identity_runtime(
            authentication_evidence=[
                evidence(AuthenticatedSessionEvidence, "weak-session", confidence=0.2)
            ],
            familiarity_evidence=[
                evidence(FaceFamiliarityEvidence, "strong-face", confidence=1.0)
            ],
            now=NOW,
        )
        self.assertFalse(result.creator_actions_authorized)
        self.assertTrue(result.personalization_allowed)
        self.assertEqual(
            result.authorization_reason,
            AuthorizationReason.INSUFFICIENT_AUTHENTICATION_CONFIDENCE,
        )
        self.assertAlmostEqual(result.authentication_confidence, 0.2)

    def test_authenticated_not_creator_blocks_creator_personalization(self) -> None:
        result = evaluate_identity_runtime(
            authentication_evidence=[
                evidence(
                    AuthenticatedAccountEvidence,
                    "other-account",
                    claim=IdentityClaim.NOT_CREATOR,
                )
            ],
            familiarity_evidence=[
                evidence(FaceFamiliarityEvidence, "creator-face")
            ],
            now=NOW,
        )
        self.assertEqual(result.status, RuntimeIdentityStatus.AUTHENTICATION_DENIED)
        self.assertFalse(result.creator_actions_authorized)
        self.assertFalse(result.personalization_allowed)
        self.assertEqual(
            result.personalization_reason,
            PersonalizationReason.AUTHENTICATED_NOT_CREATOR,
        )

    def test_authentication_contradiction_fails_closed(self) -> None:
        result = evaluate_identity_runtime(
            authentication_evidence=[
                evidence(AuthenticatedSessionEvidence, "creator-session"),
                evidence(
                    AuthenticatedAccountEvidence,
                    "other-account",
                    claim=IdentityClaim.NOT_CREATOR,
                ),
            ],
            now=NOW,
        )
        self.assertEqual(result.status, RuntimeIdentityStatus.CONTRADICTORY)
        self.assertFalse(result.creator_actions_authorized)
        self.assertFalse(result.personalization_allowed)
        self.assertIn(
            Contradiction.AUTHENTICATION_CLAIM_CONFLICT,
            result.contradictions,
        )


class IdentityRuntimeBoundaryTests(unittest.TestCase):
    def test_channels_reject_misclassified_evidence(self) -> None:
        with self.assertRaisesRegex(TypeError, "non-authentication"):
            evaluate_identity_runtime(
                authentication_evidence=[
                    evidence(FaceFamiliarityEvidence, "face-in-auth-channel")
                ],
                now=NOW,
            )
        with self.assertRaisesRegex(TypeError, "non-familiarity"):
            evaluate_identity_runtime(
                familiarity_evidence=[
                    evidence(AuthenticatedSessionEvidence, "session-in-face-channel")
                ],
                now=NOW,
            )

    def test_runtime_evidence_count_is_bounded(self) -> None:
        records = [
            evidence(
                AuthenticatedSessionEvidence,
                f"session-{index}",
                confidence=0.0,
            )
            for index in range(MAX_AUTHENTICATION_EVIDENCE + 1)
        ]
        with self.assertRaisesRegex(ValueError, "32-record runtime limit"):
            evaluate_identity_runtime(authentication_evidence=records, now=NOW)

    def test_expired_evidence_is_explained_and_has_no_runtime_authority(self) -> None:
        expired = evidence(
            AuthenticatedSessionEvidence,
            "expired-session",
            observed_at=NOW - 100.0,
            expires_at=NOW,
        )
        result = evaluate_identity_runtime(
            authentication_evidence=[expired], now=NOW
        )
        self.assertEqual(result.status, RuntimeIdentityStatus.UNRECOGNIZED)
        self.assertFalse(result.creator_actions_authorized)
        self.assertEqual(result.expired_evidence_ids, ("expired-session",))
        self.assertEqual(result.active_evidence_count, 0)

    def test_duplicate_authentication_integrity_conflict_is_visible(self) -> None:
        first = evidence(AuthenticatedSessionEvidence, "duplicate", confidence=1.0)
        changed = evidence(AuthenticatedSessionEvidence, "duplicate", confidence=0.95)
        result = evaluate_identity_runtime(
            authentication_evidence=[first, changed], now=NOW
        )
        self.assertEqual(result.status, RuntimeIdentityStatus.CONTRADICTORY)
        self.assertFalse(result.creator_actions_authorized)
        self.assertEqual(result.duplicate_evidence_ids, ("duplicate",))
        self.assertIn(Contradiction.DUPLICATE_EVIDENCE_ID, result.contradictions)

    def test_familiarity_contradiction_prevents_personalization_only(self) -> None:
        result = evaluate_identity_runtime(
            familiarity_evidence=[
                evidence(FaceFamiliarityEvidence, "face-creator"),
                evidence(
                    VoiceFamiliarityEvidence,
                    "voice-other",
                    claim=IdentityClaim.NOT_CREATOR,
                ),
            ],
            now=NOW,
        )
        self.assertFalse(result.creator_actions_authorized)
        self.assertFalse(result.personalization_allowed)
        self.assertEqual(
            result.personalization_reason,
            PersonalizationReason.FAMILIARITY_CONTRADICTION,
        )

    def test_provenance_and_status_are_bounded_and_explainable(self) -> None:
        session = evidence(AuthenticatedSessionEvidence, "signed-session")
        face = evidence(FaceFamiliarityEvidence, "face-match", confidence=0.8)
        result = evaluate_identity_runtime(
            authentication_evidence=[session],
            familiarity_evidence=[face],
            now=NOW,
        )
        payload = result.as_dict()
        self.assertEqual(payload["submitted_evidence_count"], 2)
        self.assertEqual(payload["active_evidence_count"], 2)
        self.assertLessEqual(len(payload["provenance"]), 64)
        self.assertEqual(
            {item["channel"] for item in payload["provenance"]},
            {"verified_authentication", "familiarity"},
        )
        self.assertEqual(payload["status_expires_at"], session.expires_at)
        self.assertTrue(
            any("never authenticates" in text for text in payload["explanations"])
        )

    def test_configured_adapter_applies_separate_thresholds(self) -> None:
        adapter = IdentityRuntimeAdapter(
            min_authentication_confidence=0.95,
            min_personalization_confidence=0.75,
        )
        result = adapter.evaluate(
            authentication_evidence=[
                evidence(AuthenticatedDeviceEvidence, "device", confidence=0.9)
            ],
            familiarity_evidence=[
                evidence(TextFamiliarityEvidence, "text", confidence=0.8)
            ],
            now=NOW,
        )
        self.assertFalse(result.creator_actions_authorized)
        self.assertTrue(result.personalization_allowed)
        self.assertEqual(result.authentication_threshold, 0.95)
        self.assertEqual(result.personalization_threshold, 0.75)

    def test_no_evidence_has_explicit_bounded_status(self) -> None:
        result = evaluate_identity_runtime(now=NOW)
        self.assertEqual(result.status, RuntimeIdentityStatus.NO_EVIDENCE)
        self.assertFalse(result.creator_actions_authorized)
        self.assertFalse(result.personalization_allowed)
        self.assertEqual(result.provenance, ())
        self.assertIsNone(result.status_expires_at)


if __name__ == "__main__":
    unittest.main()
