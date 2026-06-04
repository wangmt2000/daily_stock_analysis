# -*- coding: utf-8 -*-
"""Tests for the AlphaSift screening endpoints."""

from __future__ import annotations

import os
import sys
import threading
import unittest
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import ANY, MagicMock, patch

from fastapi import HTTPException

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.endpoints import alphasift as alphasift_endpoint
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC

DEFAULT_ALPHASIFT_TEST_SPEC = DEFAULT_ALPHASIFT_INSTALL_SPEC


def _alphasift_unavailable() -> HTTPException:
    return HTTPException(
        status_code=424,
        detail={"error": "alphasift_unavailable", "message": "AlphaSift is unavailable"},
    )


def _raise_alphasift_unavailable() -> None:
    raise _alphasift_unavailable()


def _make_adapter_module(
    *,
    screen=None,
    list_strategies=None,
    get_status=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        screen=screen or MagicMock(return_value=[]),
        list_strategies=list_strategies or (lambda: [{"id": "dual_low", "name": "双低选股", "description": "", "category": "价值"}]),
        get_status=get_status or (lambda: {"supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1}),
    )


def _missing_alphasift_module_diagnostics() -> Dict[str, str]:
    return {
        "reason": "missing_module",
        "stage": "import_adapter",
        "error_type": "ModuleNotFoundError",
        "module": "alphasift.dsa_adapter",
    }


class AlphaSiftOpportunitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()

    def tearDown(self) -> None:
        Config.reset_instance()

    def _config(self, *, enabled: bool, install_spec: str = DEFAULT_ALPHASIFT_TEST_SPEC) -> Config:
        return Config(alphasift_enabled=enabled, alphasift_install_spec=install_spec)

    @staticmethod
    def _request(cookies=None) -> SimpleNamespace:
        return SimpleNamespace(cookies=cookies or {})

    def _screen(self, config: Config, **kwargs):
        return alphasift_endpoint.alphasift_screen(
            alphasift_endpoint.AlphaSiftScreenRequest(**kwargs),
            http_request=self._request(),
            config=config,
        )

    def _strategies(self, config: Config):
        return alphasift_endpoint.alphasift_strategies(request=self._request(), config=config)

    def test_default_install_spec_is_commit_pinned(self) -> None:
        self.assertRegex(
            DEFAULT_ALPHASIFT_TEST_SPEC,
            r"^git\+https://github\.com/ZhuLinsen/alphasift\.git@[0-9a-f]{40}$",
        )

    def test_status_defaults_to_disabled(self) -> None:
        config = self._config(enabled=False)

        with patch("api.v1.endpoints.alphasift._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["enabled"], False)
        self.assertEqual(payload["available"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("diagnostics", payload)
        self.assertNotIn("install_spec", payload)

    def test_status_marks_custom_install_source(self) -> None:
        config = self._config(enabled=False, install_spec="git+https://example.com/private/alphasift.git")

        with patch("api.v1.endpoints.alphasift._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["install_spec_is_default"], False)
        self.assertNotIn("install_spec", payload)

    def test_status_includes_adapter_contract_metadata(self) -> None:
        config = self._config(enabled=True)

        with patch(
            "api.v1.endpoints.alphasift._call_alphasift_status",
            return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["strategy_count"], 8)

    def test_status_preserves_adapter_available_false_without_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with patch(
            "api.v1.endpoints.alphasift._call_alphasift_status",
            return_value={"available": False, "contract_version": "1", "version": "0.2.0", "strategy_count": 0},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertNotIn("diagnostics", payload)

    def test_status_logs_and_reports_adapter_runtime_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=MagicMock(side_effect=RuntimeError("get_status failed")))

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status")
        self.assertEqual(payload["diagnostics"]["error_type"], "RuntimeError")
        self.assertIn("Unexpected AlphaSift get_status failure", "\n".join(captured.output))

    def test_status_logs_and_reports_unexpected_import_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        missing_sub_dependency = ModuleNotFoundError("No module named 'optional_dep'", name="optional_dep")

        with (
            patch("api.v1.endpoints.alphasift._prepare_alphasift_runtime_env"),
            patch("api.v1.endpoints.alphasift.importlib.import_module", side_effect=missing_sub_dependency),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "import_adapter")
        self.assertEqual(payload["diagnostics"]["error_type"], "ModuleNotFoundError")
        self.assertIn("Unexpected AlphaSift import_adapter failure", "\n".join(captured.output))

    def test_status_marks_missing_module_for_auto_install_shortcut(self) -> None:
        config = self._config(enabled=True)
        missing_module_exc = ModuleNotFoundError("No module named 'alphasift.dsa_adapter'", name="alphasift.dsa_adapter")

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", side_effect=missing_module_exc),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING"),
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "missing_module")
        self.assertEqual(payload["diagnostics"]["stage"], "import_adapter")
        self.assertEqual(payload["diagnostics"]["error_type"], "ModuleNotFoundError")

    def test_status_logs_and_reports_invalid_get_status_result_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=lambda: ["not", "a", "dict"])

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_result")
        self.assertEqual(payload["diagnostics"]["error_type"], "TypeError")
        self.assertIn("Unexpected AlphaSift get_status_result failure", "\n".join(captured.output))

    def test_status_logs_and_reports_missing_get_status_callable_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = SimpleNamespace(list_strategies=lambda: [], screen=MagicMock(return_value=[]))

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_callable")
        self.assertEqual(payload["diagnostics"]["error_type"], "HTTPException")
        self.assertIn("Unexpected AlphaSift get_status_callable failure", "\n".join(captured.output))

    def test_strategies_returns_adapter_strategies(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [
                {"id": "dual_low", "name": "双低选股", "description": "value", "category": "价值"},
                {"id": "trend_quality", "title": "趋势质量", "description": "trend", "tag": "框架"},
            ],
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._strategies(config=config)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(payload["strategies"][0]["id"], "dual_low")
        self.assertEqual(payload["strategies"][0]["name"], "双低选股")
        self.assertEqual(payload["strategies"][1]["name"], "趋势质量")

    def test_strategies_installs_when_enabled_but_adapter_missing(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module()

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "api.v1.endpoints.alphasift._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("api.v1.endpoints.alphasift._install_alphasift") as install_mock,
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
        ):
            payload = self._strategies(config=config)

        install_mock.assert_called_once_with(config)
        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 1)

    def test_implicit_install_is_single_flight_across_concurrent_requests(self) -> None:
        config = self._config(enabled=True)
        request = self._request()
        first_probe_barrier = threading.Barrier(2)
        state_lock = threading.Lock()
        state = {"available": False, "install_count": 0, "probe_count": 0}
        errors: list[BaseException] = []
        missing_diag = _missing_alphasift_module_diagnostics()

        def probe_status() -> tuple[dict, bool, dict[str, str] | None]:
            with state_lock:
                state["probe_count"] += 1
                probe_count = state["probe_count"]
                available = state["available"]

            if probe_count <= 2 and not available:
                first_probe_barrier.wait(timeout=2)
                return ({}, False, missing_diag)
            return ({}, bool(available), None if available else missing_diag)

        def install(_config: Config) -> Dict[str, Any]:
            with state_lock:
                state["install_count"] += 1
                state["available"] = True
            return {"installed": True}

        def worker() -> None:
            try:
                alphasift_endpoint._ensure_alphasift_ready(config, request=request)
            except BaseException as exc:
                errors.append(exc)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("api.v1.endpoints.alphasift._get_alphasift_status_snapshot", side_effect=probe_status),
            patch("api.v1.endpoints.alphasift._install_alphasift", side_effect=install) as install_mock,
        ):
            threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        for thread in threads:
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(state["install_count"], 1)
        install_mock.assert_called_once_with(config)

    def test_screen_rejects_when_disabled(self) -> None:
        config = self._config(enabled=False)

        with self.assertRaises(HTTPException) as caught:
            self._screen(config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")

    def test_screen_rejects_when_alphasift_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "api.v1.endpoints.alphasift._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("api.v1.endpoints.alphasift._install_alphasift", side_effect=lambda _config: _raise_alphasift_unavailable()) as install_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        install_mock.assert_called_once_with(config)

    def test_screen_does_not_auto_install_when_adapter_runtime_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "api.v1.endpoints.alphasift._get_alphasift_status_snapshot",
                return_value=(
                    {},
                    False,
                    {"reason": "unexpected_exception", "stage": "get_status", "error_type": "RuntimeError"},
                ),
            ),
            patch("api.v1.endpoints.alphasift._install_alphasift") as install_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("resolution"), "no_auto_install")
        self.assertEqual(
            caught.exception.detail.get("diagnostics", {}).get("message"),
            "请先检查后端日志并修复运行时异常，当前未触发自动安装。",
        )
        install_mock.assert_not_called()

    def test_install_rejects_spoofed_localhost_without_admin_session(self) -> None:
        config = self._config(enabled=True)
        request = SimpleNamespace(
            cookies={alphasift_endpoint.COOKIE_NAME: "invalid-session"},
            url=SimpleNamespace(hostname="localhost"),
            client=SimpleNamespace(host="127.0.0.1"),
        )

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False),
            patch("api.v1.endpoints.alphasift.refresh_auth_state") as refresh_mock,
            patch("api.v1.endpoints.alphasift.is_auth_enabled", return_value=True),
            patch("api.v1.endpoints.alphasift.verify_session", return_value=False) as verify_session_mock,
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=request, config=config)

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_access_denied")
        refresh_mock.assert_called_once()
        verify_session_mock.assert_called_once_with("invalid-session")
        run_mock.assert_not_called()

    def test_install_allows_valid_admin_session_outside_desktop_mode(self) -> None:
        config = self._config(enabled=True)
        request = self._request({alphasift_endpoint.COOKIE_NAME: "valid-session"})

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False),
            patch("api.v1.endpoints.alphasift.refresh_auth_state") as refresh_mock,
            patch("api.v1.endpoints.alphasift.is_auth_enabled", return_value=True),
            patch("api.v1.endpoints.alphasift.verify_session", return_value=True) as verify_session_mock,
            patch("api.v1.endpoints.alphasift._install_alphasift", return_value={"installed": True}) as install_mock,
        ):
            payload = alphasift_endpoint.alphasift_install(request=request, config=config)

        self.assertEqual(payload["installed"], True)
        refresh_mock.assert_called_once()
        verify_session_mock.assert_called_once_with("valid-session")
        install_mock.assert_called_once_with(config)

    def test_install_rejects_when_disabled_without_side_effects(self) -> None:
        config = self._config(enabled=False)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
            patch("api.v1.endpoints.alphasift._import_alphasift") as import_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")
        import_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_install_invokes_pip_when_enabled_and_missing(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("api.v1.endpoints.alphasift._is_alphasift_available", side_effect=[False, True]),
            patch(
                "api.v1.endpoints.alphasift._call_alphasift_status",
                return_value={"available": True, "supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1},
            ),
            patch("api.v1.endpoints.alphasift.subprocess.run", return_value=completed) as run_mock,
            patch("api.v1.endpoints.alphasift._get_dsa_adapter", return_value=_make_adapter_module()),
        ):
            payload = alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(payload["installed"], True)
        self.assertEqual(payload["already_installed"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("install_spec", payload)
        run_mock.assert_called_once()
        install_command = run_mock.call_args.args[0]
        self.assertIn("--upgrade", install_command)
        self.assertIn("--force-reinstall", install_command)
        self.assertIn(DEFAULT_ALPHASIFT_TEST_SPEC, install_command)

    def test_install_rejects_when_alphasift_adapter_reports_unavailable(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "api.v1.endpoints.alphasift._call_alphasift_status",
                side_effect=[
                    {"available": False},
                    {"available": False},
                ],
            ),
            patch("api.v1.endpoints.alphasift.subprocess.run", return_value=completed) as run_mock,
            patch("api.v1.endpoints.alphasift._get_dsa_adapter") as get_adapter_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        run_mock.assert_called_once()
        get_adapter_mock.assert_not_called()

    def test_install_rejects_untrusted_spec(self) -> None:
        config = self._config(enabled=True, install_spec="git+https://example.com/private/alphasift.git")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("api.v1.endpoints.alphasift._is_alphasift_available", return_value=False),
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_spec_not_allowed")
        run_mock.assert_not_called()

    def test_screen_calls_dsa_adapter_and_normalizes_llm_fields(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "run_id": "run123",
                    "strategy": "dual_low",
                    "market": "cn",
                    "snapshot_count": 100,
                    "after_filter_count": 5,
                    "llm_ranked": True,
                    "llm_coverage": 1.0,
                    "warnings": ["fallback"],
                    "source_errors": [],
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": 88.5,
                            "llm_score": 90.0,
                            "llm_thesis": "LLM likes the setup",
                            "risk_level": "medium",
                            "risk_flags": ["valuation"],
                            "price": 1688.0,
                            "industry": "Baijiu",
                            "factor_scores": {"value": 88.0},
                        }
                    ],
                }
            ),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_results=5,
            use_llm=True,
            context=ANY,
        )
        self.assertEqual(fake_module.screen.call_args.kwargs["context"]["llm"]["model"], "")
        self.assertEqual(payload["run_id"], "run123")
        self.assertEqual(payload["snapshot_count"], 100)
        self.assertEqual(payload["after_filter_count"], 5)
        self.assertEqual(payload["llm_ranked"], True)
        self.assertEqual(payload["llm_coverage"], 1.0)
        self.assertEqual(payload["warnings"], ["fallback"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["code"], "600519")
        self.assertEqual(payload["candidates"][0]["llm_score"], 90.0)
        self.assertEqual(payload["candidates"][0]["llm_thesis"], "LLM likes the setup")
        self.assertEqual(payload["candidates"][0]["risk_level"], "medium")
        self.assertEqual(payload["candidates"][0]["price"], 1688.0)
        self.assertEqual(payload["candidates"][0]["industry"], "Baijiu")

    def test_screen_bridges_dsa_llm_config_into_alphasift_runtime(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-2.5-flash",
            litellm_fallback_models=["deepseek/deepseek-chat"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-2.5-flash"],
                }
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["env"] = {
                "LITELLM_MODEL": alphasift_endpoint.os.environ.get("LITELLM_MODEL"),
                "LITELLM_FALLBACK_MODELS": alphasift_endpoint.os.environ.get("LITELLM_FALLBACK_MODELS"),
                "LLM_CHANNELS": alphasift_endpoint.os.environ.get("LLM_CHANNELS"),
                "LLM_GEMINI_PROTOCOL": alphasift_endpoint.os.environ.get("LLM_GEMINI_PROTOCOL"),
                "LLM_GEMINI_API_KEYS": alphasift_endpoint.os.environ.get("LLM_GEMINI_API_KEYS"),
                "GEMINI_API_KEY": alphasift_endpoint.os.environ.get("GEMINI_API_KEY"),
            }
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(alphasift_endpoint.os.environ, {"GEMINI_API_KEY": "outer-key", "SNAPSHOT_SOURCE_PRIORITY": ""}, clear=False),
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(alphasift_endpoint.os.environ.get("GEMINI_API_KEY"), "outer-key")

        runtime_env = captured["env"]
        self.assertIsInstance(runtime_env, dict)
        self.assertEqual(runtime_env["LITELLM_MODEL"], "gemini/gemini-2.5-flash")
        self.assertEqual(runtime_env["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-chat")
        self.assertEqual(runtime_env["LLM_CHANNELS"], "gemini")
        self.assertEqual(runtime_env["LLM_GEMINI_PROTOCOL"], "gemini")
        self.assertEqual(runtime_env["LLM_GEMINI_API_KEYS"], "dsa-gemini-key")
        self.assertEqual(runtime_env["GEMINI_API_KEY"], "dsa-gemini-key")
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["model"], "gemini/gemini-2.5-flash")
        self.assertEqual(context["llm"]["channels"][0]["api_keys"], ["dsa-gemini-key"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_preserves_explicit_alphasift_snapshot_source_priority(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["snapshot_priority"] = alphasift_endpoint.os.environ.get("SNAPSHOT_SOURCE_PRIORITY")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(alphasift_endpoint.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False),
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["snapshot_priority"], "tushare,em_datacenter")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_filters_undeclared_managed_fallbacks_for_dsa_routes(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-3-flash-preview",
            litellm_fallback_models=["gemini/gemini-2.5-flash"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-3-flash-preview"],
                },
                {
                    "name": "deepseek",
                    "protocol": "deepseek",
                    "enabled": True,
                    "base_url": "https://api.deepseek.com",
                    "api_keys": ["dsa-deepseek-key"],
                    "models": ["deepseek/deepseek-chat"],
                },
            ],
            llm_model_list=[
                {
                    "model_name": "gemini/gemini-3-flash-preview",
                    "litellm_params": {
                        "model": "gemini/gemini-3-flash-preview",
                        "api_key": "dsa-gemini-key",
                    },
                },
                {
                    "model_name": "deepseek/deepseek-chat",
                    "litellm_params": {
                        "model": "deepseek/deepseek-chat",
                        "api_key": "dsa-deepseek-key",
                        "api_base": "https://api.deepseek.com",
                    },
                },
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["env"] = {
                "LITELLM_MODEL": alphasift_endpoint.os.environ.get("LITELLM_MODEL"),
                "LITELLM_FALLBACK_MODELS": alphasift_endpoint.os.environ.get("LITELLM_FALLBACK_MODELS"),
                "LLM_CHANNELS": alphasift_endpoint.os.environ.get("LLM_CHANNELS"),
            }
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        runtime_env = captured["env"]
        self.assertIsInstance(runtime_env, dict)
        self.assertEqual(runtime_env["LITELLM_MODEL"], "gemini/gemini-3-flash-preview")
        self.assertEqual(runtime_env["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-chat")
        self.assertEqual(runtime_env["LLM_CHANNELS"], "gemini,deepseek")
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["fallback_models"], ["deepseek/deepseek-chat"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_retries_without_context_for_older_adapter_kwargs_wrappers(self) -> None:
        config = self._config(enabled=True)

        def screen_impl(_strategy: str, **kwargs):
            if "context" in kwargs:
                raise TypeError("unexpected keyword argument 'context'")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(fake_module.screen.call_count, 2)
        first_kwargs = fake_module.screen.call_args_list[0].kwargs
        second_kwargs = fake_module.screen.call_args_list[1].kwargs
        self.assertIn("context", first_kwargs)
        self.assertNotIn("context", second_kwargs)
        self.assertEqual(second_kwargs["market"], "cn")
        self.assertEqual(second_kwargs["max_results"], 5)
        self.assertEqual(second_kwargs["use_llm"], True)
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_installs_when_enabled_but_adapter_missing(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(screen=MagicMock(return_value={"candidates": []}))

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "api.v1.endpoints.alphasift._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("api.v1.endpoints.alphasift._install_alphasift") as install_mock,
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        install_mock.assert_called_once_with(config)
        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_results=5,
            use_llm=True,
            context=ANY,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_normalizes_non_finite_values(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "picks": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": float("nan"),
                            "ranking_reason": "AlphaSift pick",
                            "nested": {"pe": float("inf"), "pb": float("-inf"), "eps": 20.5},
                        },
                    ],
                }
            ),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertIsNone(payload["candidates"][0]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pe"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pb"])

    def test_screen_allows_non_listed_strategy_as_custom(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [{"id": "dual_low", "name": "双低选股"}],
            screen=MagicMock(return_value={"candidates": []}),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="custom_alpha", max_results=5)

        fake_module.screen.assert_called_once_with(
            "custom_alpha",
            market="cn",
            max_results=5,
            use_llm=True,
            context=ANY,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_rejects_unsupported_market(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            get_status=lambda: {"supported_markets": ["hk", "us"]},
            screen=MagicMock(return_value=[]),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["error"], "alphasift_invalid_market")

    def test_screen_maps_adapter_value_error_to_bad_request(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(side_effect=ValueError("Only market='cn' is currently supported")),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail["error"], "alphasift_screen_rejected")


if __name__ == "__main__":
    unittest.main()
