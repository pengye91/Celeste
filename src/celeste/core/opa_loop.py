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
import logging
from typing import Any

from celeste.config.settings import EngineSettings, get_settings
from celeste.core.evaluator import Evaluator, EvaluatorDecision
from celeste.core.exceptions import PlannerTimeoutError
from celeste.core.planner import DAGFragment, DAGNode, Planner

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


# ---------------------------------------------------------------------------
# WorkflowExecutor
# ---------------------------------------------------------------------------


class WorkflowExecutor:
    """Executes a DAGFragment by calling tools via the agent.

    For this implementation, nodes are executed sequentially respecting
    dependencies. Each node is invoked via agent.call_tool().
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def execute_fragment(self, fragment: DAGFragment) -> dict[str, Any]:
        """Execute all nodes in the fragment sequentially.

        Returns a dict with:
            - completed: list of node names that succeeded
            - failed: list of node names that failed
            - skipped: list of node names skipped due to failed dependencies
        """
        completed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []

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
    ) -> None:
        self._agent = agent
        self._planner = planner
        self._evaluator = evaluator
        self._settings = settings or get_settings()
        self._executor = WorkflowExecutor(agent)

    # -- public API ---------------------------------------------------------

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

        while True:
            # -- Safety limits ------------------------------------------------
            cycle_count += 1
            if cycle_count >= max_cycles:
                return WorkflowResult(
                    status="escalated",
                    reason="max_cycles_exceeded",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                )
            # Heuristic: each OPA cycle consumes some tokens (observation + plan + evaluate)
            # In production this would come from actual LLM usage metadata
            llm_tokens_accumulated += 100
            if llm_tokens_accumulated >= max_llm_tokens:
                return WorkflowResult(
                    status="escalated",
                    reason="token_budget_exceeded",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                )

            # -- 1. OBSERVE ---------------------------------------------------
            try:
                observation = await self._agent.call_tool("snapshot", {})
            except Exception as exc:
                logger.error("Agent unreachable during observation: %s", exc)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,  # no cycle completed
                    llm_tokens_accumulated=llm_tokens_accumulated,
                )

            try:
                tool_schemas = await self._agent.list_tools()
            except Exception as exc:
                logger.error("Agent unreachable listing tools: %s", exc)
                return WorkflowResult(
                    status="failed",
                    reason="agent_unreachable",
                    cycle_count=cycle_count - 1,
                    llm_tokens_accumulated=llm_tokens_accumulated,
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
                    return WorkflowResult(
                        status="escalated",
                        reason="planner_timeout_no_progress",
                        cycle_count=cycle_count,
                        llm_tokens_accumulated=llm_tokens_accumulated,
                    )
                # Retry with simplified prompt on next cycle
                continue

            # -- 3. ACT -------------------------------------------------------
            # Tier 1: retry transient failures
            exec_result = await self._execute_with_retries(fragment)

            # -- 4. EVALUATE --------------------------------------------------
            decision = await self._evaluator.evaluate(fragment, goal)

            # Build history entry for this cycle
            history.append({
                "cycle": cycle_count,
                "observation": observation,
                "fragment": fragment.model_dump() if hasattr(fragment, "model_dump") else repr(fragment),
                "execution": exec_result,
                "decision": decision.name if hasattr(decision, "name") else str(decision),
                "decision_reason": getattr(decision, "reason", ""),
            })

            # Check if planner signaled goal achieved
            if getattr(fragment, "goal_achieved", False):
                decision = EvaluatorDecision.DONE

            if decision == "DONE" or decision == EvaluatorDecision.DONE:
                return WorkflowResult(
                    status="completed",
                    reason="Goal achieved",
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                )
            elif decision == "ESCALATE" or decision == EvaluatorDecision.ESCALATE:
                reason = getattr(decision, "reason", "evaluator_escalated")
                return WorkflowResult(
                    status="escalated",
                    reason=reason,
                    cycle_count=cycle_count,
                    llm_tokens_accumulated=llm_tokens_accumulated,
                )
            elif decision == "REPLAN" or decision == EvaluatorDecision.REPLAN:
                # Tier 2: scoped replan -- continue with history preserved
                continue
            else:
                # CONTINUE or unrecognized -- keep cycling
                continue

    # -- private helpers ----------------------------------------------------

    async def _execute_with_retries(
        self,
        fragment: DAGFragment,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Execute a fragment with Tier 1 retry logic.

        Retries transient failures up to max_retries times with
        exponential backoff.
        """
        for attempt in range(max_retries + 1):
            exec_result = await self._executor.execute_fragment(fragment)

            # Check for transient failures
            failed_nodes = exec_result.get("failed", [])
            if not failed_nodes:
                return exec_result

            # Check if failures are retryable (all have retryable flag)
            all_retryable = True
            for node in fragment.nodes:
                if node.name in failed_nodes:
                    # For this implementation, we assume retryable unless
                    # explicitly marked otherwise. In a real system, the
                    # agent/tool would indicate retryability.
                    pass

            if not all_retryable or attempt >= max_retries:
                return exec_result

            # Exponential backoff: 1s, 2s, 4s
            backoff = 2 ** attempt
            logger.info("Tier 1 retry: waiting %ds before retry %d/%d", backoff, attempt + 1, max_retries)
            await asyncio.sleep(backoff)

            # Rebuild fragment with only failed nodes for retry
            retry_nodes = [n for n in fragment.nodes if n.name in failed_nodes]
            fragment = DAGFragment(
                nodes=retry_nodes,
                reasoning=f"Retry after transient failure (attempt {attempt + 1})",
                estimated_remaining=fragment.estimated_remaining,
                goal_achieved=fragment.goal_achieved,
            )

        return exec_result
