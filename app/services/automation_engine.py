"""
Automation Engine — processes events, evaluates rule conditions,
respects autopilot settings (quiet hours, mode), and executes action chains.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytz
from sqlalchemy.orm import Session

from app.models.automation import (
    AutomationRule,
    AutomationExecution,
    AutopilotSettings,
)
from app.services.event_bus import PropertyEvent

logger = logging.getLogger(__name__)
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")


class AutomationEngine:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Public entry point ────────────────────────────────────────────────────

    async def handle_event(self, event: PropertyEvent) -> None:
        """
        Called by the event_bus for every published event.
        Routes to matching rules for the event owner.
        """
        logger.info(
            f"[engine] Handling event '{event.event_type}' for owner {event.owner_id}"
        )
        try:
            owner_uuid = uuid.UUID(event.owner_id)
        except (ValueError, AttributeError):
            logger.warning(f"[engine] Invalid owner_id: {event.owner_id}")
            return

        rules = (
            self.db.query(AutomationRule)
            .filter(
                AutomationRule.owner_id == owner_uuid,
                AutomationRule.trigger_event == event.event_type,
                AutomationRule.is_active == True,
            )
            .all()
        )

        if not rules:
            logger.debug(f"[engine] No active rules for '{event.event_type}' owner={event.owner_id}")
            return

        settings = (
            self.db.query(AutopilotSettings)
            .filter(AutopilotSettings.owner_id == owner_uuid)
            .first()
        )

        for rule in rules:
            await self._maybe_execute(rule, event, settings)

    # ── Condition evaluation ──────────────────────────────────────────────────

    def _check_conditions(
        self, conditions: Optional[List[Dict[str, Any]]], payload: Dict[str, Any]
    ) -> bool:
        """Return True if all conditions pass (AND logic)."""
        if not conditions:
            return True

        for cond in conditions:
            field = cond.get("field", "")
            op = cond.get("operator", "eq")
            expected = cond.get("value")
            actual = payload.get(field)

            try:
                if op == "eq":
                    result = actual == expected
                elif op == "neq":
                    result = actual != expected
                elif op == "gt":
                    result = float(actual or 0) > float(expected or 0)
                elif op == "lt":
                    result = float(actual or 0) < float(expected or 0)
                elif op == "gte":
                    result = float(actual or 0) >= float(expected or 0)
                elif op == "lte":
                    result = float(actual or 0) <= float(expected or 0)
                elif op == "in":
                    result = actual in (expected or [])
                elif op == "contains":
                    result = str(expected or "").lower() in str(actual or "").lower()
                else:
                    result = True
            except (TypeError, ValueError):
                result = False

            if not result:
                logger.debug(
                    f"[engine] Condition failed: {field} {op} {expected} (actual={actual})"
                )
                return False

        return True

    # ── Quiet hours check ─────────────────────────────────────────────────────

    def _in_quiet_hours(self, settings: Optional[AutopilotSettings]) -> bool:
        if not settings:
            return False
        now_eat = datetime.now(NAIROBI_TZ)
        hour = now_eat.hour
        start = settings.quiet_hours_start  # e.g. 21
        end = settings.quiet_hours_end      # e.g. 7

        if start > end:
            # Overnight window (e.g. 21 → 07)
            return hour >= start or hour < end
        else:
            return start <= hour < end

    # ── Execution gate ────────────────────────────────────────────────────────

    async def _maybe_execute(
        self,
        rule: AutomationRule,
        event: PropertyEvent,
        settings: Optional[AutopilotSettings],
    ) -> None:
        # Conditions check
        conditions_list = rule.trigger_conditions if isinstance(rule.trigger_conditions, list) else []
        if not self._check_conditions(conditions_list, event.payload):
            logger.debug(f"[engine] Rule '{rule.name}' — conditions not met, skipping")
            return

        # Settings checks
        if not settings or not settings.is_enabled:
            logger.info(f"[engine] Autopilot disabled for owner {event.owner_id} — skipping '{rule.name}'")
            return

        if self._in_quiet_hours(settings):
            logger.info(f"[engine] Quiet hours active — skipping rule '{rule.name}'")
            return

        # Daily action cap check
        from sqlalchemy import func as sqlfunc
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        executions_today = (
            self.db.query(sqlfunc.count(AutomationExecution.id))
            .filter(
                AutomationExecution.owner_id == uuid.UUID(event.owner_id),
                AutomationExecution.started_at >= today_start,
                AutomationExecution.status.in_(["completed", "running"]),
            )
            .scalar() or 0
        )
        if executions_today >= (settings.max_actions_per_day or 50):
            logger.warning(
                f"[engine] Daily cap reached ({executions_today}/{settings.max_actions_per_day}) "
                f"— skipping rule '{rule.name}'"
            )
            return

        # Property exclusion check
        property_id = str(event.payload.get("property_id", ""))
        excluded = settings.excluded_property_ids or []
        if property_id and property_id in excluded:
            logger.info(f"[engine] Property {property_id} excluded from autopilot")
            return

        # Approval required or mode = approval_required
        if rule.requires_approval or settings.mode == "approval_required":
            await self._create_awaiting_approval(rule, event)
            return

        # Delay scheduling
        if rule.delay_minutes and rule.delay_minutes > 0:
            await self._schedule_delayed(rule, event)
            return

        await self.execute_rule(rule, event)

    # ── Approval flow ─────────────────────────────────────────────────────────

    async def _create_awaiting_approval(
        self, rule: AutomationRule, event: PropertyEvent
    ) -> None:
        execution = AutomationExecution(
            id=uuid.uuid4(),
            rule_id=rule.id,
            owner_id=uuid.UUID(event.owner_id),
            trigger_event=event.event_type,
            trigger_payload=event.payload,
            status="awaiting_approval",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(execution)
        self.db.commit()
        logger.info(
            f"[engine] Rule '{rule.name}' created awaiting_approval execution {execution.id}"
        )

    # ── Delayed execution ─────────────────────────────────────────────────────

    async def _schedule_delayed(
        self, rule: AutomationRule, event: PropertyEvent
    ) -> None:
        """Schedule the rule execution via APScheduler after delay_minutes."""
        try:
            from app.services.scheduler import get_scheduler
            from datetime import timedelta
            run_at = datetime.now(NAIROBI_TZ) + timedelta(minutes=rule.delay_minutes)

            scheduler = get_scheduler()
            if scheduler:
                scheduler.add_job(
                    _delayed_execute_job,
                    "date",
                    run_date=run_at,
                    args=[str(rule.id), event.event_type, event.owner_id, event.payload],
                    id=f"delayed_{rule.id}_{datetime.utcnow().timestamp()}",
                    replace_existing=False,
                )
                logger.info(
                    f"[engine] Rule '{rule.name}' scheduled in {rule.delay_minutes} min at {run_at}"
                )
            else:
                # Fallback — execute immediately
                await self.execute_rule(rule, event)
        except Exception as exc:
            logger.error(f"[engine] Failed to schedule delayed job: {exc}")
            await self.execute_rule(rule, event)

    # ── Main execution ────────────────────────────────────────────────────────

    async def execute_rule(
        self, rule: AutomationRule, event: PropertyEvent
    ) -> Optional[AutomationExecution]:
        """Create an execution row and run every action in the chain."""
        from app.services.action_library import dispatch_action

        owner_uuid = uuid.UUID(event.owner_id)
        execution = AutomationExecution(
            id=uuid.uuid4(),
            rule_id=rule.id,
            owner_id=owner_uuid,
            trigger_event=event.event_type,
            trigger_payload=event.payload,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(execution)
        self.db.commit()

        actions_taken: List[Dict[str, Any]] = []
        final_status = "completed"
        error_msg = None

        action_chain = rule.action_chain or []
        if not isinstance(action_chain, list):
            action_chain = []

        for step in action_chain:
            action_type = step.get("action_type", "")
            params = step.get("params", {})
            stop_on_failure = step.get("stop_on_failure", False)

            logger.info(
                f"[engine] exec={execution.id} action='{action_type}' "
                f"rule='{rule.name}'"
            )

            result = await dispatch_action(
                action_type=action_type,
                params=params,
                event_payload=event.payload,
                execution_id=execution.id,
                db=self.db,
                owner_id=owner_uuid,
            )
            actions_taken.append(result)

            if result.get("status") == "failed" and stop_on_failure:
                final_status = "failed"
                error_msg = f"Action '{action_type}' failed: {result.get('data', {}).get('error', '')}"
                logger.warning(f"[engine] stop_on_failure triggered — aborting rule '{rule.name}'")
                break

        # Update execution record
        execution.status = final_status
        execution.completed_at = datetime.now(timezone.utc)
        execution.actions_taken = actions_taken
        execution.error_message = error_msg

        # Increment rule counter
        rule.execution_count = (rule.execution_count or 0) + 1
        rule.last_executed_at = datetime.now(timezone.utc)

        self.db.commit()
        logger.info(
            f"[engine] Execution {execution.id} {final_status} "
            f"({len(actions_taken)} actions)"
        )
        return execution


# ── Global engine singleton ───────────────────────────────────────────────────
_engine_instance: Optional[AutomationEngine] = None


def get_engine() -> Optional[AutomationEngine]:
    return _engine_instance


def set_engine(engine: AutomationEngine) -> None:
    global _engine_instance
    _engine_instance = engine


# ── APScheduler delayed job (must be module-level for pickling) ───────────────

def _delayed_execute_job(
    rule_id: str,
    event_type: str,
    owner_id: str,
    payload: Dict[str, Any],
) -> None:
    """Runs in APScheduler thread — creates its own DB session."""
    import asyncio
    from app.database import SessionLocal
    from app.services.event_bus import PropertyEvent

    db = SessionLocal()
    try:
        rule = db.query(AutomationRule).filter(
            AutomationRule.id == uuid.UUID(rule_id)
        ).first()
        if not rule:
            logger.warning(f"[delayed_job] Rule {rule_id} not found")
            return

        engine = AutomationEngine(db)
        event = PropertyEvent(
            event_type=event_type,
            owner_id=owner_id,
            payload=payload,
            source="scheduler_delayed",
        )
        asyncio.run(engine.execute_rule(rule, event))
    finally:
        db.close()
