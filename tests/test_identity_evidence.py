from __future__ import annotations

from dataclasses import FrozenInstanceError
import math
import unittest

from alpecca.identity_evidence import (
    AuthorizationReason,
    AuthenticatedAccountEvidence,
    AuthenticatedDeviceEvidence,
    AuthenticatedSessionEvidence,
    Contradiction,
    EvidenceProvenance,
    EvidenceType,
    FaceFamiliarityEvidence,
    IdentityClaim,
    MAX_FAMILIARITY_FUSION_CONFIDENCE,
    TextFamiliarityEvidence,
    VoiceFamiliarityEvidence,
    authorize_creator,
    decide_creator_authorization,
    fuse_identity_evidence,
)


NOW = 10_000.0


def provenance(reference: str = "event-1") -> EvidenceProvenance:
    return EvidenceProvenance(
        source="house-hq",
        mechanism="local-verifier",
        reference=reference,
    )


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
        provenance=provenance(evidence_id),
    )


class EvidenceModelTests(unittest.TestCase):
    def test_defines_all_authentication_and_familiarity_types(self) -> None:
        expected = {
            AuthenticatedAccountEvidence: EvidenceType.AUTHENTICATED_ACCOUNT,
            AuthenticatedDeviceEvidence: EvidenceType.AUTHENTICATED_DEVICE,
            AuthenticatedSessionEvidence: EvidenceType.AUTHENTICATED_SESSION,
            VoiceFamiliarityEvidence: EvidenceType.VOICE_FAMILIARITY,
            FaceFamiliarityEvidence: EvidenceType.FACE_FAMILIARITY,
            TextFamiliarityEvidence: EvidenceType.TEXT_FAMILIARITY,
        }
        for evidence_class, evidence_type in expected.items():
            item = evidence(evidence_class, evidence_type.value)
            self.assertEqual(item.evidence_type, evidence_type)
            self.assertEqual(
                item.authorization_capable,
                evidence_type.value.startswith("authenticated_"),
            )

    def test_evidence_is_immutable_and_retains_provenance(self) -> None:
        item = evidence(AuthenticatedSessionEvidence, "session-1")
        with self.assertRaises(FrozenInstanceError):
            item.confidence = 0.2
        self.assertEqual(item.as_dict()["provenance"]["reference"], "session-1")

    def test_confidence_and_time_bounds_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            evidence(VoiceFamiliarityEvidence, "voice-high", confidence=1.01)
        with self.assertRaisesRegex(ValueError, "finite"):
            evidence(VoiceFamiliarityEvidence, "voice-nan", confidence=math.nan)
        with self.assertRaisesRegex(ValueError, "within 3600"):
            evidence(
                VoiceFamiliarityEvidence,
                "voice-long",
                observed_at=NOW,
                expires_at=NOW + 3601.0,
            )

    def test_create_derives_bounded_expiry(self) -> None:
        item = AuthenticatedSessionEvidence.create(
            evidence_id="session-create",
            claim=IdentityClaim.CREATOR,
            confidence=1.0,
            observed_at=NOW,
            ttl_seconds=60.0,
            provenance=provenance(),
        )
        self.assertEqual(item.expires_at, NOW + 60.0)
        with self.assertRaisesRegex(ValueError, "within 86400"):
            AuthenticatedSessionEvidence.create(
                evidence_id="session-too-long",
                claim=IdentityClaim.CREATOR,
                confidence=1.0,
                observed_at=NOW,
                ttl_seconds=86401.0,
                provenance=provenance(),
            )


class FusionTests(unittest.TestCase):
    def test_fusion_is_bounded_and_familiarity_is_capped(self) -> None:
        signals = [
            evidence(VoiceFamiliarityEvidence, "voice", confidence=0.99),
            evidence(FaceFamiliarityEvidence, "face", confidence=0.99),
            evidence(TextFamiliarityEvidence, "text", confidence=0.99),
        ]
        result = fuse_identity_evidence(signals, now=NOW)
        self.assertEqual(
            result.familiarity_creator_confidence,
            MAX_FAMILIARITY_FUSION_CONFIDENCE,
        )
        self.assertGreaterEqual(result.creator_confidence, 0.0)
        self.assertLessEqual(result.creator_confidence, 1.0)

    def test_expired_and_future_evidence_are_excluded(self) -> None:
        expired = evidence(
            AuthenticatedSessionEvidence,
            "expired",
            observed_at=NOW - 100.0,
            expires_at=NOW,
        )
        future = evidence(
            AuthenticatedSessionEvidence,
            "future",
            observed_at=NOW + 10.0,
            expires_at=NOW + 20.0,
        )
        result = fuse_identity_evidence([expired, future], now=NOW)
        self.assertEqual(result.active_evidence, ())
        self.assertEqual(result.expired_evidence_ids, ("expired",))
        self.assertEqual(result.future_evidence_ids, ("future",))

    def test_authentication_and_familiarity_contradictions_are_reported(self) -> None:
        result = fuse_identity_evidence(
            [
                evidence(AuthenticatedAccountEvidence, "account-creator"),
                evidence(
                    AuthenticatedDeviceEvidence,
                    "device-other",
                    claim=IdentityClaim.NOT_CREATOR,
                ),
                evidence(VoiceFamiliarityEvidence, "voice-creator"),
                evidence(
                    TextFamiliarityEvidence,
                    "text-other",
                    claim=IdentityClaim.NOT_CREATOR,
                ),
            ],
            now=NOW,
        )
        self.assertEqual(
            set(result.contradictions),
            {
                Contradiction.AUTHENTICATION_CLAIM_CONFLICT,
                Contradiction.FAMILIARITY_CLAIM_CONFLICT,
                Contradiction.CROSS_CHANNEL_CLAIM_CONFLICT,
            },
        )

    def test_conflicting_duplicate_id_is_excluded_and_marked(self) -> None:
        first = evidence(AuthenticatedSessionEvidence, "replayed")
        altered = evidence(
            AuthenticatedSessionEvidence,
            "replayed",
            claim=IdentityClaim.NOT_CREATOR,
        )
        result = fuse_identity_evidence([first, altered], now=NOW)
        self.assertEqual(result.active_evidence, ())
        self.assertEqual(result.duplicate_evidence_ids, ("replayed",))
        self.assertTrue(result.authentication_integrity_conflict)
        self.assertIn(Contradiction.DUPLICATE_EVIDENCE_ID, result.contradictions)

    def test_identical_duplicate_is_idempotent(self) -> None:
        item = evidence(AuthenticatedSessionEvidence, "same")
        result = fuse_identity_evidence([item, item], now=NOW)
        self.assertEqual(result.active_evidence, (item,))
        self.assertEqual(result.duplicate_evidence_ids, ())


class AuthorizationTests(unittest.TestCase):
    def test_each_authentication_type_can_authorize_creator(self) -> None:
        for evidence_class in (
            AuthenticatedAccountEvidence,
            AuthenticatedDeviceEvidence,
            AuthenticatedSessionEvidence,
        ):
            item = evidence(evidence_class, evidence_class.__name__)
            decision = decide_creator_authorization([item], now=NOW)
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.principal, "creator")
            self.assertEqual(
                decision.reason,
                AuthorizationReason.AUTHORIZED_BY_AUTHENTICATION,
            )
            self.assertEqual(decision.authorizing_evidence_ids, (item.evidence_id,))
            self.assertEqual(decision.provenance, (item.provenance,))
            self.assertEqual(decision.expires_at, item.expires_at)

    def test_biometric_and_style_similarity_never_authorize(self) -> None:
        signals = [
            evidence(VoiceFamiliarityEvidence, "voice", confidence=1.0),
            evidence(FaceFamiliarityEvidence, "face", confidence=1.0),
            evidence(TextFamiliarityEvidence, "text", confidence=1.0),
        ]
        decision = decide_creator_authorization(signals, now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, AuthorizationReason.NO_ACTIVE_AUTHENTICATION)
        self.assertEqual(decision.authorizing_evidence_ids, ())
        self.assertEqual(decision.provenance, ())

    def test_many_weak_authentication_records_fuse_but_must_reach_threshold(self) -> None:
        weak = [
            evidence(AuthenticatedDeviceEvidence, "device-a", confidence=0.5),
            evidence(AuthenticatedSessionEvidence, "session-a", confidence=0.5),
        ]
        denied = decide_creator_authorization(weak, now=NOW)
        allowed = decide_creator_authorization(
            weak,
            now=NOW,
            min_authentication_confidence=0.70,
        )
        self.assertAlmostEqual(denied.authentication_confidence, 0.75)
        self.assertEqual(
            denied.reason,
            AuthorizationReason.INSUFFICIENT_AUTHENTICATION_CONFIDENCE,
        )
        self.assertTrue(allowed.allowed)

    def test_authentication_contradiction_fails_closed(self) -> None:
        result = fuse_identity_evidence(
            [
                evidence(AuthenticatedSessionEvidence, "creator-session"),
                evidence(
                    AuthenticatedAccountEvidence,
                    "other-account",
                    claim=IdentityClaim.NOT_CREATOR,
                    confidence=0.2,
                ),
            ],
            now=NOW,
        )
        decision = authorize_creator(result)
        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            AuthorizationReason.AUTHENTICATION_CONTRADICTION,
        )

    def test_familiarity_contradiction_does_not_grant_or_revoke_auth(self) -> None:
        session = evidence(AuthenticatedSessionEvidence, "creator-session")
        conflicting_voice = evidence(
            VoiceFamiliarityEvidence,
            "unfamiliar-voice",
            claim=IdentityClaim.NOT_CREATOR,
        )
        decision = decide_creator_authorization(
            [session, conflicting_voice], now=NOW
        )
        self.assertTrue(decision.allowed)
        self.assertIn(
            Contradiction.CROSS_CHANNEL_CLAIM_CONFLICT,
            decision.contradictions,
        )
        self.assertEqual(decision.authorizing_evidence_ids, ("creator-session",))

    def test_expired_authentication_cannot_authorize(self) -> None:
        expired = evidence(
            AuthenticatedSessionEvidence,
            "expired-session",
            observed_at=NOW - 100.0,
            expires_at=NOW,
        )
        decision = decide_creator_authorization([expired], now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, AuthorizationReason.NO_ACTIVE_AUTHENTICATION)

    def test_conflicting_duplicate_authentication_fails_closed(self) -> None:
        first = evidence(AuthenticatedSessionEvidence, "duplicate")
        changed = evidence(
            AuthenticatedSessionEvidence,
            "duplicate",
            confidence=0.95,
        )
        decision = decide_creator_authorization([first, changed], now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            AuthorizationReason.AUTHENTICATION_INTEGRITY_CONFLICT,
        )

    def test_authenticated_non_creator_is_explicitly_denied(self) -> None:
        other = evidence(
            AuthenticatedAccountEvidence,
            "other-account",
            claim=IdentityClaim.NOT_CREATOR,
        )
        decision = decide_creator_authorization([other], now=NOW)
        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            AuthorizationReason.AUTHENTICATED_NOT_CREATOR,
        )


if __name__ == "__main__":
    unittest.main()
