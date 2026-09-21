import { useState, useEffect, Fragment } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, KpiCard } from "../../components/ui";
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

function AgentTraces() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [sinceDays, setSinceDays] = useState(30);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  const [selectedTraceId, setSelectedTraceId] = useState(null);
  const [traceSteps, setTraceSteps] = useState(null);
  const [traceError, setTraceError] = useState("");

  const navigate = useNavigate();

  useEffect(() => {
    setSummary(null);
    setError("");
    setSelectedTraceId(null);
    apiClient
      .get("/observability/agent-traces/summary", { params: { since_days: sinceDays } })
      .then((response) => setSummary(response.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Failed to load agent trace data.";
        setError(detail);
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
      .catch((err) => {
        const detail = err.response?.data?.detail || "Failed to load trace detail.";
        setTraceError(detail);
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

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="agent-traces"
        logoText="EduIntel AI"
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
          user={{ name: "Dr. Aria Vance", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                OBSERVABILITY
              </span>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
                Agent Traces
              </h2>
            </div>

            <div style={{ display: "flex", gap: "8px" }}>
              {SINCE_DAYS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSinceDays(opt.value)}
                  className={sinceDays === opt.value ? "edu-btn-accent" : "edu-btn-secondary"}
                  style={{ padding: "8px 14px", fontSize: "13px" }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div
              className="edu-card"
              style={{ padding: "16px 20px", marginBottom: "24px", borderLeft: "4px solid #B23A2E" }}
            >
              <p style={{ fontSize: "14px", color: "#1B2330", margin: 0, fontWeight: 500 }}>{error}</p>
            </div>
          )}

          {!summary && !error && (
            <div style={{ textAlign: "center", padding: "60px 0" }}>
              <span className="material-symbols-outlined" style={{ fontSize: "36px", color: "#26415E", animation: "spin 1s infinite linear" }}>
                sync
              </span>
              <p style={{ color: "#5F6774", marginTop: "12px", fontFamily: "'IBM Plex Sans', sans-serif" }}>
                Loading agent trace data...
              </p>
            </div>
          )}

          {summary && (
            <>
              <div
                className="edu-card"
                style={{ padding: "16px 20px", marginBottom: "24px", backgroundColor: "#FFFFFF", borderLeft: "4px solid #26415E" }}
              >
                <p style={{ fontSize: "14px", color: "#1B2330", margin: 0, fontWeight: 500 }}>
                  Step-by-step execution path for every LangGraph agent run — which node ran, in what order,
                  and how long it took. Pick a run below to see its full trace.
                </p>
              </div>

              <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
                <KpiCard
                  title="Total Agent Runs"
                  value={totalRuns}
                  trend={SINCE_DAYS_OPTIONS.find((o) => o.value === sinceDays)?.label}
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#26415E"
                />
                <KpiCard
                  title="Admin Assistant Runs"
                  value={runCounts["admin-assistant"] || 0}
                  trend="chat_with_admin_assistant"
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#26415E"
                />
                <KpiCard
                  title="Portal Assistant Runs"
                  value={runCounts["portal-assistant"] || 0}
                  trend="chat_with_portal_assistant"
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#92ADCF"
                />
                <KpiCard
                  title="Nodes Executed"
                  value={totalNodeCalls}
                  trend={slowestNode ? `Slowest avg: ${slowestNode.node_name} (${Math.round(slowestNode.avg_duration_ms)} ms)` : "—"}
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#26415E"
                />
                <KpiCard
                  title="Node Errors"
                  value={totalErrors}
                  trend={totalErrors > 0 ? "Investigate below" : "None in this window"}
                  trendDirection={totalErrors > 0 ? "down" : "up"}
                  progressPercent={totalNodeCalls > 0 ? Math.round((totalErrors / totalNodeCalls) * 100) : 0}
                  progressColor={totalErrors > 0 ? "#B23A2E" : "#26415E"}
                />
              </div>

              <div className="edu-card" style={{ padding: "0", overflow: "hidden", marginBottom: "24px" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E5E0" }}>
                  <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: 0 }}>
                    Node Breakdown
                  </h3>
                </div>

                {nodeBreakdown.length === 0 ? (
                  <p style={{ padding: "20px", color: "#5F6774", fontSize: "14px" }}>
                    No agent runs recorded in this window.
                  </p>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ backgroundColor: "#FAFAF7" }}>
                        {["Agent", "Node", "Calls", "Avg Duration", "Max Duration", "Errors"].map((h) => (
                          <th
                            key={h}
                            style={{
                              textAlign: "left",
                              padding: "10px 20px",
                              fontSize: "11px",
                              fontWeight: 700,
                              letterSpacing: "0.05em",
                              textTransform: "uppercase",
                              color: "#5F6774",
                              borderBottom: "1px solid #E5E5E0",
                            }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {nodeBreakdown.map((row) => (
                        <tr key={`${row.agent_name}-${row.node_name}`} style={{ borderBottom: "1px solid #F0F0EC" }}>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            {AGENT_LABELS[row.agent_name] || row.agent_name}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330", fontFamily: "monospace" }}>
                            {row.node_name}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>{row.call_count}</td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            {Math.round(row.avg_duration_ms)} ms
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            {row.max_duration_ms} ms
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: row.error_count > 0 ? "#B23A2E" : "#5F6774" }}>
                            {row.error_count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="edu-card" style={{ padding: "0", overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E5E0" }}>
                  <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: 0 }}>
                    Recent Runs
                  </h3>
                </div>

                {(summary.recent_traces || []).length === 0 ? (
                  <p style={{ padding: "20px", color: "#5F6774", fontSize: "14px" }}>
                    No agent runs recorded in this window.
                  </p>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ backgroundColor: "#FAFAF7" }}>
                        {["Agent", "Trace ID", "Last Step At", "Total Duration", ""].map((h) => (
                          <th
                            key={h}
                            style={{
                              textAlign: "left",
                              padding: "10px 20px",
                              fontSize: "11px",
                              fontWeight: 700,
                              letterSpacing: "0.05em",
                              textTransform: "uppercase",
                              color: "#5F6774",
                              borderBottom: "1px solid #E5E5E0",
                            }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {summary.recent_traces.map((trace) => (
                        <Fragment key={trace.trace_id}>
                          <tr style={{ borderBottom: "1px solid #F0F0EC" }}>
                            <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                              {AGENT_LABELS[trace.agent_name] || trace.agent_name}
                            </td>
                            <td style={{ padding: "12px 20px", fontSize: "13px", color: "#5F6774", fontFamily: "monospace" }}>
                              {trace.trace_id.slice(0, 8)}…
                            </td>
                            <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                              {new Date(trace.last_step_at).toLocaleString()}
                            </td>
                            <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                              {trace.total_duration_ms} ms
                            </td>
                            <td style={{ padding: "12px 20px" }}>
                              <button
                                className="edu-btn-secondary"
                                style={{ padding: "6px 12px", fontSize: "12px" }}
                                onClick={() =>
                                  setSelectedTraceId(selectedTraceId === trace.trace_id ? null : trace.trace_id)
                                }
                              >
                                {selectedTraceId === trace.trace_id ? "Hide steps" : "View steps"}
                              </button>
                            </td>
                          </tr>
                          {selectedTraceId === trace.trace_id && (
                            <tr>
                              <td colSpan={5} style={{ padding: "0 20px 16px 20px", backgroundColor: "#FAFAF8" }}>
                                {traceError && (
                                  <p style={{ fontSize: "13px", color: "#B23A2E", margin: "12px 0" }}>{traceError}</p>
                                )}
                                {!traceSteps && !traceError && (
                                  <p style={{ fontSize: "13px", color: "#5F6774", margin: "12px 0" }}>
                                    Loading steps...
                                  </p>
                                )}
                                {traceSteps && (
                                  <div style={{ display: "flex", flexDirection: "column", gap: "6px", padding: "12px 0" }}>
                                    {traceSteps.map((step) => (
                                      <div
                                        key={step.step_order}
                                        style={{
                                          display: "flex",
                                          alignItems: "center",
                                          gap: "12px",
                                          padding: "8px 12px",
                                          backgroundColor: "#FFFFFF",
                                          borderRadius: "6px",
                                          border: "1px solid #E5E5E0",
                                        }}
                                      >
                                        <span
                                          style={{
                                            fontSize: "11px",
                                            fontWeight: 700,
                                            color: "#FFFFFF",
                                            backgroundColor: "#26415E",
                                            borderRadius: "999px",
                                            width: "20px",
                                            height: "20px",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                          }}
                                        >
                                          {step.step_order + 1}
                                        </span>
                                        <span style={{ fontSize: "13px", fontFamily: "monospace", color: "#1B2330", minWidth: "140px" }}>
                                          {step.node_name}
                                        </span>
                                        <span style={{ fontSize: "13px", color: "#5F6774" }}>{step.duration_ms} ms</span>
                                        <span
                                          style={{
                                            fontSize: "11px",
                                            fontWeight: 700,
                                            textTransform: "uppercase",
                                            color: step.status === "blocked" ? "#B23A2E" : "#26415E",
                                          }}
                                        >
                                          {step.status}
                                        </span>
                                        {step.error_message && (
                                          <span style={{ fontSize: "12px", color: "#B23A2E" }}>{step.error_message}</span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default AgentTraces;
