# -*- coding: utf-8 -*-
"""Background worker for persisted and legacy alert rules."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.agent.events import (
    EventMonitor,
    PriceAlert,
    PriceChangeAlert,
    VolumeAlert,
    parse_event_alert_rules,
    validate_event_alert_rule,
)
from src.services.alert_service import AlertService

logger = logging.getLogger(__name__)

ALERT_WORKER_FINGERPRINT_TTL_SECONDS = 24 * 60 * 60
ALERT_WORKER_RULE_LIMIT = 1000
WRITABLE_TRIGGER_STATUSES = frozenset({"triggered", "skipped", "degraded", "failed"})


@dataclass
class RuntimeAlertRule:
    key: str
    rule: Any
    source: str


class AlertWorker:
    """Evaluate alert-center rules for schedule-mode background polling."""

    def __init__(
        self,
        *,
        config_provider: Optional[Callable[[], Any]] = None,
        service: Optional[AlertService] = None,
        notifier: Optional[Any] = None,
        now_provider: Optional[Callable[[], float]] = None,
        fingerprint_ttl_seconds: int = ALERT_WORKER_FINGERPRINT_TTL_SECONDS,
    ) -> None:
        self.config_provider = config_provider or self._default_config_provider
        self.service = service or AlertService()
        self.notifier = notifier
        self.now_provider = now_provider or time.time
        self.fingerprint_ttl_seconds = max(1, int(fingerprint_ttl_seconds))
        self._trigger_fingerprints: Dict[str, float] = {}

    @staticmethod
    def _default_config_provider():
        from src.config import get_config

        return get_config()

    def run_once(self) -> Dict[str, int]:
        """Run one alert worker cycle.

        This method is intentionally exception-contained so scheduler background
        threads keep running even when one config or rule is bad.
        """
        stats = {
            "loaded": 0,
            "evaluated": 0,
            "recorded": 0,
            "triggered": 0,
            "notified": 0,
            "skipped": 0,
            "degraded": 0,
            "failed": 0,
        }

        try:
            config = self.config_provider()
        except Exception as exc:
            logger.warning("[AlertWorker] Failed to load runtime config: %s", exc)
            return stats

        if not getattr(config, "agent_event_monitor_enabled", False):
            logger.debug("[AlertWorker] Event monitor disabled; skipping")
            return stats

        self._prune_fingerprints()
        runtime_rules = self._load_runtime_rules(config)
        stats["loaded"] = len(runtime_rules)
        if not runtime_rules:
            logger.info("[AlertWorker] No active alert rules loaded")
            return stats

        monitor = EventMonitor()
        for runtime_rule in runtime_rules:
            stats["evaluated"] += 1
            try:
                result = asyncio.run(self.service._evaluate_rule(runtime_rule.rule, monitor))
            except Exception as exc:
                result = {
                    "rule_id": self.service._runtime_rule_id(runtime_rule.rule),
                    "record_status": "failed",
                    "triggered": False,
                    "observed_value": None,
                    "threshold": self.service._threshold_for_rule(runtime_rule.rule),
                    "data_source": self.service._data_source_for_rule(runtime_rule.rule),
                    "data_timestamp": None,
                    "reason": self.service._sanitize_text(str(exc) or "Alert evaluation failed"),
                    "message": self.service._sanitize_text(str(exc) or "Alert evaluation failed"),
                }

            record_status = result.get("record_status")
            if record_status in WRITABLE_TRIGGER_STATUSES:
                if self._record_trigger_safely(runtime_rule, result, record_status):
                    stats["recorded"] += 1
                if record_status in stats and record_status != "triggered":
                    stats[record_status] += 1

            if record_status == "triggered":
                stats["triggered"] += 1
                if self._should_notify(runtime_rule.key):
                    if self._send_notification_safely(runtime_rule, result):
                        self._mark_notified(runtime_rule.key)
                        stats["notified"] += 1

        return stats

    def _load_runtime_rules(self, config: Any) -> List[RuntimeAlertRule]:
        runtime_rules: List[RuntimeAlertRule] = []
        seen_keys = set()

        for row in self.service.repo.list_enabled_rules(limit=ALERT_WORKER_RULE_LIMIT):
            try:
                rule_data = self.service._serialize_rule(row)
                key = self._semantic_key(
                    rule_data["target_scope"],
                    rule_data["target"],
                    rule_data["alert_type"],
                    rule_data["parameters"],
                )
                runtime_rules.append(
                    RuntimeAlertRule(
                        key=key,
                        rule=self.service._to_runtime_rule(row),
                        source="db",
                    )
                )
                seen_keys.add(key)
            except Exception as exc:
                logger.warning("[AlertWorker] Skip invalid persisted alert rule %s: %s", getattr(row, "id", "?"), exc)

        for key, rule in self._load_legacy_rules(config):
            if key in seen_keys:
                logger.info("[AlertWorker] Skip duplicate legacy alert rule: %s", key)
                continue
            runtime_rules.append(RuntimeAlertRule(key=key, rule=rule, source="legacy_env"))
            seen_keys.add(key)

        return runtime_rules

    def _load_legacy_rules(self, config: Any) -> List[Tuple[str, Any]]:
        raw_rules = getattr(config, "agent_event_alert_rules_json", "")
        try:
            parsed_rules = parse_event_alert_rules(raw_rules)
        except Exception as exc:
            logger.warning("[AlertWorker] Failed to parse legacy alert rules: %s", exc)
            return []

        legacy_rules: List[Tuple[str, Any]] = []
        for index, entry in enumerate(parsed_rules, start=1):
            try:
                validate_event_alert_rule(entry)
                stock_code = str(entry.get("stock_code") or "").strip()
                alert_type = str(entry.get("alert_type") or "").strip().lower()
                parameters = self.service._normalize_parameters(alert_type, entry)
                key = self._semantic_key("single_symbol", stock_code, alert_type, parameters)
                metadata = {"source": "legacy_env", "legacy_rule_index": index}
                if alert_type == "price_cross":
                    rule = PriceAlert(
                        stock_code=stock_code,
                        direction=str(parameters["direction"]),
                        price=float(parameters["price"]),
                        metadata=metadata,
                    )
                elif alert_type == "price_change_percent":
                    rule = PriceChangeAlert(
                        stock_code=stock_code,
                        direction=str(parameters["direction"]),
                        change_pct=float(parameters["change_pct"]),
                        metadata=metadata,
                    )
                elif alert_type == "volume_spike":
                    rule = VolumeAlert(
                        stock_code=stock_code,
                        multiplier=float(parameters["multiplier"]),
                        metadata=metadata,
                    )
                else:
                    raise ValueError(f"unsupported alert_type: {alert_type}")
                legacy_rules.append((key, rule))
            except Exception as exc:
                logger.warning("[AlertWorker] Skip invalid legacy alert rule #%d: %s", index, exc)
        return legacy_rules

    @staticmethod
    def _semantic_key(target_scope: str, target: str, alert_type: str, parameters: Dict[str, Any]) -> str:
        canonical_params = json.dumps(parameters or {}, ensure_ascii=False, sort_keys=True)
        return f"{target_scope}:{target}:{alert_type}:{canonical_params}"

    def _record_trigger(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any], status: str) -> None:
        try:
            rule_id = int(result.get("rule_id") or 0) or None
        except (TypeError, ValueError):
            rule_id = None

        fields = {
            "rule_id": rule_id,
            "target": runtime_rule.rule.stock_code,
            "observed_value": self._optional_float(result.get("observed_value")),
            "threshold": self._optional_float(result.get("threshold")),
            "reason": result.get("reason") or result.get("message"),
            "data_source": result.get("data_source"),
            "data_timestamp": result.get("data_timestamp"),
            "status": status,
            "diagnostics": self._diagnostics_for_status(status, result),
        }
        self.service.repo.create_trigger(fields)

    def _record_trigger_safely(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any], status: str) -> bool:
        try:
            self._record_trigger(runtime_rule, result, status)
            return True
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to record alert trigger for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                self.service._sanitize_text(str(exc) or "trigger write failed"),
            )
            return False

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _diagnostics_for_status(status: str, result: Dict[str, Any]) -> Optional[str]:
        if status == "triggered":
            return None
        return result.get("message") or result.get("reason")

    def _should_notify(self, rule_key: str) -> bool:
        now = self.now_provider()
        last_seen = self._trigger_fingerprints.get(rule_key)
        if last_seen is not None and now - last_seen < self.fingerprint_ttl_seconds:
            return False
        return True

    def _mark_notified(self, rule_key: str) -> None:
        self._trigger_fingerprints[rule_key] = self.now_provider()

    def _prune_fingerprints(self) -> None:
        now = self.now_provider()
        expired_keys = [
            key
            for key, last_seen in self._trigger_fingerprints.items()
            if now - last_seen >= self.fingerprint_ttl_seconds
        ]
        for key in expired_keys:
            self._trigger_fingerprints.pop(key, None)

    def _send_notification(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> bool:
        from src.notification import NotificationBuilder, NotificationService

        notification_service = self.notifier or NotificationService()
        title = f"Event Alert | {runtime_rule.rule.stock_code}"
        content = result.get("reason") or result.get("message") or runtime_rule.rule.description or "Alert triggered"
        alert_text = NotificationBuilder.build_simple_alert(title=title, content=content, alert_type="warning")
        sent = notification_service.send(alert_text, route_type="alert")
        if not sent:
            logger.info("[AlertWorker] No notification channel available for alert: %s", title)
        return bool(sent)

    def _send_notification_safely(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> bool:
        try:
            return self._send_notification(runtime_rule, result)
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to send alert notification for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                self.service._sanitize_text(str(exc) or "notification failed"),
            )
            return False
