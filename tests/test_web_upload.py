from io import BytesIO
from types import SimpleNamespace
import json

from channel.web.web import web_channel


def test_chat_upload_saves_file_and_returns_attachment_payload(tmp_path, monkeypatch):
    file_obj = SimpleNamespace(filename="report.docx", file=BytesIO(b"demo document"))
    monkeypatch.setattr(web_channel, "_upload_web_input", lambda: {"file": file_obj, "session_id": "s1"})
    monkeypatch.setattr(web_channel, "_get_upload_dir", lambda: str(tmp_path))

    result = web_channel.WebChannel().upload_file()
    payload = json.loads(result)

    assert payload["status"] == "success"
    assert payload["file_name"] == "report.docx"
    assert payload["file_type"] == "file"
    assert payload["preview_url"].startswith("/uploads/")
    assert (tmp_path / payload["preview_url"].rsplit("/", 1)[-1]).exists()


def test_chat_upload_normalizes_browser_filename(tmp_path, monkeypatch):
    file_obj = SimpleNamespace(filename=r"C:\fakepath\image.png", file=BytesIO(b"png"))
    monkeypatch.setattr(web_channel, "_upload_web_input", lambda: {"file": file_obj, "session_id": "s1"})
    monkeypatch.setattr(web_channel, "_get_upload_dir", lambda: str(tmp_path))

    result = web_channel.WebChannel().upload_file()
    payload = json.loads(result)

    assert payload["status"] == "success"
    assert payload["file_name"] == "image.png"
    assert payload["file_type"] == "image"
