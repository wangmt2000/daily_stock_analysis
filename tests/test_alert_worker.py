# -*- coding: utf-8 -*-
"""Alert worker tests for Issue #1202 P2."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from src.config import Config
from src.services.alert_service import AlertService
from src.services.alert_worker import AlertWorker
from src.storage import DatabaseManager


class AlertWorkerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.db_path = self.data_dir / "alert_worker_test.db"
        self.env_path.write_text(
            "\n".join([
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={self.db_path}",
            ])
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.service = AlertService()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _config(self, raw_rules: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json=raw_rules,
        )

    def _create_rule(self, **overrides) -> dict:
        payload = {
            "name": "Moutai breakout",
            "target_scope": "single_symbol",
            "target": "600519",
            "alert_type": "price_cross",
            "parameters": {"direction": "above", "price": 1800},
            "severity": "warning",
            "enabled": True,
        }
        payload.update(overrides)
        return self.service.create_rule(payload)

    def _triggers(self, **filters) -> list[dict]:
        return self.service.list_triggers(page_size=100, **filters)["items"]

    def test_enabled_db_rule_triggers_and_disabled_rule_is_ignored(self) -> None:
        enabled_rule = self._create_rule(target="600519")
        self._create_rule(
            name="Disabled",
            target="000001",
            parameters={"direction": "above", "price": 10},
            enabled=False,
        )
        notifier = MagicMock()
        notifier.send.return_value = True
        seen_codes = []

        async def _quote(_monitor, stock_code):
            seen_codes.append(stock_code)
            return SimpleNamespace(price=1810.0)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 1)
        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(seen_codes, ["600519"])
        triggers = self._triggers(rule_id=enabled_rule["id"])
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["status"], "triggered")
        self.assertEqual(triggers[0]["target"], "600519")
        self.assertEqual(triggers[0]["observed_value"], 1810.0)
        self.assertEqual(triggers[0]["threshold"], 1800.0)
        notifier.send.assert_called_once()
        self.assertEqual(notifier.send.call_args.kwargs["route_type"], "alert")

    def test_legacy_rules_coexist_with_db_rules_and_db_rule_wins_duplicate_key(self) -> None:
        self._create_rule(target="600519")
        legacy_rules = (
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},'
            '{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.5}]'
        )

        async def _quote(_monitor, stock_code):
            if stock_code == "300750":
                return {"pct_chg": "-3.75%"}
            return SimpleNamespace(price=1810.0)

        worker = AlertWorker(
            config_provider=lambda: self._config(legacy_rules),
            service=self.service,
            notifier=MagicMock(send=MagicMock(return_value=True)),
        )
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 2)
        self.assertEqual(stats["triggered"], 2)
        targets = {item["target"] for item in self._triggers()}
        self.assertEqual(targets, {"600519", "300750"})

    def test_legacy_json_parse_failure_does_not_crash_or_block_persisted_rules(self) -> None:
        before = self.env_path.read_text(encoding="utf-8")
        self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        worker = AlertWorker(config_provider=lambda: self._config("[invalid"), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 1)
        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(len(self._triggers()), 1)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), before)

    def test_all_invalid_legacy_rules_do_not_crash(self) -> None:
        invalid_rules = (
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"sideways","price":1800},'
            '{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":0}]'
        )
        worker = AlertWorker(config_provider=lambda: self._config(invalid_rules), service=self.service)

        stats = worker.run_once()

        self.assertEqual(stats["loaded"], 0)
        self.assertEqual(stats["evaluated"], 0)
        self.assertEqual(self._triggers(), [])

    def test_empty_sources_are_a_noop(self) -> None:
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)

        stats = worker.run_once()

        self.assertEqual(stats["loaded"], 0)
        self.assertEqual(stats["evaluated"], 0)
        self.assertEqual(self._triggers(), [])

    def test_missing_quote_writes_skipped_trigger_without_notification(self) -> None:
        self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=AsyncMock(return_value=None)):
            stats = worker.run_once()

        self.assertEqual(stats["skipped"], 1)
        triggers = self._triggers(status="skipped")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "600519")
        self.assertIn("No realtime quote", triggers[0]["diagnostics"])
        notifier.send.assert_not_called()

    def test_price_cross_numeric_yyyymmdd_quote_date_writes_correct_timestamp(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, date=20260517)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-17T00:00:00")

    def test_price_cross_space_separated_quote_time_writes_timestamp(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, quote_time="2026-05-17 15:00:00")),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-17T15:00:00")

    def test_ambiguous_numeric_quote_timestamp_is_not_written_as_epoch(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, timestamp=1700000000)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertIsNone(triggers[0]["data_timestamp"])

    def test_service_test_rule_exception_uses_same_sanitized_reason_and_message(self) -> None:
        rule = self._create_rule(target="600519")

        async def _raise(_rule, _monitor):
            raise RuntimeError("token=secret-token failed at https://example.com/webhook")

        with patch.object(self.service, "_evaluate_rule", new=_raise):
            result = self.service.test_rule(rule["id"])

        self.assertEqual(result["status"], "evaluation_error")
        self.assertEqual(result["record_status"], "failed")
        self.assertEqual(result["reason"], result["message"])
        self.assertNotIn("secret-token", result["reason"])
        self.assertNotIn("example.com/webhook", result["message"])

    def test_daily_data_unavailable_writes_degraded_trigger(self) -> None:
        self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.5},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = None

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        triggers = self._triggers(status="degraded")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertIn("No daily volume data", triggers[0]["diagnostics"])

    def test_malformed_daily_data_response_writes_degraded_trigger(self) -> None:
        self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.5},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = {"unexpected": "shape"}

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        triggers = self._triggers(status="degraded")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertIn("Malformed daily volume data", triggers[0]["diagnostics"])

    def test_volume_spike_trigger_writes_expected_trigger_fields(self) -> None:
        rule = self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.0},
        )
        manager = MagicMock()
        daily = pd.DataFrame(
            {
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "volume": [1000, 1000, 5000],
            }
        )
        manager.get_daily_data.return_value = (daily, "test_source")
        notifier = MagicMock()
        notifier.send.return_value = True

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(stats["recorded"], 1)
        self.assertEqual(stats["notified"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertEqual(triggers[0]["observed_value"], 5000.0)
        self.assertAlmostEqual(triggers[0]["threshold"], 4666.666666666667)
        self.assertEqual(triggers[0]["data_source"], "daily_data")
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-15T00:00:00")
        notifier.send.assert_called_once()

    def test_single_rule_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = MagicMock()
        notifier.send.return_value = True

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                raise RuntimeError("token=secret-token failed at https://example.com/webhook")
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["triggered"], 1)
        failed = self._triggers(status="failed")
        self.assertEqual(len(failed), 1)
        self.assertNotIn("secret-token", failed[0]["diagnostics"])
        self.assertNotIn("example.com/webhook", failed[0]["diagnostics"])
        self.assertEqual(len(self._triggers(status="triggered")), 1)

    def test_notification_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = MagicMock()
        notifier.send.side_effect = [RuntimeError("webhook secret failed"), True]

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                return SimpleNamespace(price=1810.0)
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 2)
        self.assertEqual(stats["recorded"], 2)
        self.assertEqual(stats["notified"], 1)
        self.assertEqual(len(self._triggers(status="triggered")), 2)
        self.assertEqual(notifier.send.call_count, 2)

    def test_trigger_record_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = MagicMock()
        notifier.send.return_value = True
        original_create_trigger = self.service.repo.create_trigger

        def _create_trigger(fields):
            if fields["target"] == "600519":
                raise RuntimeError("database locked")
            return original_create_trigger(fields)

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                return SimpleNamespace(price=1810.0)
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch.object(self.service.repo, "create_trigger", side_effect=_create_trigger), \
             patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 2)
        self.assertEqual(stats["recorded"], 1)
        self.assertEqual(stats["notified"], 2)
        triggers = self._triggers(status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "300750")

    def test_fingerprint_ttl_suppresses_duplicate_notifications_but_expires(self) -> None:
        self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.return_value = True
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            worker.run_once()
            now["value"] += 30
            worker.run_once()
            now["value"] += 61
            worker.run_once()

        self.assertEqual(notifier.send.call_count, 2)
        self.assertEqual(len(self._triggers(status="triggered")), 3)

    def test_failed_notification_attempts_do_not_consume_fingerprint_window(self) -> None:
        self._create_rule(target="600519")
        notifier = MagicMock()
        notifier.send.side_effect = [False, RuntimeError("temporary webhook failure"), True]
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            first = worker.run_once()
            now["value"] += 10
            second = worker.run_once()
            now["value"] += 10
            third = worker.run_once()
            now["value"] += 10
            fourth = worker.run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(third["notified"], 1)
        self.assertEqual(fourth["notified"], 0)
        self.assertEqual(notifier.send.call_count, 3)
        self.assertEqual(len(self._triggers(status="triggered")), 4)


if __name__ == "__main__":
    unittest.main()
