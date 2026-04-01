import logging

import src.webui_frontend as webui_frontend


def _prepare_fake_repo(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    module_path = repo_root / "src" / "webui_frontend.py"
    module_path.parent.mkdir(parents=True)
    module_path.touch()
    monkeypatch.setattr(webui_frontend, "__file__", str(module_path))
    return repo_root


def test_prepare_webui_frontend_assets_reuses_prebuilt_static_without_source(tmp_path, monkeypatch, caplog):
    repo_root = _prepare_fake_repo(tmp_path, monkeypatch)
    static_index = repo_root / "static" / "index.html"
    static_index.parent.mkdir(parents=True)
    static_index.write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.delenv("WEBUI_AUTO_BUILD", raising=False)
    monkeypatch.delenv("WEBUI_FORCE_BUILD", raising=False)
    monkeypatch.setattr(webui_frontend.shutil, "which", lambda _: None)

    with caplog.at_level(logging.INFO):
        assert webui_frontend.prepare_webui_frontend_assets() is True

    assert "检测到可直接复用的前端静态产物" in caplog.text
    assert "未找到前端项目，无法自动构建" not in caplog.text
    assert "未检测到 npm，无法自动构建前端" not in caplog.text


def test_prepare_webui_frontend_assets_fails_without_static_or_source(tmp_path, monkeypatch, caplog):
    _prepare_fake_repo(tmp_path, monkeypatch)

    monkeypatch.delenv("WEBUI_AUTO_BUILD", raising=False)
    monkeypatch.delenv("WEBUI_FORCE_BUILD", raising=False)

    with caplog.at_level(logging.WARNING):
        assert webui_frontend.prepare_webui_frontend_assets() is False

    assert "未找到前端项目，无法自动构建" in caplog.text
