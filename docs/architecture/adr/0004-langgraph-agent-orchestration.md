# ADR 0004: LangGraph for Stateful AI Agent Orchestration

- **Status**: Accepted
- **Deciders**: EduIntel Engineering Team
- **Date**: 2026-10-20

---

## Context and Problem Statement

EduIntel requires autonomous AI assistants capable of executing multi-step reasoning, tool invocation, and decision-making:
1. **Admin Assistant**: Answering administrative questions (e.g., unpaid fees, unassigned teachers, attendance percentages) by dynamically calling reporting tools.
2. **Portal Assistant**: Conversational navigation and workflow guidance using RAG.

Traditional linear LLM chains (e.g. LangChain `LLMChain` or standard ReAct prompts) have well-known failure modes:
- Tendency to loop endlessly or fail to terminate cleanly when tools fail.
- Poor state observability and inability to inspect intermediate reasoning nodes.
- Lack of deterministic control over the execution graph, making security containment difficult.

We needed an agent framework that supports stateful cyclic graphs, explicit tool governance, checkpointing, and trace observability.

---

## Decision Outcome

We selected **LangGraph** (version 0.1.0) as the core agent orchestration engine.

### Architectural Rules:
- Agent workflows are compiled as explicit state graphs with typed state dictionaries (`MessagesState` or custom state schemas).
- Graph transitions between reasoning nodes, tool execution nodes, and response synthesis nodes are explicitly defined.
- In Phase 0A, the Admin Assistant's previous unrestricted SQL tool was deprecated and replaced with **6 safe, parameterized reporting tools** (`query_fee_summary`, `query_teacher_salaries`, `query_timetable_coverage`, `query_student_attendance`, `query_exam_performance`, `query_at_risk_students`).
- Agent execution steps and tool invocations are logged to `agent_trace_logs` via the observability module for auditability.

---

## Consequences

### Positive Consequences
- **Deterministic Control**: The state machine strictly limits which tools can be invoked and ensures the agent always reaches an end node.
- **Traceability & Auditing**: Every node transition and tool output is inspectable and recorded in PostgreSQL `agent_trace_logs`.
- **Security Containment**: Arbitrary code/SQL execution is prevented by defining strict Pydantic schemas for all tool inputs.

### Negative Consequences
- **Framework Overhead**: LangGraph introduces additional abstractions and dependencies (`langgraph`, `langchain-core`) that must be kept updated.
- **Latency**: Multi-turn agent loops involving several tool calls can take 3–7 seconds per query if tools run sequentially.

---

## Alternatives Considered

- **Raw ReAct Prompting / LangChain AgentExecutor**: Rejected due to frequent infinite loops, lack of explicit graph transitions, and deprecation of `AgentExecutor` in modern LangChain.
- **Autogen / CrewAI**: Evaluated but rejected as overly heavyweight for single-agent administrative workflows, requiring unnecessary multi-agent communication overhead.

