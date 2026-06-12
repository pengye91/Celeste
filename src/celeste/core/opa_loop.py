"""
OPA Loop (Observe-Plan-Act) workflow orchestrator for Celeste-DAG.

The OPALoop is the central orchestrator that drives the Environment Agent
Protocol. It implements a tiered escalation strategy:

- Tier 1: Retry transient failures (up to 3x with exponential backoff)
- Tier 2: Scoped replan (triggered by evaluator REPLAN or postcondition mismatch)
- Tier 3: Full replan (when environment changes drastically)
- Tier 4: Human escalation (return WorkflowResult with escalated status)

Safety limits:
- MAX_OPA_CYCLES (default 100)
- MAX_LLM_TOKENS (default 50000)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from typing import Any

from celeste.config.settings import EngineSettings, get_settings
from celeste.core.evaluator import Evaluator, EvaluatorDecision
from celeste.core.exceptions import PlannerTimeoutError
from celeste.core.planner import DAGFragment, DAGNode, DAGPlan, Planner
from celeste.database.db import get_session
from celeste.database.models import (
    TaskEvent,
    TaskEventType,
    TaskNode,
    TaskNodeStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
    _utcnow,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WorkflowResult
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class WorkflowResult:
    """Result of an OPA loop workflow execution."""

    status: str  # "completed", "escalated", "failed"
    cycle_count: int
    llm_tokens_accumulated: int
    reason: str | None = None
    workflow_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# WorkflowExecutor
# ---------------------------------------------------------------------------


class WorkflowExecutor:
    """Executes a DAGFragment by calling tools via the agent.

    For this implementation, nodes are executed sequentially respecting
    dependencies. Each node is invoked via agent.call_tool().
    """

    def __init__(self, agent: Any, security_auditor: Any = None) -> None:
        self._agent = agent
        self._security_auditor = security_auditor

    async def execute_fragment(self, fragment: DAGFragment) -> dict[str, Any]:
        """Execute all nodes in the fragment sequentially.

        Returns a dict with:
            - completed: list of node names that succeeded
            - failed: list of node names that failed
            - skipped: list of node names skipped due to failed dependencies
            - audit_results: list of audit verdict dicts (when security_auditor is set)
        """
        completed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        security_blocked: list[str] = []
        audit_results: list[dict[str, Any]] = []

        # Build a map of node name -> node
        node_map = {node.name: node for node in fragment.nodes}
        executed = set()

        # Process nodes in topological order (respecting dependencies)
        # We use a simple approach: repeatedly find nodes whose deps are satisfied
        pending = set(node_map.keys())

        while pending:
            # Find nodes with all dependencies satisfied
            ready = {
                name for name in pending
                if all(dep in executed for dep in node_map[name].dependencies)
            }

            if not ready:
                # Remaining nodes have unresolvable dependencies (cycle or missing)
                for name in pending:
                    skipped.append(name)
                break

            for name in sorted(ready):
                node = node_map[name]
                pending.remove(name)

                # Skip if any dependency failed
                dep_failed = any(dep in failed for dep in node.dependencies)
                if dep_failed:
                    skipped.append(name)
                    executed.add(name)
                    continue

                # --- Security audit before execution ---
                verdict = None
                if self._security_auditor is not None:
                    verdict = self._security_auditor.audit_tool_call(
                        node.command,
                        node.arguments,
                    )

                    audit_results.append({
                        "node_name": name,
                        "tool_name": node.command,
                        "arguments": node.arguments,
                        "is_safe": verdict.is_safe if verdict else True,
                        "risk_level": verdict.risk_level if verdict else "safe",
                        "reason": verdict.reason if verdict else "No auditor configured",
                        "detected_threats": list(verdict.detected_threats) if verdict else [],
                    })

                if verdict is not None and not verdict.is_safe:
                    security_blocked.append(name)
                    failed.append(name)
                    executed.add(name)
                    continue

                try:
                    result = await self._agent.call_tool(
                        node.command,
                        node.arguments,
                    )
                    if isinstance(result, dict) and result.get("error"):
                        failed.append(name)
                    else:
                        completed.append(name)
                except Exception:
                    failed.append(name)

                executed.add(name)

        return {
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "security_blocked": security_blocked,
            "audit_results": audit_results,
        }


# ---------------------------------------------------------------------------
# OPALoop
# ---------------------------------------------------------------------------


class OPALoop:
    """Observe-Plan-Act loop orchestrator.

    Drives the OPA cycle:
        1. OBSERVE  -- snapshot environment + list tools
        2. PLAN     -- ask planner for next DAG fragment
        3. ACT      -- execute fragment via WorkflowExecutor
        4. EVALUATE -- ask evaluator if goal is achieved

    Supports tiered escalation and safety limits.
    """

    def __init__(
        self,
        agent: Any,
        planner: Planner,
        evaluator: Evaluator,
        settings: EngineSettings | None = None,
        security_auditor: Any = None,
    ) -> None:
        self._agent = agent
        self._planner = planner
        self._evaluator = evaluator
        self._settings = settings or get_settings()
        self._security_auditor = security_auditor
        self._executor = WorkflowExecutor(agent, security_auditor=security_auditor)

    def _summarize_history_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Compress a full history entry into a minimal summary."""
        if entry.get("_summary"):
            # Already a summary block; keep it as-is.
            return entry
        return {
            "cycle": entry["cycle"],
            "decision": entry["decision"],
            "completed_nodes": len(entry["execution"].get("completed", [])),
            "failed_nodes": len(entry["execution"].get("failed", [])),
            "token_estimate": entry.get("token_estimate", 0),
        }

    def _maybe_summarize_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep the last N full cycles; summarize older cycles into a summary block.

        The summary block is stored as a single entry at the front of the history
        list so the planner still receives chronological context without unbounded
        memory growth.
        """
        max_full = self._settings.OPA_HISTORY_MAX_CYCLES
        if max_full < 0:
            max_full = 0

        if len(history) <= max_full:
            return history

        # Partition: oldest entries become summaries; newest remain full.
        # The summary block itself counts toward the budget, so keep at most
        # max_full - 1 full entries when a summary block is present.
        # When max_full is 0, all prior full entries are summarized and the
        # planner receives only the summary block.
        full_slots = max(0, max_full - 1) if max_full > 0 else 0
        to_summarize = history[: len(history) - full_slots]
        keep_full = history[len(history) - full_slots :]

        summaries: list[dict[str, Any]] = []
        for entry in to_summarize:
            if entry.get("_summary"):
                summaries.extend(entry.get("entries", []))
            else:
                summaries.append(self._summarize_history_entry(entry))

        return [{"_summary": True, "entries": summaries}] + keep_full

    async def run(
        self,
        goal: str,
        max_cycles: int | None = None,
        max_llm_tokens: int | None = None,
    ) -> WorkflowResult:
        """Run the OPA loop until the goal is achieved or limits are hit.

        Args:
            goal: The high-level workflow goal.
            max_cycles: Override for MAX_OPA_CYCLES.
            max_llm_tokens: Override for MAX_LLM_TOKENS.

        Returns:
            WorkflowResult with final status, reason, and metrics.
        """
        max_cycles = max_cycles or self._settings.MAX_OPA_CYCLES
        max_llm_tokens = max_llm_tokens or self._settings.MAX_LLM_TOKENS

        cycle_count = 0
        llm_tokens_accumulated = 0
        history: list[dict[str, Any]] = []

        # Create and persist the workflow record up front.
        workflow = await self._create_workflow(goal)
        workflow_id = workflow.id
        seq = 0

        # Track completed node names across cycles so that compensation is
        # triggered for any node that succeeded before a later failure.
        completed_node_names: set[str] = set()
        failed_node_names: set[str] = set()

        while True:
            # -- Safety limits ------------------------------------------------
            cycle_count += 1
            if cycle_count > max_cycles:
                await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                return WorkflowResult(
                    status="escalated",
                    reason="max_cycles_exceeded",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )
            # Heuristic: each OPA cycle consumes some tokens (observation + plan + evaluate)
            # In production this would come from actual LLM usage metadata
            llm_tokens_accumulated += 100
            if llm_tokens_accumulated >= max_llm_tokens:
                await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                return WorkflowResult(
                    status="escalated",
                    reason="token_budget_exceeded",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.CYCLE_STARTED,
                {"cycle": cycle_count},
                seq,
            )

            # -- 1. OBSERVE ---------------------------------------------------
            try:
                observation = await self._agent.call_tool("snapshot", {})
            except Exception as exc:
                logger.error("Agent unreachable during observation: %s", exc)
                await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,  # no cycle completed
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.OBSERVATION_CAPTURED,
                {"observation": observation},
                seq,
            )

            try:
                tool_schemas = await self._agent.list_tools()
            except Exception as exc:
                logger.error("Agent unreachable listing tools: %s", exc)
                await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            # -- 2. PLAN ------------------------------------------------------
            try:
                fragment = await self._planner.plan(
                    goal=goal,
                    observation=observation,
                    tool_schemas=tool_schemas,
                    history=history,
                )
            except PlannerTimeoutError:
                if cycle_count == 1:
                    await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                    return WorkflowResult(
                        status="escalated",
                        reason="planner_timeout_no_progress",
                        cycle_count=cycle_count,
                        llm_tokens_accumulated=llm_tokens_accumulated,
                        workflow_id=workflow_id,
                    )
                # Retry with simplified prompt on next cycle
                continue

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.PLAN_GENERATED,
                {
                    "cycle": cycle_count,
                    "dag_def": fragment.model_dump(),
                    "reasoning": fragment.reasoning,
                },
                seq,
            )

            # Persist the fragment as TaskNode records and execute via engine.
            await self._persist_fragment(workflow_id, fragment)

            # -- 3. ACT -------------------------------------------------------
            # Tier 1: retry transient failures
            exec_result = await self._execute_with_retries(fragment)

            # Emit SECURITY_AUDIT events for each audited tool call.
            seq = await self._emit_security_audit_events(
                workflow_id, seq, exec_result.get("audit_results", [])
            )

            # Update tracking sets from execution result.
            completed_node_names.update(exec_result.get("completed", []))
            failed_node_names.update(exec_result.get("failed", []))

            # If any node failed and there are completed nodes with compensation
            # commands, trigger saga compensation immediately.
            if exec_result.get("failed"):
                has_compensation = any(
                    n.compensation_command
                    for n in fragment.nodes
                    if n.name in completed_node_names
                )
                if has_compensation:
                    await self._trigger_compensation(workflow_id, fragment, completed_node_names)
                    await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                    return WorkflowResult(
                        status="failed",
                        reason="node_failure",
                        cycle_count=cycle_count,
                        llm_tokens_accumulated=llm_tokens_accumulated,
                        workflow_id=workflow_id,
                    )

            # -- 4. EVALUATE --------------------------------------------------
            decision = await self._evaluator.evaluate(fragment, goal)

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.EVALUATION_RESULT,
                {
                    "cycle": cycle_count,
                    "decision": decision.name if hasattr(decision, "name") else str(decision),
                    "reason": getattr(decision, "reason", ""),
                },
                seq,
            )

            # Build history entry for this cycle
            history.append({
                "cycle": cycle_count,
                "observation": observation,
                "fragment": fragment.model_dump() if hasattr(fragment, "model_dump") else repr(fragment),
                "execution": exec_result,
                "decision": decision.name if hasattr(decision, "name") else str(decision),
                "decision_reason": getattr(decision, "reason", ""),
            })

            # Truncate/summarize history to bound memory usage. We reassign to a
            # new list so that any references held by the planner (e.g. test stubs
            # recording the passed-in history) see the state at plan time rather
            # than a later mutation.
            history = self._maybe_summarize_history(history)

            # Check if planner signaled goal achieved
            if getattr(fragment, "goal_achieved", False):
                decision = EvaluatorDecision.DONE

            if decision == "DONE" or decision == EvaluatorDecision.DONE:
                await self._update_workflow_status(workflow_id, WorkflowStatus.COMPLETED)
                return WorkflowResult(
                    status="completed",
                    reason="Goal achieved",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )
            elif decision == "ESCALATE" or decision == EvaluatorDecision.ESCALATE:
                reason = getattr(decision, "reason", "evaluator_escalated")
                # Tier 4: human escalation -- pause workflow and persist state.
                seq += 1
                await self._emit_workflow_event(
                    workflow_id,
                    TaskEventType.ESCALATE,
                    {"reason": reason, "cycle": cycle_count},
                    seq,
                )
                await self._pause_workflow(
                    workflow_id,
                    reason=reason,
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    history=history,
                )
                seq += 1
                await self._emit_workflow_event(
                    workflow_id,
                    TaskEventType.WORKFLOW_PAUSED,
                    {"reason": reason, "cycle": cycle_count},
                    seq,
                )
                return WorkflowResult(
                    status="paused",
                    reason=reason,
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )
            elif decision == "REPLAN" or decision == EvaluatorDecision.REPLAN:
                # Tier 2: scoped replan -- continue with history preserved.
                continue
            else:
                # CONTINUE or unrecognized -- keep cycling
                continue

    # -- persistence helpers ------------------------------------------------

    async def _create_workflow(self, goal: str) -> Workflow:
        """Create a Workflow record in the database with status RUNNING."""
        # Ensure the database is initialized (no-op if already initialized).
        from celeste.database.db import init_db

        await init_db(settings=self._settings)

        workflow = Workflow(
            id=uuid.uuid4(),
            name=goal,
            status=WorkflowStatus.RUNNING,
            dag_definition={"goal": goal},
        )
        async with get_session() as session:
            session.add(workflow)
            await session.flush()
            # Refresh so the returned object has the generated id and defaults.
            await session.refresh(workflow)
            # Return a detached copy so subsequent sessions can load it.
            session.expunge(workflow)
        return workflow

    async def _update_workflow_status(
        self,
        workflow_id: uuid.UUID,
        status: WorkflowStatus,
    ) -> None:
        """Update the workflow status in the database."""
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is not None:
                workflow.status = status

    async def _emit_workflow_event(
        self,
        workflow_id: uuid.UUID,
        event_type: TaskEventType,
        event_data: dict[str, Any],
        sequence_number: int,
    ) -> None:
        """Write a WorkflowEvent row for the workflow."""
        async with get_session() as session:
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    event_type=event_type,
                    event_data=event_data,
                    sequence_number=sequence_number,
                )
            )

    async def _pause_workflow(
        self,
        workflow_id: uuid.UUID,
        reason: str,
        cycle_count: int,
        llm_tokens_accumulated: int,
        history: list[dict[str, Any]],
    ) -> None:
        """Pause a workflow and persist loop state for later resume."""
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                return

            workflow.status = WorkflowStatus.PAUSED
            workflow.paused_at = _utcnow()

            # Serialize loop state into dag_definition.
            dag_def = dict(workflow.dag_definition or {})
            dag_def["_opa_state"] = {
                "cycle_count": cycle_count,
                "llm_tokens_accumulated": llm_tokens_accumulated,
                "history": history,
                "pause_reason": reason,
            }
            workflow.dag_definition = dag_def

    async def resume(
        self,
        workflow_id: uuid.UUID,
        human_input: str,
    ) -> WorkflowResult:
        """Resume a paused workflow with human guidance.

        Loads the workflow, verifies it is PAUSED, restores loop state from
        dag_definition["_opa_state"], injects human_input into the next
        observation, and continues the OPA loop.
        """
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                raise ValueError(f"Workflow {workflow_id} not found")
            if workflow.status not in (WorkflowStatus.PAUSED, WorkflowStatus.RUNNING):
                raise ValueError(
                    f"Workflow {workflow_id} is not paused (status={workflow.status.value})"
                )

            opa_state = workflow.dag_definition.get("_opa_state", {}) if workflow.dag_definition else {}
            cycle_count = opa_state.get("cycle_count", 0)
            llm_tokens_accumulated = opa_state.get("llm_tokens_accumulated", 0)
            history = list(opa_state.get("history", []))

            # Record human_input and clear paused_at even when resume is
            # called directly (Engine.resume_workflow() also does this).
            workflow.human_input = human_input
            workflow.paused_at = None

        # Find the max sequence number to continue monotonic ordering.
        async with get_session() as session:
            result = await session.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == workflow_id)
                .order_by(WorkflowEvent.sequence_number.desc())
                .limit(1)
            )
            last_event = result.scalar_one_or_none()
            seq = last_event.sequence_number if last_event else 0

        seq += 1
        await self._emit_workflow_event(
            workflow_id,
            TaskEventType.HUMAN_INPUT_RECEIVED,
            {"human_input": human_input},
            seq,
        )

        seq += 1
        await self._emit_workflow_event(
            workflow_id,
            TaskEventType.WORKFLOW_RESUMED,
            {"cycle": cycle_count},
            seq,
        )

        # Inject human input as an artificial observation and continue looping.
        max_cycles = self._settings.MAX_OPA_CYCLES
        max_llm_tokens = self._settings.MAX_LLM_TOKENS

        # We don't have an agent here in the Engine.resume_workflow path,
        # so resume requires agent/planner/evaluator to be set on the loop.
        if self._agent is None or self._planner is None or self._evaluator is None:
            raise ValueError("Agent, planner, and evaluator are required to resume a workflow")

        while True:
            cycle_count += 1
            if cycle_count > max_cycles:
                await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                return WorkflowResult(
                    status="escalated",
                    reason="max_cycles_exceeded",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            llm_tokens_accumulated += 100
            if llm_tokens_accumulated >= max_llm_tokens:
                await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                return WorkflowResult(
                    status="escalated",
                    reason="token_budget_exceeded",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.CYCLE_STARTED,
                {"cycle": cycle_count},
                seq,
            )

            try:
                observation = await self._agent.call_tool("snapshot", {})
            except Exception as exc:
                logger.error("Agent unreachable during observation: %s", exc)
                await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            # Inject human_input into the observation for the planner.
            if isinstance(observation, dict):
                observation["human_input"] = human_input
            else:
                observation = {"raw": observation, "human_input": human_input}

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.OBSERVATION_CAPTURED,
                {"observation": observation},
                seq,
            )

            try:
                tool_schemas = await self._agent.list_tools()
            except Exception as exc:
                logger.error("Agent unreachable listing tools: %s", exc)
                await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )

            try:
                fragment = await self._planner.plan(
                    goal=workflow.name,
                    observation=observation,
                    tool_schemas=tool_schemas,
                    history=history,
                )
            except PlannerTimeoutError:
                if cycle_count == 1:
                    await self._update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
                    return WorkflowResult(
                        status="escalated",
                        reason="planner_timeout_no_progress",
                        cycle_count=cycle_count,
                        llm_tokens_accumulated=llm_tokens_accumulated,
                        workflow_id=workflow_id,
                    )
                continue

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.PLAN_GENERATED,
                {
                    "cycle": cycle_count,
                    "dag_def": fragment.model_dump(),
                    "reasoning": fragment.reasoning,
                },
                seq,
            )

            await self._persist_fragment(workflow_id, fragment)

            exec_result = await self._execute_with_retries(fragment)

            # Emit SECURITY_AUDIT events for each audited tool call.
            seq = await self._emit_security_audit_events(
                workflow_id, seq, exec_result.get("audit_results", [])
            )

            completed_node_names: set[str] = set()
            failed_node_names: set[str] = set()
            completed_node_names.update(exec_result.get("completed", []))
            failed_node_names.update(exec_result.get("failed", []))

            if exec_result.get("failed"):
                has_compensation = any(
                    n.compensation_command
                    for n in fragment.nodes
                    if n.name in completed_node_names
                )
                if has_compensation:
                    await self._trigger_compensation(workflow_id, fragment, completed_node_names)
                    await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
                    return WorkflowResult(
                        status="failed",
                        reason="node_failure",
                        cycle_count=cycle_count,
                        llm_tokens_accumulated=llm_tokens_accumulated,
                        workflow_id=workflow_id,
                    )

            decision = await self._evaluator.evaluate(fragment, workflow.name)

            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.EVALUATION_RESULT,
                {
                    "cycle": cycle_count,
                    "decision": decision.name if hasattr(decision, "name") else str(decision),
                    "reason": getattr(decision, "reason", ""),
                },
                seq,
            )

            history.append({
                "cycle": cycle_count,
                "observation": observation,
                "fragment": fragment.model_dump() if hasattr(fragment, "model_dump") else repr(fragment),
                "execution": exec_result,
                "decision": decision.name if hasattr(decision, "name") else str(decision),
                "decision_reason": getattr(decision, "reason", ""),
            })
            history = self._maybe_summarize_history(history)

            if getattr(fragment, "goal_achieved", False):
                decision = EvaluatorDecision.DONE

            if decision == "DONE" or decision == EvaluatorDecision.DONE:
                await self._update_workflow_status(workflow_id, WorkflowStatus.COMPLETED)
                return WorkflowResult(
                    status="completed",
                    reason="Goal achieved",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )
            elif decision == "ESCALATE" or decision == EvaluatorDecision.ESCALATE:
                reason = getattr(decision, "reason", "evaluator_escalated")
                await self._pause_workflow(
                    workflow_id,
                    reason=reason,
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    history=history,
                )
                seq += 1
                await self._emit_workflow_event(
                    workflow_id,
                    TaskEventType.WORKFLOW_PAUSED,
                    {"reason": reason, "cycle": cycle_count},
                    seq,
                )
                return WorkflowResult(
                    status="paused",
                    reason=reason,
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                    workflow_id=workflow_id,
                )
            elif decision == "REPLAN" or decision == EvaluatorDecision.REPLAN:
                continue
            else:
                continue

    async def _persist_fragment(
        self,
        workflow_id: uuid.UUID,
        fragment: DAGFragment,
    ) -> None:
        """Persist fragment nodes as TaskNode records for the workflow."""
        async with get_session() as session:
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            if workflow is None:
                return

            for node in fragment.nodes:
                task_node = TaskNode(
                    id=uuid.uuid4(),
                    workflow_id=workflow_id,
                    name=node.name,
                    task_type=node.task_type,
                    status=TaskNodeStatus.PENDING,
                    command=node.command,
                    arguments=node.arguments,
                    previous_node_ids=list(node.dependencies),
                    next_node_ids=[],
                    compensation_command=node.compensation_command,
                    compensation_arguments=node.compensation_arguments,
                )
                session.add(task_node)

            # Merge fragment into dag_definition for auditability.
            dag_def = dict(workflow.dag_definition or {})
            fragments = list(dag_def.get("fragments", []))
            fragments.append(fragment.model_dump())
            dag_def["fragments"] = fragments
            workflow.dag_definition = dag_def

    # -- compensation helper ------------------------------------------------

    async def _trigger_compensation(
        self,
        workflow_id: uuid.UUID,
        fragment: DAGFragment,
        completed_node_names: set[str],
    ) -> None:
        """Trigger saga compensation for completed nodes that have compensation commands.

        Compensation is executed in reverse order of completion. Independent
        branches (nodes not on the failed path) are not rolled back.
        """
        # Build ordered list of completed nodes in this fragment based on
        # fragment node order (planner is expected to emit dependents after
        # dependencies). Reverse so most recently completed is compensated first.
        nodes_to_compensate = [
            node for node in fragment.nodes
            if node.name in completed_node_names and node.compensation_command
        ]
        nodes_to_compensate.reverse()

        if not nodes_to_compensate:
            return

        async with get_session() as session:
            result = await session.execute(
                select(TaskNode).where(
                    TaskNode.workflow_id == workflow_id,
                    TaskNode.name.in_([n.name for n in nodes_to_compensate]),
                )
            )
            db_node_map = {n.name: n for n in result.scalars().all()}

        for node in nodes_to_compensate:
            db_node = db_node_map.get(node.name)
            if db_node is None:
                continue

            async with get_session() as session:
                session.add(
                    TaskEvent(
                        task_node_id=db_node.id,
                        workflow_id=workflow_id,
                        event_type=TaskEventType.COMPENSATION_TRIGGERED,
                        event_data={
                            "compensation_command": node.compensation_command,
                            "compensation_arguments": node.compensation_arguments or {},
                        },
                    )
                )

            try:
                await self._agent.call_tool(
                    node.compensation_command,
                    node.compensation_arguments or {},
                )
                async with get_session() as session:
                    session.add(
                        TaskEvent(
                            task_node_id=db_node.id,
                            workflow_id=workflow_id,
                            event_type=TaskEventType.COMPENSATION_COMPLETED,
                            event_data={
                                "compensation_command": node.compensation_command,
                            },
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Compensation failed for node %s (%s): %s",
                    db_node.id,
                    node.name,
                    exc,
                )
                async with get_session() as session:
                    session.add(
                        TaskEvent(
                            task_node_id=db_node.id,
                            workflow_id=workflow_id,
                            event_type=TaskEventType.COMPENSATION_FAILED,
                            event_data={
                                "compensation_command": node.compensation_command,
                                "error": str(exc),
                            },
                        )
                    )

    # -- private helpers ----------------------------------------------------

    async def _emit_security_audit_events(
        self,
        workflow_id: uuid.UUID,
        seq: int,
        audit_results: list[dict[str, Any]],
    ) -> int:
        """Emit SECURITY_AUDIT WorkflowEvents for each audited tool call.

        Returns the next available sequence number.
        """
        for audit in audit_results:
            seq += 1
            await self._emit_workflow_event(
                workflow_id,
                TaskEventType.SECURITY_AUDIT,
                {
                    "node_name": audit.get("node_name"),
                    "tool_name": audit.get("tool_name"),
                    "arguments": audit.get("arguments"),
                    "is_safe": audit.get("is_safe"),
                    "risk_level": audit.get("risk_level"),
                    "reason": audit.get("reason"),
                    "detected_threats": audit.get("detected_threats", []),
                },
                seq,
            )
        return seq

    async def _execute_with_retries(
        self,
        fragment: DAGFragment,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Execute a fragment with Tier 1 retry logic.

        Retries transient failures up to max_retries times with
        exponential backoff. Completed and skipped nodes from earlier
        attempts are preserved in the final result.
        """
        accumulated_completed: list[str] = []
        accumulated_skipped: list[str] = []
        accumulated_audit: list[dict[str, Any]] = []
        original_fragment = fragment

        for attempt in range(max_retries + 1):
            exec_result = await self._executor.execute_fragment(fragment)

            # Accumulate successes and skips from this attempt.
            accumulated_completed.extend(exec_result.get("completed", []))
            accumulated_skipped.extend(exec_result.get("skipped", []))
            accumulated_audit.extend(exec_result.get("audit_results", []))

            # Check for transient failures
            failed_nodes = exec_result.get("failed", [])
            security_blocked = exec_result.get("security_blocked", [])
            if not failed_nodes:
                return {
                    "completed": list(dict.fromkeys(accumulated_completed)),
                    "failed": [],
                    "skipped": list(dict.fromkeys(accumulated_skipped)),
                    "audit_results": accumulated_audit,
                }

            # Security-blocked nodes are not retryable (they are deterministic
            # blocks, not transient failures).
            retryable_failures = [
                n for n in failed_nodes if n not in security_blocked
            ]

            # If all failures are security blocks, stop retrying.
            if not retryable_failures or attempt >= max_retries:
                return {
                    "completed": list(dict.fromkeys(accumulated_completed)),
                    "failed": failed_nodes,
                    "skipped": list(dict.fromkeys(accumulated_skipped)),
                    "audit_results": accumulated_audit,
                }

            # Exponential backoff: 1s, 2s, 4s
            backoff = 2 ** attempt
            logger.info("Tier 1 retry: waiting %ds before retry %d/%d", backoff, attempt + 1, max_retries)
            await asyncio.sleep(backoff)

            # Rebuild fragment with only retryable failed nodes for retry.
            # Security-blocked nodes are excluded.
            # Dependencies are cleared because they were already satisfied in
            # earlier attempts.
            retry_nodes = []
            for n in fragment.nodes:
                if n.name in retryable_failures:
                    retry_nodes.append(
                        DAGNode(
                            name=n.name,
                            task_type=n.task_type,
                            command=n.command,
                            arguments=n.arguments,
                            dependencies=[],
                            compensation_command=n.compensation_command,
                            compensation_arguments=n.compensation_arguments,
                        )
                    )
            fragment = DAGFragment(
                nodes=retry_nodes,
                reasoning=f"Retry after transient failure (attempt {attempt + 1})",
                estimated_remaining=fragment.estimated_remaining,
                goal_achieved=fragment.goal_achieved,
            )

        return {
            "completed": list(dict.fromkeys(accumulated_completed)),
            "failed": exec_result.get("failed", []),
            "skipped": list(dict.fromkeys(accumulated_skipped)),
            "audit_results": accumulated_audit,
        }
