from pathlib import Path


def _requirement_names():
    lines = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    return [
        line.strip().split(";", 1)[0].split("==", 1)[0].split(">=", 1)[0].strip().lower()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_legacy_cgi_is_installed_before_web_py_for_python_313_plus():
    names = _requirement_names()

    assert "legacy-cgi" in names
    assert "web.py" in names
    assert "web.py-update" in names
    assert names.index("legacy-cgi") < names.index("web.py")
    assert names.index("legacy-cgi") < names.index("web.py-update")


def test_python_313_plus_uses_web_py_update_instead_of_legacy_web_py():
    lines = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    web_py = next(line for line in lines if line.startswith("web.py;"))
    web_py_update = next(line for line in lines if line.startswith("web.py-update"))

    assert 'python_version < "3.13"' in web_py
    assert 'python_version >= "3.13"' in web_py_update


def test_default_requirements_exclude_optional_or_unused_integrations():
    names = set(_requirement_names())

    assert "aiohttp" not in names
    assert "plotly" not in names
    assert "click" not in names
    assert "wechatpy" not in names
    assert "lark-oapi" not in names
    assert "dingtalk_stream" not in names
    assert "playwright" not in names


def test_default_requirements_include_pdf_reading_stack():
    names = set(_requirement_names())

    assert "pypdf" in names
    assert "pymupdf" in names
