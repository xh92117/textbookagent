import sys
from types import SimpleNamespace

from agent.knowledge.service import KnowledgeService
from common import package_manager


def test_package_manager_uses_current_python_for_install(monkeypatch):
    calls = []

    def fake_run(cmd, check):
        calls.append((cmd, check))

    monkeypatch.setattr(package_manager.subprocess, "run", fake_run)

    package_manager.install("dulwich")

    assert calls == [([sys.executable, "-m", "pip", "install", "dulwich"], True)]


def test_package_manager_uses_current_python_for_requirements(monkeypatch, tmp_path):
    calls = []
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest\n", encoding="utf-8")

    def fake_run(cmd, check):
        calls.append((cmd, check))

    monkeypatch.setattr(package_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(package_manager, "_reset_logger", lambda logger: None)

    package_manager.install_requirements(str(requirements))

    assert calls == [
        ([sys.executable, "-m", "pip", "install", "-r", str(requirements), "--upgrade"], True)
    ]


def test_doc_extraction_uses_current_python(monkeypatch, tmp_path):
    calls = []
    doc_path = tmp_path / "demo.doc"
    doc_path.write_bytes(b"demo")

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="converted text")

    import agent.knowledge.service as service_module

    monkeypatch.setattr(service_module.subprocess, "run", fake_run)
    svc = KnowledgeService(str(tmp_path))

    assert svc._extract_doc(str(doc_path)) == "converted text"
    assert calls[0][0] == sys.executable
