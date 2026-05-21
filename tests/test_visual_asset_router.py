from agent.textbook.pipeline.visual_asset_router import VisualAssetRouter


def test_visual_asset_gate_rejects_tiny_files(tmp_path):
    router = VisualAssetRouter(str(tmp_path / "tb"))
    bad = tmp_path / "tiny.png"
    bad.write_bytes(b"x")

    ok, reason = router._validate_asset(str(bad))

    assert ok is False
    assert "too small" in reason


def test_visual_asset_fallback_is_valid_and_labeled(tmp_path, monkeypatch):
    router = VisualAssetRouter(str(tmp_path / "tb"))

    class FailedImage:
        status = "failed"
        path = ""
        reason = "model unavailable"

    monkeypatch.setattr(router, "_generate_model_image", lambda *args, **kwargs: FailedImage())

    decision = router.resolve_image("construction site inspection scene", 1, 1)

    assert decision.status == "success"
    assert decision.source == "fallback"
    assert "placeholder=true" in decision.evidence
    assert decision.path
