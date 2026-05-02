from knownet_api.services.source_selector import SourceSelector


def test_source_selector_returns_message_and_keyword_pages(tmp_path):
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "neat.md").write_text("# NEAT\n\nNEAT evolves topology.", encoding="utf-8")
    (pages_dir / "other.md").write_text("# Other\n\nUnrelated note.", encoding="utf-8")

    selector = SourceSelector(tmp_path)
    selected = selector.select_for_message(message_id="msg_1", content="How does NEAT topology growth work?")

    assert selected["candidate_sources"][0]["source_key"] == "msg_1"
    assert selected["candidate_pages"][0]["slug"] == "neat"
    assert selected["selection_reason"]


def test_source_selector_limits_candidate_pages(tmp_path):
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    for index in range(4):
        (pages_dir / f"page-{index}.md").write_text("keyword keyword", encoding="utf-8")

    selector = SourceSelector(tmp_path)
    selected = selector.select_for_message(message_id="msg_1", content="keyword")

    assert len(selected["candidate_pages"]) == 2
