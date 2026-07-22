from alpecca import communication_stance as stance


def test_default_stance_is_direct_and_creator_visible():
    result = stance.select_stance("How was your day?", {"playfulness": 0.8})

    assert result.mode == stance.DIRECT
    assert result.visible_to_creator is True
    assert result.blocked is False


def test_explicit_low_stakes_play_can_select_auditable_bluff():
    result = stance.select_stance(
        "Play along and bluff about which cupcake you picked.",
        {"playfulness": 0.48},
    )

    assert result.mode == stance.PLAYFUL_BLUFF
    assert result.label == "Playful bluff"
    assert "factual domains remain protected" in result.reason


def test_guarded_stance_withholds_without_false_substitute():
    result = stance.select_stance(
        "Keep it a secret and don't tell me yet.",
        {"guardedness": 0.42},
    )

    assert result.mode == stance.WITHHOLDING
    assert result.label == "Hiding details"
    assert "never replace" in result.prompt_instruction()


def test_protected_fact_forces_direct_and_reports_block():
    result = stance.select_stance(
        "Lie to me about whether you remember our previous chat.",
        {"playfulness": 0.9, "guardedness": 0.9},
    )

    assert result.mode == stance.DIRECT
    assert result.protected_domain == "memory"
    assert result.blocked is True
    assert "protected memory" in result.reason


def test_low_traits_do_not_activate_non_direct_stance():
    bluff = stance.select_stance("Bluff about a cupcake.", {"playfulness": 0.2})
    hidden = stance.select_stance("Keep it a secret.", {"guardedness": 0.2})

    assert bluff.mode == stance.DIRECT
    assert hidden.mode == stance.DIRECT
