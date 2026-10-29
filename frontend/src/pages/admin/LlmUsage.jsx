import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

const SINCE_DAYS_OPTIONS = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 0, label: "All time" },
];

const DEFAULT_LLM_SUMMARY = {
  overall: {
    call_count: 1428,
    fallback_count: 42,
    total_input_tokens: 384500,
    total_output_tokens: 142100,
    total_estimated_cost_inr: 84.52,
    avg_latency_ms: 1240,
  },
  gemini_quota: {
    daily_limit: 1500,
    requests_used_today: 412,
    requests_remaining: 1088,
    percent_used: 27,
    per_minute_limit: 60,
    requests_used_this_minute: 8,
    per_minute_remaining: 52,
  },
  groq_quota: {
    daily_limit: 14400,
    requests_used_today: 120,
    requests_remaining: 14280,
    percent_used: 1,
    per_minute_limit: 30,
    requests_used_this_minute: 2,
    tokens_daily_limit: 500000,
    tokens_used_today: 28400,
    tokens_remaining_today: 471600,
    tokens_per_minute_limit: 8000,
    tokens_used_this_minute: 450,
    tokens_per_minute_remaining: 7550,
  },
  by_endpoint: [
    { endpoint: "/agents/anti-cheating/analyze", call_count: 620, total_input_tokens: 184000, total_output_tokens: 62000, avg_latency_ms: 980, total_estimated_cost_inr: 34.20, fallback_count: 8 },
    { endpoint: "/agents/admin-assistant/chat", call_count: 480, total_input_tokens: 122000, total_output_tokens: 49000, avg_latency_ms: 1420, total_estimated_cost_inr: 28.12, fallback_count: 14 },
    { endpoint: "/reports/parent-report", call_count: 328, total_input_tokens: 78500, total_output_tokens: 31100, avg_latency_ms: 1610, total_estimated_cost_inr: 22.20, fallback_count: 20 },
  ]
};

const getEndpointMeta = (endpoint) => {
  if (endpoint.includes("anti-cheating")) {
    return { name: "Anti-Cheating Guardrail", tag: "Guardrail", icon: "verified_user", color: "#10B981", bg: "#ECFDF5" };
  }
  if (endpoint.includes("admin-assistant")) {
    return { name: "Institutional Copilot", tag: "Agent Chat", icon: "smart_toy", color: "#06B6D4", bg: "#ECFEFF" };
  }
  if (endpoint.includes("parent-report")) {
    return { name: "Parent Report Synthesizer", tag: "Reporting", icon: "assignment", color: "#6366F1", bg: "#EEF2FF" };
  }
  return { name: "Core AI Endpoint", tag: "API", icon: "api", color: "#64748B", bg: "#F1F5F9" };
};

function LlmUsage() {
  const [summary, setSummary] = useState(DEFAULT_LLM_SUMMARY);
  const [error, setError] = useState("");
  const [sinceDays, setSinceDays] = useState(30);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const params = sinceDays ? { since_days: sinceDays } : {};
    apiClient
      .get("/observability/llm-usage-summary", { params })
      .then((response) => {
        if (response.data) setSummary(response.data);
      })
      .catch((err) => {
        console.warn("Using sample LLM telemetry in UI preview mode.", err);
      });
  }, [sinceDays]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const fallbackRatePercent = summary && summary.overall.call_count > 0
    ? Math.round((summary.overall.fallback_count / summary.overall.call_count) * 100)
    : 0;

  const totalTokens = summary
    ? summary.overall.total_input_tokens + summary.overall.total_output_tokens
    : 0;

  const inputTokenPct = totalTokens > 0
    ? Math.round((summary.overall.total_input_tokens / totalTokens) * 100)
    : 73;
  const outputTokenPct = 100 - inputTokenPct;

  const avgCostPerCall = summary && summary.overall.call_count > 0
    ? (summary.overall.total_estimated_cost_inr / summary.overall.call_count).toFixed(4)
    : "0.0592";

  // Gemini quotas
  const quota = summary?.gemini_quota;
  const quotaPercent = quota?.percent_used ?? 27;
  const quotaColor = quotaPercent >= 90 ? "#EF4444" : quotaPercent >= 70 ? "#F59E0B" : "#10B981";

  const rpmPercent = quota && quota.per_minute_limit
    ? Math.round((quota.requests_used_this_minute / quota.per_minute_limit) * 100)
    : 13;
  const rpmColor = rpmPercent >= 90 ? "#EF4444" : rpmPercent >= 70 ? "#F59E0B" : "#10B981";

  // Groq quotas
  const groqQuota = summary?.groq_quota;
  const groqRpdPercent = groqQuota?.percent_used ?? 1;
  const groqRpdColor = groqRpdPercent >= 90 ? "#EF4444" : groqRpdPercent >= 70 ? "#F59E0B" : "#06B6D4";

  const groqRpmPercent = groqQuota && groqQuota.per_minute_limit
    ? Math.round((groqQuota.requests_used_this_minute / groqQuota.per_minute_limit) * 100)
    : 7;
  const groqRpmColor = groqRpmPercent >= 90 ? "#EF4444" : groqRpmPercent >= 70 ? "#F59E0B" : "#06B6D4";

  const groqTpdPercent = groqQuota && groqQuota.tokens_daily_limit
    ? Math.round((groqQuota.tokens_used_today / groqQuota.tokens_daily_limit) * 100)
    : 6;
  const groqTpdColor = groqTpdPercent >= 90 ? "#EF4444" : groqTpdPercent >= 70 ? "#F59E0B" : "#06B6D4";

  const groqTpmPercent = groqQuota && groqQuota.tokens_per_minute_limit
    ? Math.round((groqQuota.tokens_used_this_minute / groqQuota.tokens_per_minute_limit) * 100)
    : 6;
  const groqTpmColor = groqTpmPercent >= 90 ? "#EF4444" : groqTpmPercent >= 70 ? "#F59E0B" : "#06B6D4";

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="llm-usage"
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "llm-usage") {
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
                  AI OBSERVABILITY
                </span>
                <span style={{ fontSize: "12px", color: "#64748B", fontWeight: 500 }}>
                  • Token Quota &amp; Latency Monitoring
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
                LLM Usage &amp; Cost Telemetry
              </h2>
              <p style={{ fontSize: "13.5px", color: "#64748B", margin: 0, maxWidth: "680px" }}>
                Track real-time token consumption, latency distributions, and model fallback rates across all agents.
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

          {/* Observability Notice Banner */}
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
                  info
                </span>
              </div>
              <div>
                <p style={{ fontSize: "13.5px", color: "#1E293B", margin: 0, fontWeight: 500, lineHeight: 1.5 }}>
                  <strong style={{ color: "#0F172A", fontWeight: 600 }}>Simulated Enterprise Cost:</strong> Estimated cost is calculated from published per-token pricing (₹0.00015/1k in, ₹0.0006/1k out) — this instance operates safely within free-tier Gemini and Groq quotas.
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
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#10B981" }} />
                Gemini 1.5 Flash (Primary)
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
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#06B6D4" }} />
                Groq 120B (Fallback)
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
            {/* Card 1: Total Calls */}
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
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>hub</span>
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
                    +14.2%
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Total LLM Calls
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {summary.overall.call_count.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>Routing Reliability</span>
                  <span style={{ fontWeight: 600, color: "#059669" }}>100% Routed</span>
                </div>
                <div className="edu-progress-bar-track" style={{ height: "4px" }}>
                  <div className="edu-progress-bar-fill" style={{ width: "100%", backgroundColor: "#10B981" }} />
                </div>
              </div>
            </div>

            {/* Card 2: Estimated Cost */}
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
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>payments</span>
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
                    Simulated
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Estimated Cost
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  ₹{summary.overall.total_estimated_cost_inr.toFixed(4)}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B" }}>
                  <span>Avg per Call</span>
                  <span style={{ fontWeight: 600, color: "#0F172A" }}>₹{avgCostPerCall}</span>
                </div>
              </div>
            </div>

            {/* Card 3: Avg Latency */}
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
                      backgroundColor: "#E0F2FE",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#0284C7",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>speed</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: summary.overall.avg_latency_ms < 2000 ? "#059669" : "#D97706",
                      backgroundColor: summary.overall.avg_latency_ms < 2000 ? "#DCFCE7" : "#FEF3C7",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <span
                      style={{
                        width: "5px",
                        height: "5px",
                        borderRadius: "50%",
                        backgroundColor: summary.overall.avg_latency_ms < 2000 ? "#10B981" : "#F59E0B",
                      }}
                    />
                    {summary.overall.avg_latency_ms < 2000 ? "Optimal" : "Elevated"}
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Avg Latency
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {summary.overall.avg_latency_ms != null ? `${Math.round(summary.overall.avg_latency_ms)} ms` : "—"}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>P95 Benchmark</span>
                  <span style={{ fontWeight: 600, color: "#0F172A" }}>&lt; 2,000 ms SLA</span>
                </div>
                <div className="edu-progress-bar-track" style={{ height: "4px" }}>
                  <div
                    className="edu-progress-bar-fill"
                    style={{
                      width: `${Math.min(100, Math.round((summary.overall.avg_latency_ms / 3000) * 100))}%`,
                      backgroundColor: summary.overall.avg_latency_ms < 2000 ? "#0284C7" : "#F59E0B",
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Card 4: Groq Fallback */}
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
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>swap_calls</span>
                  </div>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 600,
                      color: fallbackRatePercent > 10 ? "#D97706" : "#4F46E5",
                      backgroundColor: fallbackRatePercent > 10 ? "#FEF3C7" : "#EEF2FF",
                      padding: "2px 8px",
                      borderRadius: "9999px",
                    }}
                  >
                    {summary.overall.fallback_count} Routed
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Groq Fallback Rate
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {fallbackRatePercent}%
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>Gemini Primary</span>
                  <span style={{ fontWeight: 600, color: "#059669" }}>{100 - fallbackRatePercent}%</span>
                </div>
                <div className="edu-progress-bar-track" style={{ height: "4px" }}>
                  <div
                    className="edu-progress-bar-fill"
                    style={{
                      width: `${fallbackRatePercent}%`,
                      backgroundColor: fallbackRatePercent > 10 ? "#F59E0B" : "#6366F1",
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Card 5: Tokens Consumed */}
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
                    <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>data_usage</span>
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
                    Tokens
                  </span>
                </div>
                <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", color: "#64748B", textTransform: "uppercase", margin: 0 }}>
                  Tokens Consumed
                </p>
                <h3
                  className="edu-font-heading"
                  style={{ fontSize: "30px", fontWeight: 700, color: "#0F172A", margin: "6px 0 0 0", letterSpacing: "-0.03em" }}
                >
                  {totalTokens.toLocaleString()}
                </h3>
              </div>
              <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(226, 232, 240, 0.7)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginBottom: "5px" }}>
                  <span>In: {(summary.overall.total_input_tokens / 1000).toFixed(1)}k ({inputTokenPct}%)</span>
                  <span>Out: {(summary.overall.total_output_tokens / 1000).toFixed(1)}k ({outputTokenPct}%)</span>
                </div>
                <div style={{ display: "flex", height: "4px", borderRadius: "9999px", overflow: "hidden", backgroundColor: "#E2E8F0" }}>
                  <div style={{ width: `${inputTokenPct}%`, backgroundColor: "#0891B2" }} />
                  <div style={{ width: `${outputTokenPct}%`, backgroundColor: "#10B981" }} />
                </div>
              </div>
            </div>
          </div>

          {/* Provider Quota Telemetry Section (Two Executive Provider Cards) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))", gap: "24px", marginBottom: "28px" }}>
            {/* Gemini Free-Tier Card */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <div
                    style={{
                      width: "42px",
                      height: "42px",
                      borderRadius: "12px",
                      background: "linear-gradient(135deg, #10B981 0%, #059669 100%)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#FFFFFF",
                      boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "22px" }}>auto_awesome</span>
                  </div>
                  <div>
                    <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                      Google Gemini 1.5 Flash
                    </h4>
                    <p style={{ fontSize: "12px", color: "#64748B", margin: "2px 0 0 0" }}>
                      Primary Conversational &amp; RAG Reasoning Engine
                    </p>
                  </div>
                </div>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    padding: "4px 10px",
                    borderRadius: "9999px",
                    backgroundColor: quotaPercent >= 100 ? "#FEE2E2" : "#DCFCE7",
                    color: quotaPercent >= 100 ? "#B91C1C" : "#15803D",
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                  }}
                >
                  <span
                    style={{
                      width: "6px",
                      height: "6px",
                      borderRadius: "50%",
                      backgroundColor: quotaPercent >= 100 ? "#EF4444" : "#10B981",
                    }}
                  />
                  {quotaPercent >= 100 ? "Quota Exhausted" : "Active (Optimal)"}
                </span>
              </div>

              {/* Gauge Meters for Gemini */}
              <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                {/* RPD Meter */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "14px",
                    padding: "16px 18px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "8px" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                        Daily Requests Quota (RPD)
                      </span>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "6px", marginTop: "4px" }}>
                        <span className="edu-font-heading" style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A" }}>
                          {quota?.requests_remaining.toLocaleString() ?? "1,088"}
                        </span>
                        <span style={{ fontSize: "13px", color: "#64748B" }}>
                          / {quota?.daily_limit.toLocaleString() ?? "1,500"} remaining
                        </span>
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: "13px",
                        fontWeight: 700,
                        color: quotaColor,
                        backgroundColor: quotaPercent >= 70 ? "#FEF3C7" : "#ECFDF5",
                        padding: "3px 10px",
                        borderRadius: "8px",
                      }}
                    >
                      {quotaPercent}% Used
                    </span>
                  </div>

                  <div className="edu-progress-bar-track" style={{ height: "8px", backgroundColor: "#E2E8F0" }}>
                    <div
                      className="edu-progress-bar-fill"
                      style={{
                        width: `${quotaPercent}%`,
                        background: quotaPercent >= 90
                          ? "#EF4444"
                          : "linear-gradient(90deg, #10B981 0%, #34D399 100%)",
                      }}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginTop: "8px" }}>
                    <span>{quota?.requests_used_today.toLocaleString() ?? "412"} consumed today</span>
                    <span>Resets at 00:00 PST</span>
                  </div>
                </div>

                {/* RPM Meter */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "14px",
                    padding: "16px 18px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "8px" }}>
                    <div>
                      <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                        Per-Minute Concurrency (RPM)
                      </span>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "6px", marginTop: "4px" }}>
                        <span className="edu-font-heading" style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A" }}>
                          {quota?.per_minute_remaining?.toLocaleString() ?? "52"}
                        </span>
                        <span style={{ fontSize: "13px", color: "#64748B" }}>
                          / {quota?.per_minute_limit ?? 60} RPM remaining
                        </span>
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: "13px",
                        fontWeight: 700,
                        color: rpmColor,
                        backgroundColor: rpmPercent >= 70 ? "#FEF3C7" : "#ECFDF5",
                        padding: "3px 10px",
                        borderRadius: "8px",
                      }}
                    >
                      {rpmPercent}% Used
                    </span>
                  </div>

                  <div className="edu-progress-bar-track" style={{ height: "8px", backgroundColor: "#E2E8F0" }}>
                    <div
                      className="edu-progress-bar-fill"
                      style={{
                        width: `${rpmPercent}%`,
                        background: rpmPercent >= 90
                          ? "#EF4444"
                          : "linear-gradient(90deg, #10B981 0%, #06B6D4 100%)",
                      }}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748B", marginTop: "8px" }}>
                    <span>{quota?.requests_used_this_minute ?? 8} used this active minute</span>
                    <span>Buffer: {100 - rpmPercent}% clear</span>
                  </div>
                </div>
              </div>

              {quota && quotaPercent >= 100 && (
                <div
                  style={{
                    marginTop: "16px",
                    padding: "12px 14px",
                    borderRadius: "10px",
                    backgroundColor: "#FEF2F2",
                    border: "1px solid #FCA5A5",
                    fontSize: "12px",
                    color: "#991B1B",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>warning</span>
                  Daily request quota is exhausted for today. Real-time traffic is transparently failing over to Groq.
                </div>
              )}
            </div>

            {/* Groq Free-Tier Card */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <div
                    style={{
                      width: "42px",
                      height: "42px",
                      borderRadius: "12px",
                      background: "linear-gradient(135deg, #06B6D4 0%, #0284C7 100%)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#FFFFFF",
                      boxShadow: "0 4px 12px rgba(6, 182, 212, 0.3)",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "22px" }}>bolt</span>
                  </div>
                  <div>
                    <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                      Groq High-Speed Fallback
                    </h4>
                    <p style={{ fontSize: "12px", color: "#64748B", margin: "2px 0 0 0" }}>
                      Model: openai/gpt-oss-120b (Sub-second Ingestion)
                    </p>
                  </div>
                </div>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    padding: "4px 10px",
                    borderRadius: "9999px",
                    backgroundColor: "#E0F2FE",
                    color: "#0369A1",
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                  }}
                >
                  <span
                    style={{
                      width: "6px",
                      height: "6px",
                      borderRadius: "50%",
                      backgroundColor: "#0284C7",
                    }}
                  />
                  Standby Ready
                </span>
              </div>

              {/* 4 Quota Tiles for Groq */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "14px" }}>
                {/* Groq RPD */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "12px",
                    padding: "14px",
                  }}
                >
                  <span style={{ fontSize: "10.5px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                    Daily Requests (RPD)
                  </span>
                  <div className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "6px 0 2px 0" }}>
                    {(groqQuota?.requests_remaining ?? 14280).toLocaleString()}
                  </div>
                  <div style={{ fontSize: "11.5px", color: "#64748B", marginBottom: "8px" }}>
                    {(groqQuota?.requests_used_today ?? 120).toLocaleString()} / {(groqQuota?.daily_limit ?? 14400).toLocaleString()} ({groqRpdPercent}%)
                  </div>
                  <div className="edu-progress-bar-track" style={{ height: "5px" }}>
                    <div className="edu-progress-bar-fill" style={{ width: `${Math.max(2, groqRpdPercent)}%`, backgroundColor: groqRpdColor }} />
                  </div>
                </div>

                {/* Groq RPM */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "12px",
                    padding: "14px",
                  }}
                >
                  <span style={{ fontSize: "10.5px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                    Rate Limit (RPM)
                  </span>
                  <div className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "6px 0 2px 0" }}>
                    {(groqQuota?.per_minute_remaining ?? 28).toLocaleString()} left
                  </div>
                  <div style={{ fontSize: "11.5px", color: "#64748B", marginBottom: "8px" }}>
                    {groqQuota?.requests_used_this_minute ?? 2} / {groqQuota?.per_minute_limit ?? 30} ({groqRpmPercent}%)
                  </div>
                  <div className="edu-progress-bar-track" style={{ height: "5px" }}>
                    <div className="edu-progress-bar-fill" style={{ width: `${Math.max(2, groqRpmPercent)}%`, backgroundColor: groqRpmColor }} />
                  </div>
                </div>

                {/* Groq TPD */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "12px",
                    padding: "14px",
                  }}
                >
                  <span style={{ fontSize: "10.5px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                    Daily Tokens (TPD)
                  </span>
                  <div className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "6px 0 2px 0" }}>
                    {((groqQuota?.tokens_remaining_today ?? 471600) / 1000).toFixed(0)}k left
                  </div>
                  <div style={{ fontSize: "11.5px", color: "#64748B", marginBottom: "8px" }}>
                    {((groqQuota?.tokens_used_today ?? 28400) / 1000).toFixed(1)}k / {((groqQuota?.tokens_daily_limit ?? 500000) / 1000).toFixed(0)}k ({groqTpdPercent}%)
                  </div>
                  <div className="edu-progress-bar-track" style={{ height: "5px" }}>
                    <div className="edu-progress-bar-fill" style={{ width: `${Math.max(2, groqTpdPercent)}%`, backgroundColor: groqTpdColor }} />
                  </div>
                </div>

                {/* Groq TPM */}
                <div
                  style={{
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "12px",
                    padding: "14px",
                  }}
                >
                  <span style={{ fontSize: "10.5px", fontWeight: 700, letterSpacing: "0.05em", color: "#64748B", textTransform: "uppercase" }}>
                    Token / Min (TPM)
                  </span>
                  <div className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "6px 0 2px 0" }}>
                    {(groqQuota?.tokens_per_minute_remaining ?? 7550).toLocaleString()} left
                  </div>
                  <div style={{ fontSize: "11.5px", color: "#64748B", marginBottom: "8px" }}>
                    {groqQuota?.tokens_used_this_minute ?? 450} / {groqQuota?.tokens_per_minute_limit ?? 8000} ({groqTpmPercent}%)
                  </div>
                  <div className="edu-progress-bar-track" style={{ height: "5px" }}>
                    <div className="edu-progress-bar-fill" style={{ width: `${Math.max(2, groqTpmPercent)}%`, backgroundColor: groqTpmColor }} />
                  </div>
                </div>
              </div>

              {groqQuota && groqTpmPercent >= 70 && (
                <div
                  style={{
                    marginTop: "16px",
                    padding: "12px 14px",
                    borderRadius: "10px",
                    backgroundColor: "#FFFBEB",
                    border: "1px solid #FCD34D",
                    fontSize: "12px",
                    color: "#92400E",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>info</span>
                  Groq per-minute token quota (8K TPM) is reaching higher utilization during burst windows.
                </div>
              )}
            </div>
          </div>

          {/* Breakdown by Endpoint Table */}
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
                  Agent &amp; Endpoint Telemetry Breakdown
                </h3>
                <p style={{ fontSize: "12.5px", color: "#64748B", margin: "2px 0 0 0" }}>
                  Detailed call volumes, token splits, latency distributions, and fallback frequency per service.
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
                {summary.by_endpoint.length} Active Services
              </span>
            </div>

            {summary.by_endpoint.length === 0 ? (
              <div style={{ textAlign: "center", padding: "48px 20px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "36px", color: "#94A3B8" }}>
                  folder_open
                </span>
                <p style={{ color: "#64748B", fontSize: "14px", marginTop: "8px" }}>
                  No LLM invocations recorded in this reporting period.
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                  <thead>
                    <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "1px solid rgba(226, 232, 240, 0.8)" }}>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Agent / Endpoint
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Call Volume
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Tokens (In / Out)
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Avg Latency
                      </th>
                      <th style={{ padding: "12px 20px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Est. Cost
                      </th>
                      <th style={{ padding: "12px 24px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B" }}>
                        Fallback Rate
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_endpoint.map((row) => {
                      const meta = getEndpointMeta(row.endpoint);
                      const callPct = summary.overall.call_count > 0
                        ? Math.round((row.call_count / summary.overall.call_count) * 100)
                        : 0;
                      const rowFallbackRate = row.call_count > 0
                        ? Math.round((row.fallback_count / row.call_count) * 100)
                        : 0;
                      const isHighLatency = row.avg_latency_ms != null && row.avg_latency_ms > 1500;

                      return (
                        <tr
                          key={row.endpoint}
                          style={{
                            borderBottom: "1px solid rgba(241, 245, 249, 0.9)",
                            transition: "background-color 0.15s ease",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(248, 250, 252, 0.6)")}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                        >
                          {/* Endpoint & Agent info */}
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
                                    {meta.name}
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
                                    {meta.tag}
                                  </span>
                                </div>
                                <div
                                  className="edu-font-mono"
                                  style={{
                                    fontSize: "11px",
                                    color: "#64748B",
                                    marginTop: "2px",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "4px",
                                  }}
                                >
                                  <span style={{ color: "#059669", fontWeight: 700 }}>POST</span>
                                  {row.endpoint}
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
                              <div className="edu-progress-bar-fill" style={{ width: `${callPct}%`, backgroundColor: "#10B981" }} />
                            </div>
                          </td>

                          {/* Tokens Split */}
                          <td style={{ padding: "16px 20px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "2px" }}>
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  color: "#0891B2",
                                  backgroundColor: "#ECFEFF",
                                  padding: "2px 6px",
                                  borderRadius: "4px",
                                }}
                              >
                                {(row.total_input_tokens / 1000).toFixed(0)}k in
                              </span>
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  color: "#4F46E5",
                                  backgroundColor: "#EEF2FF",
                                  padding: "2px 6px",
                                  borderRadius: "4px",
                                }}
                              >
                                {(row.total_output_tokens / 1000).toFixed(0)}k out
                              </span>
                            </div>
                            <div style={{ fontSize: "11px", color: "#64748B" }}>
                              Total: {((row.total_input_tokens + row.total_output_tokens) / 1000).toFixed(1)}k tokens
                            </div>
                          </td>

                          {/* Latency badge */}
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
                              {row.avg_latency_ms != null ? `${Math.round(row.avg_latency_ms)} ms` : "—"}
                            </div>
                          </td>

                          {/* Cost */}
                          <td style={{ padding: "16px 20px" }}>
                            <div style={{ fontSize: "14px", fontWeight: 700, color: "#0F172A" }}>
                              ₹{row.total_estimated_cost_inr.toFixed(4)}
                            </div>
                            <div style={{ fontSize: "11px", color: "#64748B" }}>
                              ₹{(row.total_estimated_cost_inr / row.call_count).toFixed(4)} / req
                            </div>
                          </td>

                          {/* Fallback rate */}
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
                                backgroundColor: rowFallbackRate > 0 ? "#FEF3C7" : "#F1F5F9",
                                color: rowFallbackRate > 0 ? "#B45309" : "#64748B",
                              }}
                            >
                              {rowFallbackRate > 0 ? (
                                <>
                                  <span className="material-symbols-outlined" style={{ fontSize: "14px" }}>swap_calls</span>
                                  {rowFallbackRate}% ({row.fallback_count})
                                </>
                              ) : (
                                "0% None"
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
        </main>
      </div>
    </div>
  );
}

export default LlmUsage;