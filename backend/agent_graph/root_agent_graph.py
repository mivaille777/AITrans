"""Canonical LangGraph entry point for Agent Runtime v1.

The existing reading, ReAct, and multi-agent nodes share one compiled graph
and one Run ID/checkpointer. Keeping the established node names lets paused
pre-Stage-6 runs resume without replaying completed work.
"""

from __future__ import annotations

from backend.agent_graph.reading_agent_graph import ReadingAgentGraph


class RootAgentGraph(ReadingAgentGraph):
    """Production root graph; ReadingAgentGraph remains the compatibility API."""

    graph_role = "canonical_root"


__all__ = ["RootAgentGraph"]
