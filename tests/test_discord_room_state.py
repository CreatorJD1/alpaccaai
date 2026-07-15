from __future__ import annotations

import pytest

from alpecca.discord_room_state import (
    RoomTurn,
    autonomous_speech_allowed,
    bounded_recent_turns,
    count_human_turns_after_latest_self,
    has_close_self_repeat,
    human_turn_supports_autonomy,
    is_bot_or_self_author,
    is_human_turn,
    is_self_author,
    normalize_author_identity,
    normalize_room_text,
)


SELF_ALIASES = (9001, "Alpecca_ai", "Alpecca")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        (9001, "9001"),
        (" <@!9001> ", "9001"),
        (" @Alpecca_AI ", "alpecca_ai"),
        ("\uff21lpecca   AI", "alpecca ai"),
    ],
)
def test_normalize_author_identity_is_stable_and_presentation_only(
    raw: object | None,
    expected: str,
) -> None:
    assert normalize_author_identity(raw) == expected


def test_self_identity_uses_exact_normalized_aliases() -> None:
    assert is_self_author("<@9001>", SELF_ALIASES)
    assert is_self_author("@ALPECCA_AI", SELF_ALIASES)
    assert is_self_author("alpecca", SELF_ALIASES)
    assert not is_self_author("alpecca-ai", SELF_ALIASES)
    assert not is_self_author(None, SELF_ALIASES)


def test_bot_or_self_detection_and_human_turn_classification_fail_closed() -> None:
    assert is_bot_or_self_author(
        "status_bot",
        is_bot=True,
        self_aliases=SELF_ALIASES,
    )
    assert is_bot_or_self_author(
        "Alpecca_ai",
        is_bot=False,
        self_aliases=SELF_ALIASES,
    )
    assert not is_bot_or_self_author(
        "creatorjd",
        is_bot=False,
        self_aliases=SELF_ALIASES,
    )
    assert is_human_turn(RoomTurn(author="creatorjd"), self_aliases=SELF_ALIASES)
    assert not is_human_turn(
        RoomTurn(author="other_bot", is_bot=True),
        self_aliases=SELF_ALIASES,
    )
    assert not is_human_turn(RoomTurn(author=None), self_aliases=SELF_ALIASES)


def test_count_human_turns_after_latest_self_ignores_other_bots() -> None:
    turns = [
        RoomTurn(author="creatorjd"),
        RoomTurn(author="other_bot", is_bot=True),
        RoomTurn(author="<@9001>", is_bot=True),
        RoomTurn(author="creatorjd"),
        RoomTurn(author="other_bot", is_bot=True),
        RoomTurn(author="reviewer"),
    ]

    assert count_human_turns_after_latest_self(turns, self_aliases=SELF_ALIASES) == 2


def test_count_human_turns_after_latest_self_counts_humans_when_self_has_not_spoken() -> None:
    turns = [
        RoomTurn(author="creatorjd"),
        RoomTurn(author="other_bot", is_bot=True),
        RoomTurn(author="reviewer"),
    ]

    assert count_human_turns_after_latest_self(turns, self_aliases=SELF_ALIASES) == 2


@pytest.mark.parametrize(
    ("turns", "expected"),
    [
        ([RoomTurn(author="creatorjd")], True),
        (
            [
                RoomTurn(author="creatorjd"),
                RoomTurn(author="Alpecca", is_bot=True),
            ],
            False,
        ),
        (
            [
                RoomTurn(author="Alpecca", is_bot=True),
                RoomTurn(author="other_bot", is_bot=True),
            ],
            False,
        ),
        (
            [
                RoomTurn(author="Alpecca", is_bot=True),
                RoomTurn(author="creatorjd"),
            ],
            True,
        ),
        ([], False),
    ],
)
def test_autonomous_speech_requires_a_newer_human_turn(
    turns: list[RoomTurn],
    expected: bool,
) -> None:
    assert autonomous_speech_allowed(turns, self_aliases=SELF_ALIASES) is expected


def test_bounded_recent_turns_keeps_only_the_newest_room_evidence() -> None:
    turns = [RoomTurn(author=f"person-{index}") for index in range(6)]

    assert bounded_recent_turns(turns, limit=3) == tuple(turns[-3:])


@pytest.mark.parametrize(
    ("turns", "expected"),
    [
        ([RoomTurn(author="creatorjd")], True),
        (
            [
                RoomTurn(author="creatorjd"),
                RoomTurn(author="Alpecca", is_bot=True),
            ],
            True,
        ),
        (
            [
                RoomTurn(author="creatorjd"),
                RoomTurn(author="Alpecca", is_bot=True),
                RoomTurn(author="Alpecca_ai", is_bot=True),
            ],
            False,
        ),
        (
            [
                RoomTurn(author="other_bot", is_bot=True),
                RoomTurn(author="Alpecca", is_bot=True),
            ],
            False,
        ),
    ],
)
def test_human_turn_supports_at_most_one_grounded_self_followup(
    turns: list[RoomTurn],
    expected: bool,
) -> None:
    assert human_turn_supports_autonomy(
        turns,
        self_aliases=SELF_ALIASES,
    ) is expected


def test_old_human_turn_cannot_authorize_from_outside_bounded_window() -> None:
    turns = [RoomTurn(author="creatorjd")] + [
        RoomTurn(author="Alpecca", content=f"self turn {index}", is_bot=True)
        for index in range(4)
    ]

    assert not human_turn_supports_autonomy(
        turns,
        self_aliases=SELF_ALIASES,
        recent_limit=3,
        max_self_turns_after_human=4,
    )


def test_normalize_room_text_ignores_mentions_punctuation_and_case() -> None:
    assert (
        normalize_room_text("@Alpecca_ai: Heel-contact -- looks GREAT!")
        == "heel contact looks great"
    )


def test_close_self_repeat_detects_exact_normalized_message_even_when_short() -> None:
    turns = [RoomTurn(author="Alpecca", content="Yes!")]

    assert has_close_self_repeat("yes", turns, self_aliases=SELF_ALIASES)


def test_close_self_repeat_detects_substantial_near_duplicate_by_similarity() -> None:
    prior = "Could we compare the heel contacts before changing the gait timing?"
    candidate = "Could we compare the heel contact before changing gait timing?"
    turns = [RoomTurn(author="Alpecca_ai", content=prior, is_bot=True)]

    assert has_close_self_repeat(candidate, turns, self_aliases=SELF_ALIASES)


def test_close_self_repeat_detects_substantial_containment() -> None:
    prior = "The right foot should stay planted until the weight transfer begins."
    candidate = prior + " Please."
    turns = [RoomTurn(author=9001, content=prior, is_bot=True)]

    assert has_close_self_repeat(candidate, turns, self_aliases=SELF_ALIASES)


def test_close_self_repeat_ignores_human_text_and_short_nonidentical_text() -> None:
    turns = [
        RoomTurn(author="creatorjd", content="Please compare the heel contact."),
        RoomTurn(author="Alpecca", content="yeah"),
    ]

    assert not has_close_self_repeat(
        "Please compare the heel contact.",
        turns,
        self_aliases=SELF_ALIASES,
    )
    assert not has_close_self_repeat("yes", turns, self_aliases=SELF_ALIASES)


def test_close_self_repeat_leaves_distinct_long_messages_available() -> None:
    turns = [
        RoomTurn(
            author="Alpecca",
            content="The heel anchor needs another measurement before any gait change.",
        )
    ]

    assert not has_close_self_repeat(
        "The shader palette needs another screenshot before we choose a color.",
        turns,
        self_aliases=SELF_ALIASES,
    )


@pytest.mark.parametrize(
    ("minimum_comparison_length", "similarity_threshold"),
    [(0, 0.88), (32, -0.01), (32, 1.01)],
)
def test_close_self_repeat_rejects_invalid_comparison_configuration(
    minimum_comparison_length: int,
    similarity_threshold: float,
) -> None:
    with pytest.raises(ValueError):
        has_close_self_repeat(
            "candidate",
            [],
            self_aliases=SELF_ALIASES,
            minimum_comparison_length=minimum_comparison_length,
            similarity_threshold=similarity_threshold,
        )
