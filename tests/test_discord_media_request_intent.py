"""Regression coverage for exact Discord outbound media request intent."""

from __future__ import annotations

import pytest

from alpecca import discord_media


@pytest.mark.parametrize(
    ("text", "expected_kind"),
    (
        ("Can you send your portrait?", "portrait"),
        ("!image gallery", "gallery"),
    ),
)
def test_explicit_outbound_image_requests_remain_recognized(
    text: str,
    expected_kind: str,
):
    assert discord_media.requested_media_kind(text) == expected_kind
    assert discord_media.requested_disabled_media_kind(text) is None


@pytest.mark.parametrize(
    "text",
    (
        "Let us post a photo later.",
        "We should send the project file tomorrow.",
        "We will send the audio recording after the review.",
        "The source file and audio clip are ready for the next meeting.",
    ),
)
def test_nonrequests_do_not_match_any_outbound_transport_intent(text: str):
    assert discord_media.requested_media_kind(text) is None
    assert discord_media.requested_disabled_media_kind(text) is None
