"""
Workflow Engine Service
Executes workflows when trigger events fire. Supports five action types:
  send_notification, send_email, create_task, update_field, escalate

All actions use {{variable}} interpolation from the event context dict.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.workflow import (
    Workflow, WorkflowAction, WorkflowLog,
    TriggerEvent, ActionType, WorkflowStatus, WorkflowLogStatus,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Executes all active workflows matching a trigger event."""

    def __init__(self, db: Session):
        self.db = db

    # ──────────────────────────── Public API ────────────────────────────

    def fire(
        self,
        event: TriggerEvent,
        context: Dict[str, Any],
        owner_id=None,
    ) -> int:
        """
        Fire all active workflows for *event*.

        Args:
            event:    The TriggerEvent that occurred.
            context:  A dict of IDs / values relevant to the event.
                      Keys used for interpolation in action configs.
            owner_id: If provided, only run workflows owned by this user.

        Returns:
            Number of workflows executed.
        """
        try:
            query = self.db.query(Workflow).filter(
                Workflow.trigger_event == event,
                Workflow.status == WorkflowStatus.ACTIVE,
            )
            if owner_id is not None:
                query = query.filter(Workflow.owner_id == owner_id)

            workflows = query.all()
            logger.info(
                f"[WORKFLOW] Event '{event}' fired. "
                f"Found {len(workflows)} active workflow(s)."
            )

            for wf in workflows:
                self._execute_workflow(wf, event, context)

            return len(workflows)

        except Exception as exc:
            logger.error(f"[WORKFLOW] Error firing event '{event}': {exc}")
            return 0

    # ─────────────────────── Workflow Execution ───────────────────────

    def _execute_workflow(
        self,
        workflow: Workflow,
        event: TriggerEvent,
        context: Dict[str, Any],
    ) -> None:
        log = WorkflowLog(
            workflow_id=workflow.id,
            triggered_by=event.value,
            context=json.dumps(context, default=str),
            status=WorkflowLogStatus.SUCCESS,
            actions_run=0,
            triggered_at=datetime.utcnow(),
        )
        self.db.add(log)

        try:
            # Evaluate optional conditions
            if not self._check_conditions(workflow, context):
                log.status = WorkflowLogStatus.SKIPPED
                log.completed_at = datetime.utcnow()
                self.db.commit()
                logger.info(f"[WORKFLOW] '{workflow.name}' skipped (conditions not met).")
                return

            actions_run = 0
            for action in workflow.actions:
                try:
                    self._execute_action(action, context, workflow)
                    actions_run += 1
                except Exception as action_exc:
                    logger.error(
                        f"[WORKFLOW] Action {action.id} "
                        f"({action.action_type}) failed: {action_exc}"
                    )

            log.actions_run = actions_run
            log.completed_at = datetime.utcnow()

            # Update workflow stats
            workflow.run_count = (workflow.run_count or 0) + 1
            workflow.last_triggered_at = datetime.utcnow()

            self.db.commit()
            logger.info(
                f"[WORKFLOW] '{workflow.name}' completed. "
                f"Actions executed: {actions_run}/{len(workflow.actions)}."
            )

        except Exception as exc:
            logger.error(f"[WORKFLOW] '{workflow.name}' failed: {exc}")
            log.status = WorkflowLogStatus.FAILED
            log.error_message = str(exc)
            log.completed_at = datetime.utcnow()
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

    # ─────────────────────── Condition Checking ───────────────────────

    @staticmethod
    def _check_conditions(workflow: Workflow, context: Dict[str, Any]) -> bool:
        """
        Evaluate workflow.conditions (JSON dict) against the event context.
        All key/value pairs must match for the workflow to proceed.
        Missing conditions key → always passes.
        """
        if not workflow.conditions:
            return True
        try:
            conditions = json.loads(workflow.conditions)
        except Exception:
            return True

        for key, expected in conditions.items():
            actual = context.get(key)
            if actual is None:
                continue  # Unresolvable conditions are skipped (lenient)
            if str(actual) != str(expected):
                return False
        return True

    # ──────────────────────── Action Dispatch ────────────────────────

    def _execute_action(
        self,
        action: WorkflowAction,
        context: Dict[str, Any],
        workflow: Workflow,
    ) -> None:
        try:
            config: Dict[str, Any] = json.loads(action.config) if action.config else {}
        except Exception:
            config = {}

        dispatch = {
            ActionType.SEND_NOTIFICATION: self._action_send_notification,
            ActionType.SEND_EMAIL: self._action_send_email,
            ActionType.CREATE_TASK: self._action_create_task,
            ActionType.UPDATE_FIELD: self._action_update_field,
            ActionType.ESCALATE: self._action_escalate,
        }
        handler = dispatch.get(action.action_type)
        if handler:
            handler(config, context, workflow)  # type: ignore[call-arg]

    # ──────────────────────── Action Handlers ────────────────────────

    def _action_send_notification(
        self,
        config: dict,
        context: dict,
        workflow: Workflow,
    ) -> None:
        """
        Persist an in-app notification.
        Stored as a WorkflowLog detail; a real push/ws layer reads these.
        """
        title = self._interpolate(config.get("title", "Propertech Notification"), context)
        body = self._interpolate(config.get("body", ""), context)
        logger.info(
            f"[WORKFLOW][NOTIFY] wf='{workflow.name}' | "
            f"title='{title}' | body='{body[:120]}'"
        )
        # Production: push to FCM / websocket notification service

    def _action_send_email(
        self,
        config: dict,
        context: dict,
        workflow: Workflow,
    ) -> None:
        """
        Dispatch a transactional email.
        Uses recipient resolved from context (owner_email, tenant_email, etc.).
        """
        subject = self._interpolate(
            config.get("subject", "Propertech Alert"), context
        )
        body = self._interpolate(config.get("body", ""), context)
        to_role = config.get("to", "owner")

        # Resolve recipient e-mail from context
        recipient = (
            context.get(f"{to_role}_email")
            or context.get("owner_email")
            or config.get("fallback_email")
        )

        logger.info(
            f"[WORKFLOW][EMAIL] wf='{workflow.name}' | "
            f"to='{recipient}' | subject='{subject}' | body='{body[:120]}'"
        )

        if recipient:
            try:
                self._dispatch_email(recipient, subject, body)
            except Exception as email_exc:
                logger.warning(f"[WORKFLOW][EMAIL] Dispatch failed: {email_exc}")

    def _dispatch_email(self, to: str, subject: str, body: str) -> None:
        """
        Actual email dispatch. Uses SMTP if configured, otherwise logs.
        Configure SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS in env.
        """
        import os
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")
        from_addr = os.getenv("SMTP_FROM", smtp_user or "noreply@propertech.app")

        if not smtp_host or not smtp_user or not smtp_pass:
            logger.info(
                f"[WORKFLOW][EMAIL] SMTP not configured. "
                f"Would send to '{to}': {subject}"
            )
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to, msg.as_string())
            logger.info(f"[WORKFLOW][EMAIL] Sent to '{to}': {subject}")

    def _action_create_task(
        self,
        config: dict,
        context: dict,
        workflow: Workflow,
    ) -> None:
        """Create a task record in the tasks table."""
        try:
            from app.models.task import Task
            import uuid

            task_title = self._interpolate(
                config.get("title", "Automated Task"), context
            )
            due_in_days = int(config.get("due_in_days", 1))

            task = Task(
                id=uuid.uuid4(),
                title=task_title,
                description=self._interpolate(
                    config.get(
                        "description",
                        f"Auto-created by workflow: {workflow.name}",
                    ),
                    context,
                ),
                due_date=datetime.utcnow() + timedelta(days=due_in_days),
                status="pending",
                created_at=datetime.utcnow(),
            )
            self.db.add(task)
            logger.info(
                f"[WORKFLOW][TASK] wf='{workflow.name}' | created task: '{task_title}'"
            )
        except Exception as exc:
            logger.warning(f"[WORKFLOW][TASK] Failed to create task: {exc}")

    def _action_update_field(
        self,
        config: dict,
        context: dict,
        workflow: Workflow,  # noqa: ARG002
    ) -> None:
        """Set a field on a Unit or Tenant record."""
        model_name = config.get("model", "")
        field = config.get("field", "")
        value = self._interpolate(str(config.get("value", "")), context)

        try:
            if model_name == "unit" and "unit_id" in context:
                from app.models.property import Unit

                unit = self.db.query(Unit).filter(
                    Unit.id == context["unit_id"]
                ).first()
                if unit and hasattr(unit, field):
                    setattr(unit, field, value)
                    logger.info(
                        f"[WORKFLOW][UPDATE] Unit({context['unit_id']}).{field} = {value!r}"
                    )

            elif model_name == "tenant" and "tenant_id" in context:
                from app.models.tenant import Tenant

                tenant = self.db.query(Tenant).filter(
                    Tenant.id == context["tenant_id"]
                ).first()
                if tenant and hasattr(tenant, field):
                    setattr(tenant, field, value)
                    logger.info(
                        f"[WORKFLOW][UPDATE] Tenant({context['tenant_id']}).{field} = {value!r}"
                    )

        except Exception as exc:
            logger.warning(f"[WORKFLOW][UPDATE] Failed: {exc}")

    def _action_escalate(
        self,
        config: dict,
        context: dict,
        workflow: Workflow,
    ) -> None:
        """High-priority escalation: send email + notification to owner."""
        message = self._interpolate(
            config.get("message", "Escalation required"), context
        )
        notify_role = config.get("notify_role", "owner")
        subject = f"[ESCALATION] {workflow.name}"
        logger.info(
            f"[WORKFLOW][ESCALATE] wf='{workflow.name}' "
            f"→ role='{notify_role}': {message}"
        )
        # Re-use email dispatch for escalation
        self._action_send_email(
            {"to": notify_role, "subject": subject, "body": message},
            context,
            workflow,
        )

    # ──────────────────────── Interpolation ────────────────────────

    @staticmethod
    def _interpolate(template: str, context: Dict[str, Any]) -> str:
        """Replace {{key}} placeholders using the event context."""
        result = template
        for key, value in context.items():
            result = result.replace(
                f"{{{{{key}}}}}", str(value) if value is not None else ""
            )
        return result
