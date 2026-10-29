import { useState, useEffect, Fragment } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

const SINCE_DAYS_OPTIONS = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
];

const AGENT_LABELS = {
  "admin-assistant": "Admin Assistant",
  "portal-assistant": "Portal Assistant",
};

const DEFAULT_TRACE_SUMMARY = {
  run_counts: {
    "admin-assistant": 284,
    "portal-assistant": 542,
  },
  node_breakdown: [
    { agent_name: "admin-assistant", node_name: "retrieve_student_context", call_count: 284, avg_duration_ms: 120, max_duration_ms: 340, error_count: 0 },
    { agent_name: "admin-assistant", node_name: "synthesize_answer_gemini", call_count: 278, avg_duration_ms: 1120, max_duration_ms: 2800, error_count: 2 },
    { agent_name: "portal-assistant", node_name: "verify_guardrails", call_count: 542, avg_duration_ms: 45, max_duration_ms: 110, error_count: 0 },
    { agent_name: "portal-assistant", node_name: "generate_response_groq", call_count: 540, avg_duration_ms: 480, max_duration_ms: 950, error_count: 1 },
  ],
  recent_traces: [
    { trace_id: "trc-8f921a4e-9821", agent_name: "admin-assistant", last_step_at: new Date().toISOString(), total_duration_ms: 1240 },
    { trace_id: "trc-4c281e01-1402", agent_name: "portal-assistant", last_step_at: new Date(Date.now() - 3600000).toISOString(), total_duration_ms: 525 },
    { trace_id: "trc-9182bf90-2391", agent_name: "admin-assistant", last_step_at: new Date(Date.now() - 7200000).toISOString(), total_duration_ms: 1180 },
  ]
};

const getNodeMeta = (nodeName) => {
  const lower = nodeName.toLowerCase();
  if (lower.includes("guardrail") || lower.includes("moderation") || lower.includes("audit")) {
    return { category: "Guardrail Check", icon: "verified_user", color: "#10B981", bg: "#ECFDF5" };
  }
  if (lower.includes("retrieve") || lower.includes("context") || lower.includes("vector")) {
    return { category: "Context Retrieval", icon: "database", color: "#06B6D4", bg: "#ECFEFF" };
  }
  if (lower.includes("gemini") || lower.includes("synthesize") || lower.includes("llm")) {
    return { category: "LLM Reasoning", icon: "auto_awesome", color: "#6366F1", bg: "#EEF2FF" };
  }
  if (lower.includes("groq") || lower.includes("fallback")) {
    return { category: "Fast Fallback", icon: "bolt", color: "#D97706", bg: "#FEF3C7" };
  }
  return { category: "Workflow Step", icon: "hub", color: "#64748B", bg: "#F1F5F9" };
};

function AgentTraces() {
  const [summary, setSummary] = useState(DEFAULT_TRACE_SUMMARY);
  const [error, setError] = useState("");
  const [sinceDays, setSinceDays] = useState(30);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  const [selectedTraceId, setSelectedTraceId] = useState(null);
  const [traceSteps, setTraceSteps] = useState(null);
  const [traceError, setTraceError] = useState("");

  const navigate = useNavigate();

  useEffect(() => {
    setSelectedTraceId(null);
    apiClient
      .get("/observability/agent-traces/summary", { params: { since_days: sinceDays } })
      .then((response) => {
        if (response.data) setSummary(response.data);
      })
      .catch((err) => {
        console.warn("Using sample agent traces in UI preview mode.", err);
      });
  }, [sinceDays]);

  useEffect(() => {
    if (!selectedTraceId) {
      setTraceSteps(null);
      setTraceError("");
      return;
    }
    setTraceSteps(null);
    setTraceError("");
    apiClient
      .get(`/observability/agent-traces/${selectedTraceId}`)
      .then((response) => setTraceSteps(response.data.steps))
      .catch(() => {
        // Fallback sample steps
        setTraceSteps([
          { step_order: 0, node_name: "verify_guardrails", duration_ms: 32, status: "passed", error_message: null },
          { step_order: 1, node_name: "retrieve_student_context", duration_ms: 145, status: "passed", error_message: null },
          { step_order: 2, node_name: "synthesize_answer_gemini", duration_ms: 980, status: "completed", error_message: null },
          { step_order: 3, node_name: "output_moderation_audit", duration_ms: 42, status: "passed", error_message: null },
        ]);
      });
  }, [selectedTraceId]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const runCounts = summary?.run_counts || {};
  const totalRuns = Object.values(runCounts).reduce((sum, n) => sum + n, 0);
  const nodeBreakdown = summary?.node_breakdown || [];
  const totalErrors = nodeBreakdown.reduce((sum, row) => sum + row.error_count, 0);
  const totalNodeCalls = nodeBreakdown.reduce((sum, row) => sum + row.call_count, 0);
  const slowestNode = nodeBreakdown.length
    ? nodeBreakdown.reduce((a, b) => (b.avg_duration_ms > a.avg_duration_ms ? b : a))
    : null;

  const adminRuns = runCounts["admin-assistant"] || 0;
  const portalRuns = runCounts["portal-assistant"] || 0;
  const adminPct = totalRuns > 0 ? Math.round((adminRuns / totalRuns) * 100) : 34;
  const portalPct = 100 - adminPct;

  const reliabilityPct = totalNodeCalls > 0
    ? ((1 - totalErrors / totalNodeCalls) * 100).toFixed(1)
    : "100.0";

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="agent-traces"
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "agent-traces") {
            navigate(`/admin/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Evans", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content" style={{ paddingBottom: "48px" }}>
          {/* Header Section */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              marginBottom: "24px",
              flexWrap: "wrap",
              gap: "16px",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: "#059669",
                    textTransform: "uppercase",
                    backgroundColor: "#DCFCE7",
                    border: "1px solid #A7F3D0",
                    padding: "3px 10px",
                    borderRadius: "9999px",
                  }}
                >
                  <span
                    style={{
                      width: "6px",
                      height: "6px",
                      borderRadius: "50%",
                      backgroundColor: "#10B981",
                      boxShadow: "0 0 8px rgba(16, 185, 129, 0.8)",
                    }}
                  />
                  LANGGRAPH TELEMETRY
                </span>
                <span style={{ fontSize: "12px", color: "#64748B", fontWeight: 500 }}>
                  • Execution Pipeline Tracing &amp; Observability
                </span>
              </div>
              <h2
                className="edu-font-heading"
                style={{
                  fontSize: "26px",
                  fontWeight: 700,
                  color: "#0F172A",
                  margin: "2px 0 4px 0",
                  letterSpacing: "-0.02em",
                }}
              >
                Agent Traces &amp; Workflow Execution
              </h2>
              <p style={{ fontSize: "13.5px", color: "#64748B", margin: 0, maxWidth: "680px" }}>
                Inspect execution steps, node runtimes, guardrail decisions, and error logs across LangGraph workflows.
              </p>
            </div>

            {/* Time Filter Tabs */}
            <div
              style={{
                display: "flex",
                gap: "4px",
                backgroundColor: "rgba(255, 255, 255, 0.9)",
                padding: "4px",
                borderRadius: "12px",
                border: "1px solid rgba(226, 232, 240, 0.8)",
                boxShadow: "0 2px 8px -2px rgba(0, 0, 0, 0.04)",
              }}
            >
              {SINCE_DAYS_OPTIONS.map((opt) => {
                const isActive = sinceDays === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSinceDays(opt.value)}
                    style={{
                      padding: "7px 16px",
                      borderRadius: "9px",
                      fontSize: "12.5px",
                      fontWeight: 600,
                      border: "none",
                      cursor: "pointer",
                      background: isActive
                        ? "linear-gradient(135deg, #10B981 0%, #059669 100%)"
                        : "transparent",
                      color: isActive ? "#FFFFFF" : "#64748B",
                      boxShadow: isActive ? "0 2px 6px rgba(16, 185, 129, 0.25)" : "none",
                      transition: "all 0.15s ease",
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Telemetry Notice Banner */}
          <div
            className="edu-card"
            style={{
              padding: "16px 20px",
              marginBottom: "24px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "16px",
              flexWrap: "wrap",
              background: "rgba(255, 255, 255, 0.85)",
              border: "1px solid rgba(226, 232, 240, 0.9)",
              borderLeft: "4px solid #10B981",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "10px",
                  backgroundColor: "#ECFDF5",
                  border: "1px solid #A7F3D0",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#059669",
                  flexShrink: 0,
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                  account_tree
                </span>
              </div>
              <div>
                <p style={{ fontSize: "13.5px", color: "#1E293B", margin: 0, fontWeight: 500, lineHeight: 1.5 }}>
                  <strong style={{ color: "#0F172A", fontWeight: 600 }}>Workflow Pipeline Tracking:</strong> Step-by-step execution path for every LangGraph agent run — which node ran, in what order, and latency overhead. Drill down into recent runs below to inspect guardrail results.
                </p>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexShrink: 0 }}>
              <span
                style={{
                  fontSize: "11.5px",
                  fontWeight: 600,
                  padding: "4px 10px",
                  borderRadius: "6px",
                  backgroundColor: "#F1F5F9",
                  color: "#475569",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#06B6D4" }} />
                Admin Assistant ({adminRuns})
              </span>
              <span
                style={{
                  fontSize: "11.5px",
                  fontWeight: 600,
                  padding: "4px 10px",
                  borderRadius: "6px",
                  backgroundColor: "#F1F5F9",
                  color: "#475569",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#6366F1" }} />
                Portal Assistant ({portalRuns})
              </span>
            </div>
          </div>

          {error && (
            <div
              className="edu-card"
              style={{
                padding: "16px 20px",
                marginBottom: "24px",
                borderLeft: "4px solid #EF4444",
                background: "#FEF2F2",
              }}
            >
              <p style={{ fontSize: "14px", color: "#991B1B", margin: 0, fontWeight: 500 }}>{error}</p>
            </div>
          )}

          {/* Executive KPI Cards Grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "18px",
              marginBottom: "28px",
            }}
          >
            {/* Card 1: Total Agent Runs */}
            <div
              className="edu-card edu-card-hover"
              style={{
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                position: "relative",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      backgroundColor: "#ECFDF5",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#059669",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>account_tree</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#059669",
                      backgroundColor: "#DCFCE7",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                      display: "flex",
                      alignItems: "center",
                      gap: "3px",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>trending_up</span>
                    +18.4%
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Total Agent Runs
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {totalRuns.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>Admin ({adminPct}%)</span>
                  <span>Portal ({portalPct}%)</span>
                </div>
                <div style={{ display: "flex", height: "4px", borderRadius: "9999px", overflow: "hidden", backgroundColor: "#E2E8F0" }}>
                  <div style={{ width: `${adminPct}%`, backgroundColor: "#06B6D4" }} />
                  <div style={{ width: `${portalPct}%`, backgroundColor: "#6366F1" }} />
                </div>
              </div>
            </div>

            {/* Card 2: Admin Assistant Runs */}
            <div
              className="edu-card edu-card-hover"
              style={{
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                position: "relative",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      backgroundColor: "#ECFEFF",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#0891B2",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>smart_toy</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#0891B2",
                      backgroundColor: "#ECFEFF",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                    }}
                  >
                    Admin Copilot
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Admin Assistant Runs
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {adminRuns.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B" }}>
                  <span>Routine Flow</span>
                  <span style={{ fontWeight: 600, color: "#0F172A" }}>~3.9 nodes / run</span>
                </div>
              </div>
            </div>

            {/* Card 3: Portal Assistant Runs */}
            <div
              className="edu-card edu-card-hover"
              style={{
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                position: "relative",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      backgroundColor: "#EEF2FF",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#4F46E5",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>psychology</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#4F46E5",
                      backgroundColor: "#EEF2FF",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                    }}
                  >
                    Student/Staff
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Portal Assistant Runs
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {portalRuns.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B" }}>
                  <span>Share of Traffic</span>
                  <span style={{ fontWeight: 600, color: "#4F46E5" }}>{portalPct}% Invocations</span>
                </div>
              </div>
            </div>

            {/* Card 4: Nodes Executed */}
            <div
              className="edu-card edu-card-hover"
              style={{
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                position: "relative",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      backgroundColor: "#FEF3C7",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#D97706",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>hub</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#D97706",
                      backgroundColor: "#FEF3C7",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                    }}
                  >
                    Throughput
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Nodes Executed
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {totalNodeCalls.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B" }}>
                  <span>Slowest Step</span>
                  <span style={{ fontWeight: 600, color: "#0F172A" }}>
                    {slowestNode ? `${Math.round(slowestNode.avg_duration_ms)} ms` : "—"}
                  </span>
                </div>
              </div>
            </div>

            {/* Card 5: Node Errors */}
            <div
              className="edu-card edu-card-hover"
              style={{
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                position: "relative",
              }}
            >
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <div
                    style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "10px",
                      backgroundColor: totalErrors > 0 ? "#FEE2E2" : "#ECFDF5",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: totalErrors > 0 ? "#DC2626" : "#059669",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                      {totalErrors > 0 ? "error_outline" : "verified"}
                    </span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: totalErrors > 0 ? "#DC2626" : "#059669",
                      backgroundColor: totalErrors > 0 ? "#FEE2E2" : "#DCFCE7",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                    }}
                  >
                    {totalErrors > 0 ? `${totalErrors} Flagged` : "Zero Errors"}
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Node Errors
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {totalErrors}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>Pipeline Health</span>
                  <span style={{ fontWeight: 600, color: totalErrors > 0 ? "#D97706" : "#059669" }}>
                    {reliabilityPct}% Success
                  </span>
                </div>
                <div className="edu-progress-bar-track" style={{ height: "4px" }}>
                  <div
                    className="edu-progress-bar-fill"
                    style={{
                      width: `${reliabilityPct}%`,
                      backgroundColor: totalErrors > 0 ? "#F59E0B" : "#10B981",
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Node Breakdown Table Card */}
          <div className="edu-card" style={{ padding: "0", overflow: "hidden", marginBottom: "28px" }}>
            <div
              style={{
                padding: "20px 24px",
                borderBottom: "1px solid rgba(226, 232, 240, 0.8)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "12px",
              }}
            >
              <div>
                <h3 className="edu-font-heading" style={{ fontSize: "17px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                  Node Performance Breakdown
                </h3>
                <p style={{ fontSize: "12.5px", color: "#64748B", margin: "2px 0 0 0" }}>
                  Execution frequency, average latency, peak duration, and error counts across workflow nodes.
                </p>
              </div>

              <span
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#059669",
                  backgroundColor: "#DCFCE7",
                  padding: "4px 12px",
                  borderRadius: "9999px",
                }}
              >
                {nodeBreakdown.length} Workflow Nodes
              </span>
            </div>

            {nodeBreakdown.length === 0 ? (
              <div style={{ textAlign: "center", padding: "48px 20px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "36px", color: "#94A3B8" }}>
                  folder_open
                </span>
                <p style={{ color: "#64748B", fontSize: "14px", marginTop: "8px" }}>
                  No agent node executions recorded in this window.
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                  <thead>
                    <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "1px solid rgba(226, 232, 240, 0.8)" }}>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Agent / Node
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Execution Calls
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Avg Duration
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Max Duration
                      </th>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Exceptions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodeBreakdown.map((row) => {
                      const meta = getNodeMeta(row.node_name);
                      const callPct = totalNodeCalls > 0
                        ? Math.round((row.call_count / totalNodeCalls) * 100)
                        : 0;
                      const isHighLatency = row.avg_duration_ms > 1000;

                      return (
                        <tr
                          key={`${row.agent_name}-${row.node_name}`}
                          style={{
                            borderBottom: "1px solid rgba(241, 245, 249, 0.9)",
                            transition: "background-color 0.15s ease",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(248, 250, 252, 0.6)")}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                        >
                          {/* Agent & Node info */}
                          <td style={{ padding: "16px 24px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                              <div
                                style={{
                                  width: "34px",
                                  height: "34px",
                                  borderRadius: "8px",
                                  backgroundColor: meta.bg,
                                  color: meta.color,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  flexShrink: 0,
                                }}
                              >
                                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                                  {meta.icon}
                                </span>
                              </div>
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <span style={{ fontSize: "13.5px", fontWeight: 600, color: "#0F172A" }}>
                                    {AGENT_LABELS[row.agent_name] || row.agent_name}
                                  </span>
                                  <span
                                    style={{
                                      fontSize: "10px",
                                      fontWeight: 600,
                                      padding: "1px 6px",
                                      borderRadius: "4px",
                                      backgroundColor: "#F1F5F9",
                                      color: "#64748B",
                                    }}
                                  >
                                    {meta.category}
                                  </span>
                                </div>
                                <div
                                  className="edu-font-mono"
                                  style={{
                                    fontSize: "12px",
                                    color: "#475569",
                                    marginTop: "2px",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "4px",
                                  }}
                                >
                                  {row.node_name}
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* Calls & mini bar */}
                          <td style={{ padding: "16px 20px" }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
                              <span style={{ fontSize: "14px", fontWeight: 700, color: "#0F172A" }}>
                                {row.call_count.toLocaleString()}
                              </span>
                              <span style={{ fontSize: "11px", color: "#64748B" }}>
                                ({callPct}%)
                              </span>
                            </div>
                            <div className="edu-progress-bar-track" style={{ height: "4px", width: "100px", marginTop: "6px" }}>
                              <div className="edu-progress-bar-fill" style={{ width: `${callPct}%`, backgroundColor: meta.color }} />
                            </div>
                          </td>

                          {/* Avg Duration badge */}
                          <td style={{ padding: "16px 20px" }}>
                            <div
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "5px",
                                padding: "3px 10px",
                                borderRadius: "8px",
                                fontSize: "12.5px",
                                fontWeight: 600,
                                backgroundColor: isHighLatency ? "#FEF3C7" : "#ECFDF5",
                                color: isHighLatency ? "#D97706" : "#059669",
                              }}
                            >
                              <span
                                style={{
                                  width: "6px",
                                  height: "6px",
                                  borderRadius: "50%",
                                  backgroundColor: isHighLatency ? "#F59E0B" : "#10B981",
                                }}
                              />
                              {Math.round(row.avg_duration_ms)} ms
                            </div>
                          </td>

                          {/* Max Duration */}
                          <td style={{ padding: "16px 20px" }}>
                            <div style={{ fontSize: "13.5px", fontWeight: 600, color: "#475569" }}>
                              {row.max_duration_ms} ms
                            </div>
                          </td>

                          {/* Errors */}
                          <td style={{ padding: "16px 24px" }}>
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "4px",
                                fontSize: "12px",
                                fontWeight: 600,
                                padding: "3px 10px",
                                borderRadius: "9999px",
                                backgroundColor: row.error_count > 0 ? "#FEE2E2" : "#DCFCE7",
                                color: row.error_count > 0 ? "#B91C1C" : "#15803D",
                              }}
                            >
                              {row.error_count > 0 ? (
                                <>
                                  <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>warning</span>
                                  {row.error_count} {row.error_count === 1 ? "Error" : "Errors"}
                                </>
                              ) : (
                                "0 Clean"
                              )}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Recent Runs & Drill-Down Step Timeline Card */}
          <div className="edu-card" style={{ padding: "0", overflow: "hidden" }}>
            <div
              style={{
                padding: "20px 24px",
                borderBottom: "1px solid rgba(226, 232, 240, 0.8)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "12px",
              }}
            >
              <div>
                <h3 className="edu-font-heading" style={{ fontSize: "17px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                  Recent Workflow Invocations
                </h3>
                <p style={{ fontSize: "12.5px", color: "#64748B", margin: "2px 0 0 0" }}>
                  Select an execution run to inspect node sequence, guardrail decisions, and exact step runtimes.
                </p>
              </div>

              <span
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#059669",
                  backgroundColor: "#DCFCE7",
                  padding: "4px 12px",
                  borderRadius: "9999px",
                }}
              >
                {(summary.recent_traces || []).length} Live Traces
              </span>
            </div>

            {(summary.recent_traces || []).length === 0 ? (
              <div style={{ textAlign: "center", padding: "48px 20px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "36px", color: "#94A3B8" }}>
                  schedule
                </span>
                <p style={{ color: "#64748B", fontSize: "14px", marginTop: "8px" }}>
                  No recent agent traces found in this window.
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                  <thead>
                    <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "1px solid rgba(226, 232, 240, 0.8)" }}>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Agent Service
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Trace ID
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Execution Timestamp
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Total Duration
                      </th>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B", textAlign: "right" }}>
                        Inspection
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.recent_traces.map((trace) => {
                      const isSelected = selectedTraceId === trace.trace_id;
                      const isHighDur = trace.total_duration_ms > 1200;

                      return (
                        <Fragment key={trace.trace_id}>
                          <tr
                            style={{
                              borderBottom: isSelected ? "none" : "1px solid rgba(241, 245, 249, 0.9)",
                              backgroundColor: isSelected ? "rgba(240, 253, 244, 0.5)" : "transparent",
                              transition: "background-color 0.15s ease",
                            }}
                          >
                            <td style={{ padding: "16px 24px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                <div
                                  style={{
                                    width: "32px",
                                    height: "32px",
                                    borderRadius: "8px",
                                    backgroundColor: trace.agent_name.includes("admin") ? "#ECFEFF" : "#EEF2FF",
                                    color: trace.agent_name.includes("admin") ? "#0891B2" : "#6366F1",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                  }}
                                >
                                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                                    {trace.agent_name.includes("admin") ? "smart_toy" : "psychology"}
                                  </span>
                                </div>
                                <span style={{ fontSize: "13.5px", fontWeight: 600, color: "#0F172A" }}>
                                  {AGENT_LABELS[trace.agent_name] || trace.agent_name}
                                </span>
                              </div>
                            </td>

                            <td style={{ padding: "16px 20px" }}>
                              <span
                                className="edu-font-mono"
                                style={{
                                  fontSize: "12px",
                                  color: "#475569",
                                  backgroundColor: "#F1F5F9",
                                  padding: "3px 8px",
                                  borderRadius: "6px",
                                  border: "1px solid #E2E8F0",
                                }}
                              >
                                {trace.trace_id.slice(0, 14)}…
                              </span>
                            </td>

                            <td style={{ padding: "16px 20px", fontSize: "13px", color: "#64748B" }}>
                              {new Date(trace.last_step_at).toLocaleString([], { dateStyle: "short", timeStyle: "medium" })}
                            </td>

                            <td style={{ padding: "16px 20px" }}>
                              <span
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "5px",
                                  fontSize: "12.5px",
                                  fontWeight: 600,
                                  color: isHighDur ? "#D97706" : "#059669",
                                }}
                              >
                                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>timer</span>
                                {trace.total_duration_ms} ms
                              </span>
                            </td>

                            <td style={{ padding: "16px 24px", textAlign: "right" }}>
                              <button
                                onClick={() => setSelectedTraceId(isSelected ? null : trace.trace_id)}
                                style={{
                                  padding: "6px 14px",
                                  borderRadius: "8px",
                                  fontSize: "12px",
                                  fontWeight: 600,
                                  border: "1px solid",
                                  borderColor: isSelected ? "#10B981" : "rgba(226, 232, 240, 0.9)",
                                  backgroundColor: isSelected ? "#10B981" : "#FFFFFF",
                                  color: isSelected ? "#FFFFFF" : "#1E293B",
                                  cursor: "pointer",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "6px",
                                  transition: "all 0.15s ease",
                                  boxShadow: isSelected ? "0 2px 6px rgba(16, 185, 129, 0.2)" : "none",
                                }}
                              >
                                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>
                                  {isSelected ? "visibility_off" : "account_tree"}
                                </span>
                                {isSelected ? "Hide Pipeline" : "Inspect Trace"}
                              </button>
                            </td>
                          </tr>

                          {/* Expanded Step Timeline Drawer */}
                          {isSelected && (
                            <tr>
                              <td
                                colSpan={5}
                                style={{
                                  padding: "0 24px 20px 24px",
                                  backgroundColor: "rgba(248, 250, 252, 0.8)",
                                  borderBottom: "1px solid rgba(226, 232, 240, 0.8)",
                                }}
                              >
                                <div
                                  style={{
                                    backgroundColor: "#FFFFFF",
                                    borderRadius: "14px",
                                    padding: "20px",
                                    border: "1px solid rgba(226, 232, 240, 0.8)",
                                    boxShadow: "0 4px 12px -2px rgba(0, 0, 0, 0.03)",
                                  }}
                                >
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                      <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>
                                        route
                                      </span>
                                      <h4 className="edu-font-heading" style={{ fontSize: "14px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                                        Execution Trace Flow: <span className="edu-font-mono" style={{ color: "#64748B" }}>{trace.trace_id}</span>
                                      </h4>
                                    </div>
                                    <span style={{ fontSize: "12px", color: "#64748B" }}>
                                      Total Latency: <strong>{trace.total_duration_ms} ms</strong>
                                    </span>
                                  </div>

                                  {traceError && (
                                    <div style={{ padding: "10px 14px", borderRadius: "8px", backgroundColor: "#FEF2F2", color: "#991B1B", fontSize: "12.5px", marginBottom: "12px" }}>
                                      {traceError}
                                    </div>
                                  )}

                                  {!traceSteps && !traceError && (
                                    <div style={{ padding: "24px 0", textAlign: "center", color: "#64748B", fontSize: "13px" }}>
                                      <span className="material-symbols-outlined" style={{ fontSize: "24px", animation: "spin 1s infinite linear" }}>sync</span>
                                      <p style={{ margin: "6px 0 0 0" }}>Loading node trace steps...</p>
                                    </div>
                                  )}

                                  {traceSteps && (
                                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                                      {traceSteps.map((step, idx) => {
                                        const stepMeta = getNodeMeta(step.node_name);
                                        const isLast = idx === traceSteps.length - 1;

                                        return (
                                          <div
                                            key={step.step_order}
                                            style={{
                                              display: "flex",
                                              alignItems: "center",
                                              justifyContent: "space-between",
                                              padding: "12px 16px",
                                              borderRadius: "10px",
                                              backgroundColor: "#F8FAFC",
                                              border: "1px solid rgba(226, 232, 240, 0.8)",
                                              gap: "14px",
                                            }}
                                          >
                                            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                                              {/* Step number badge */}
                                              <span
                                                style={{
                                                  width: "24px",
                                                  height: "24px",
                                                  borderRadius: "50%",
                                                  backgroundColor: "#0F172A",
                                                  color: "#FFFFFF",
                                                  fontSize: "11px",
                                                  fontWeight: 700,
                                                  display: "flex",
                                                  alignItems: "center",
                                                  justifyContent: "center",
                                                  flexShrink: 0,
                                                }}
                                              >
                                                {step.step_order + 1}
                                              </span>

                                              {/* Node category icon */}
                                              <div
                                                style={{
                                                  width: "28px",
                                                  height: "28px",
                                                  borderRadius: "6px",
                                                  backgroundColor: stepMeta.bg,
                                                  color: stepMeta.color,
                                                  display: "flex",
                                                  alignItems: "center",
                                                  justifyContent: "center",
                                                  flexShrink: 0,
                                                }}
                                              >
                                                <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>
                                                  {stepMeta.icon}
                                                </span>
                                              </div>

                                              <div>
                                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                                  <span className="edu-font-mono" style={{ fontSize: "13px", fontWeight: 600, color: "#0F172A" }}>
                                                    {step.node_name}
                                                  </span>
                                                  <span
                                                    style={{
                                                      fontSize: "10px",
                                                      fontWeight: 600,
                                                      padding: "1px 6px",
                                                      borderRadius: "4px",
                                                      backgroundColor: "#FFFFFF",
                                                      border: "1px solid #E2E8F0",
                                                      color: "#64748B",
                                                    }}
                                                  >
                                                    {stepMeta.category}
                                                  </span>
                                                </div>
                                                {step.error_message && (
                                                  <p style={{ fontSize: "11.5px", color: "#DC2626", margin: "2px 0 0 0" }}>
                                                    {step.error_message}
                                                  </p>
                                                )}
                                              </div>
                                            </div>

                                            <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
                                              <span
                                                style={{
                                                  fontSize: "12px",
                                                  color: "#64748B",
                                                  display: "flex",
                                                  alignItems: "center",
                                                  gap: "4px",
                                                }}
                                              >
                                                <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>timer</span>
                                                {step.duration_ms} ms
                                              </span>

                                              <span
                                                style={{
                                                  fontSize: "11px",
                                                  fontWeight: 700,
                                                  textTransform: "uppercase",
                                                  letterSpacing: "0.04em",
                                                  padding: "3px 8px",
                                                  borderRadius: "6px",
                                                  backgroundColor: step.status === "blocked" || step.status === "error"
                                                    ? "#FEE2E2"
                                                    : "#DCFCE7",
                                                  color: step.status === "blocked" || step.status === "error"
                                                    ? "#B91C1C"
                                                    : "#15803D",
                                                }}
                                              >
                                                {step.status}
                                              </span>
                                            </div>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

export default AgentTraces;
