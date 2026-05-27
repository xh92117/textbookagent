from pathlib import Path


def test_one_click_write_prefills_chat_instead_of_starting_pipeline_directly():
    js = Path("channel/web/web/static/js/textbook.js").read_text(encoding="utf-8")

    start_fn = js[js.index("function startPipelineForCurrentBook()"):js.index("function startPipelineForChapter")]

    assert "navigateToChat" in start_fn
    assert "startPipeline(currentBookId)" not in start_fn


def test_chat_pause_requests_pipeline_cancel_for_current_book():
    js = Path("channel/web/web/static/js/textbook.js").read_text(encoding="utf-8")

    stop_fn = js[js.index("function stopCurrentChat()"):js.index("var EMOJIS")]

    assert "cancelCurrentPipeline()" in stop_fn
    assert "action: 'cancel'" in stop_fn
