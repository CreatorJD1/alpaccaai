from alpecca import surface_continuity
from alpecca import mind as mind_mod
from alpecca import turn_context
from alpecca import cognition


def test_surface_ledger_is_content_free_and_cross_surface(tmp_path):
    db = tmp_path / "continuity.sqlite3"
    surface_continuity.record_contact(
        "house-hq", principal="creator", db_path=db, now=100.0,
    )
    surface_continuity.record_contact(
        "discord", principal="guest", event_kind="voice", db_path=db, now=130.0,
    )

    rows = surface_continuity.recent_contacts(db_path=db, now=160.0)
    assert [row["surface"] for row in rows] == ["discord", "house-hq"]
    assert set(rows[0]) == {
        "id", "ts", "surface", "principal_class", "event_kind", "age_seconds",
    }
    assert rows[0]["event_kind"] == "voice"


def test_surface_prompt_distinguishes_contact_from_private_content(tmp_path):
    db = tmp_path / "continuity.sqlite3"
    surface_continuity.record_contact(
        "house-hq", principal="creator", db_path=db, now=100.0,
    )

    prompt = surface_continuity.prompt_awareness(db_path=db)
    assert "creator contacted you through house-hq" in prompt
    assert "proves contact occurred, not what private text said" in prompt
    assert "Never claim the other surface was unseen" in prompt


def test_authenticated_creator_receives_exact_recent_house_turn(monkeypatch):
    turn = turn_context.TurnContext.create(
        "creator-cross-surface",
        principal="creator",
        surface="discord",
        privacy_scope="creator-personal",
    )
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "recent_chat_turns",
        lambda **_kwargs: [
            {
                "user_text": "Please check the lanyard placement.",
                "reply": "I will inspect it.",
                "model_use": {"turn": {"surface": "house-hq"}},
            }
        ],
    )

    prompt = mind_mod._creator_cross_surface_context(
        turn,
        "What was my last message in House HQ?",
    )

    assert "Please check the lanyard placement." in prompt
    assert "most recent first" in prompt


def test_guest_never_receives_creator_cross_surface_content(monkeypatch):
    turn = turn_context.TurnContext.create(
        "guest-room",
        principal="guest",
        surface="discord",
    )
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "recent_chat_turns",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not query")),
    )

    assert mind_mod._creator_cross_surface_context(
        turn,
        "What was said in House HQ?",
    ) == ""


def test_lived_chat_view_keeps_all_surfaces_with_provenance(tmp_path):
    db = tmp_path / "cognition.sqlite3"
    cognition.init_db(db)
    cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="House message",
            reply="House reply",
            scope="creator-personal",
            model_use={"turn": {"surface": "house-hq", "principal": "creator"}},
        ),
        db_path=db,
    )
    cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="Discord message",
            reply="Discord reply",
            scope="alpecca-lived-discord-example",
            model_use={"turn": {"surface": "discord", "principal": "guest"}},
        ),
        db_path=db,
    )

    lived = cognition.recent_lived_chat_turns(limit=5, db_path=db)

    assert [turn["user_text"] for turn in lived] == [
        "Discord message",
        "House message",
    ]
    assert lived[0]["scope"] == "alpecca-lived-discord-example"
