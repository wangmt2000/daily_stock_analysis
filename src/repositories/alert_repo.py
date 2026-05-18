# -*- coding: utf-8 -*-
"""Alert repository.

Provides DB access helpers for alert-center P1 API tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, select

from src.storage import AlertNotificationRecord, AlertRuleRecord, AlertTriggerRecord, DatabaseManager


class AlertRepository:
    """DB access layer for alert rules and read-only alert history."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_rule(self, fields: Dict[str, Any]) -> AlertRuleRecord:
        with self.db.get_session() as session:
            row = AlertRuleRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get_rule(self, rule_id: int) -> Optional[AlertRuleRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(AlertRuleRecord).where(AlertRuleRecord.id == rule_id).limit(1)
            ).scalar_one_or_none()

    def update_rule(self, rule_id: int, fields: Dict[str, Any]) -> Optional[AlertRuleRecord]:
        with self.db.get_session() as session:
            row = session.execute(
                select(AlertRuleRecord).where(AlertRuleRecord.id == rule_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def delete_rule(self, rule_id: int) -> bool:
        with self.db.get_session() as session:
            result = session.execute(delete(AlertRuleRecord).where(AlertRuleRecord.id == rule_id))
            session.commit()
            return bool(result.rowcount)

    def list_rules(
        self,
        *,
        enabled: Optional[bool] = None,
        alert_type: Optional[str] = None,
        target_scope: Optional[str] = None,
        target: Optional[str] = None,
        source: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertRuleRecord], int]:
        conditions = []
        if enabled is not None:
            conditions.append(AlertRuleRecord.enabled.is_(enabled))
        if alert_type:
            conditions.append(AlertRuleRecord.alert_type == alert_type)
        if target_scope:
            conditions.append(AlertRuleRecord.target_scope == target_scope)
        if target:
            conditions.append(AlertRuleRecord.target == target)
        if source:
            conditions.append(AlertRuleRecord.source == source)

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertRuleRecord.id)).select_from(AlertRuleRecord).where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertRuleRecord)
                .where(where_clause)
                .order_by(desc(AlertRuleRecord.updated_at), desc(AlertRuleRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_enabled_rules(self, *, limit: int = 1000) -> List[AlertRuleRecord]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.db.get_session() as session:
            rows = session.execute(
                select(AlertRuleRecord)
                .where(AlertRuleRecord.enabled.is_(True))
                .order_by(desc(AlertRuleRecord.updated_at), desc(AlertRuleRecord.id))
                .limit(safe_limit)
            ).scalars().all()
            return list(rows)

    def create_trigger(self, fields: Dict[str, Any]) -> AlertTriggerRecord:
        if not fields.get("target"):
            raise ValueError("alert trigger target is required")
        if not fields.get("status"):
            raise ValueError("alert trigger status is required")

        with self.db.get_session() as session:
            row = AlertTriggerRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_triggers(
        self,
        *,
        rule_id: Optional[int] = None,
        target: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertTriggerRecord], int]:
        conditions = []
        if rule_id is not None:
            conditions.append(AlertTriggerRecord.rule_id == rule_id)
        if target:
            conditions.append(AlertTriggerRecord.target == target)
        if status:
            conditions.append(AlertTriggerRecord.status == status)

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertTriggerRecord.id)).select_from(AlertTriggerRecord).where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertTriggerRecord)
                .where(where_clause)
                .order_by(desc(AlertTriggerRecord.triggered_at), desc(AlertTriggerRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_notifications(
        self,
        *,
        trigger_id: Optional[int] = None,
        channel: Optional[str] = None,
        success: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertNotificationRecord], int]:
        conditions = []
        if trigger_id is not None:
            conditions.append(AlertNotificationRecord.trigger_id == trigger_id)
        if channel:
            conditions.append(AlertNotificationRecord.channel == channel)
        if success is not None:
            conditions.append(AlertNotificationRecord.success.is_(success))

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertNotificationRecord.id))
                .select_from(AlertNotificationRecord)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertNotificationRecord)
                .where(where_clause)
                .order_by(desc(AlertNotificationRecord.created_at), desc(AlertNotificationRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)
