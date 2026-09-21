import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar, KpiCard } from "../../components/ui";
import "../../components/ui/ui.css";

const SINCE_DAYS_OPTIONS = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 0, label: "All time" }, // 0 -> sent as no filter, see fetchSummary
];

function LlmUsage() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [sinceDays, setSinceDays] = useState(30);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setSummary(null);
    setError("");
    const params = sinceDays ? { since_days: sinceDays } : {};
    apiClient
      .get("/observability/llm-usage-summary", { params })
      .then((response) => setSummary(response.data))
      .catch((err) => {
        const detail = err.response?.data?.detail || "Failed to load LLM usage data.";
        setError(detail);
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

  const quota = summary?.gemini_quota;
  const quotaPercent = quota?.percent_used ?? 0;
  const quotaColor = quotaPercent >= 90 ? "#B23A2E" : quotaPercent >= 70 ? "#C97A2B" : "#26415E";

  const rpmPercent = quota
    ? Math.round((quota.requests_used_this_minute / quota.per_minute_limit) * 100)
    : 0;
  const rpmColor = rpmPercent >= 90 ? "#B23A2E" : rpmPercent >= 70 ? "#C97A2B" : "#26415E";

  const groqQuota = summary?.groq_quota;
  const groqRpdPercent = groqQuota?.percent_used ?? 0;
  const groqRpdColor = groqRpdPercent >= 90 ? "#B23A2E" : groqRpdPercent >= 70 ? "#C97A2B" : "#26415E";
  const groqRpmPercent = groqQuota
    ? Math.round((groqQuota.requests_used_this_minute / groqQuota.per_minute_limit) * 100)
    : 0;
  const groqRpmColor = groqRpmPercent >= 90 ? "#B23A2E" : groqRpmPercent >= 70 ? "#C97A2B" : "#26415E";
  const groqTpdPercent = groqQuota
    ? Math.round((groqQuota.tokens_used_today / groqQuota.tokens_daily_limit) * 100)
    : 0;
  const groqTpdColor = groqTpdPercent >= 90 ? "#B23A2E" : groqTpdPercent >= 70 ? "#C97A2B" : "#26415E";
  const groqTpmPercent = groqQuota
    ? Math.round((groqQuota.tokens_used_this_minute / groqQuota.tokens_per_minute_limit) * 100)
    : 0;
  const groqTpmColor = groqTpmPercent >= 90 ? "#B23A2E" : groqTpmPercent >= 70 ? "#C97A2B" : "#26415E";

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="llm-usage"
        logoText="EduIntel AI"
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
                LLM Cost &amp; Latency
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
                Loading usage data...
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
                  Estimated cost is based on published per-token pricing, not an actual bill — this project
                  runs on free-tier Gemini/Groq quotas. It shows what this feature would cost to run at scale.
                </p>
              </div>

              <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
                <KpiCard
                  title="Total LLM Calls"
                  value={summary.overall.call_count}
                  trend={SINCE_DAYS_OPTIONS.find((o) => o.value === sinceDays)?.label}
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#26415E"
                />
                <KpiCard
                  title="Estimated Cost"
                  value={`₹${summary.overall.total_estimated_cost_inr.toFixed(4)}`}
                  trend="Approx. at published rates"
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#C97A2B"
                />
                <KpiCard
                  title="Avg Latency"
                  value={summary.overall.avg_latency_ms != null ? `${Math.round(summary.overall.avg_latency_ms)} ms` : "—"}
                  trend="Per LLM call"
                  trendDirection={summary.overall.avg_latency_ms > 5000 ? "down" : "up"}
                  progressPercent={100}
                  progressColor="#26415E"
                />
                <KpiCard
                  title="Groq Fallback Rate"
                  value={`${fallbackRatePercent}%`}
                  trend={`${summary.overall.fallback_count} of ${summary.overall.call_count} calls`}
                  trendDirection={fallbackRatePercent > 0 ? "down" : "up"}
                  progressPercent={fallbackRatePercent}
                  progressColor="#92ADCF"
                />
                <KpiCard
                  title="Tokens Used"
                  value={totalTokens.toLocaleString()}
                  trend={`${summary.overall.total_input_tokens.toLocaleString()} in / ${summary.overall.total_output_tokens.toLocaleString()} out`}
                  trendDirection="up"
                  progressPercent={100}
                  progressColor="#26415E"
                />
              </div>

              <h3 className="edu-font-heading" style={{ fontSize: "14px", fontWeight: 600, color: "#5F6774", margin: "0 0 12px 0", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Gemini Free-Tier Quota (gemini-3.6-flash)
              </h3>
              <div className="edu-kpi-grid" style={{ marginBottom: "12px" }}>
                {quota && (
                  <KpiCard
                    title="Daily Quota (RPD)"
                    value={`${quota.requests_remaining.toLocaleString()} left`}
                    trend={`${quota.requests_used_today.toLocaleString()} / ${quota.daily_limit.toLocaleString()} used today`}
                    trendDirection={quotaPercent >= 70 ? "down" : "up"}
                    progressPercent={quotaPercent}
                    progressColor={quotaColor}
                  />
                )}
                {quota && (
                  <KpiCard
                    title="Per-Minute Quota (RPM)"
                    value={`${quota.per_minute_remaining.toLocaleString()} left`}
                    trend={`${quota.requests_used_this_minute.toLocaleString()} / ${quota.per_minute_limit.toLocaleString()} used this minute`}
                    trendDirection={rpmPercent >= 70 ? "down" : "up"}
                    progressPercent={rpmPercent}
                    progressColor={rpmColor}
                  />
                )}
              </div>

              {quota && quotaPercent >= 100 && (
                <div
                  className="edu-card"
                  style={{ padding: "12px 20px", marginBottom: "24px", borderLeft: "4px solid #B23A2E" }}
                >
                  <p style={{ fontSize: "13px", color: "#1B2330", margin: 0 }}>
                    Gemini's free-tier daily request quota (20/day) is exhausted for today — every call is now
                    falling back to Groq. This is expected behavior given the free tier's very low daily cap,
                    not an error.
                  </p>
                </div>
              )}
              {quota && quotaPercent >= 70 && quotaPercent < 100 && (
                <div
                  className="edu-card"
                  style={{ padding: "12px 20px", marginBottom: "24px", borderLeft: `4px solid ${quotaColor}` }}
                >
                  <p style={{ fontSize: "13px", color: "#1B2330", margin: 0 }}>
                    Gemini's free-tier daily request quota is more than 70% used for today.
                  </p>
                </div>
              )}

              <h3 className="edu-font-heading" style={{ fontSize: "14px", fontWeight: 600, color: "#5F6774", margin: "0 0 12px 0", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Groq Free-Tier Quota (openai/gpt-oss-120b fallback)
              </h3>
              <div className="edu-kpi-grid" style={{ marginBottom: "12px" }}>
                {groqQuota && (
                  <KpiCard
                    title="Daily Requests (RPD)"
                    value={`${groqQuota.requests_remaining.toLocaleString()} left`}
                    trend={`${groqQuota.requests_used_today.toLocaleString()} / ${groqQuota.daily_limit.toLocaleString()} used today`}
                    trendDirection={groqRpdPercent >= 70 ? "down" : "up"}
                    progressPercent={groqRpdPercent}
                    progressColor={groqRpdColor}
                  />
                )}
                {groqQuota && (
                  <KpiCard
                    title="Per-Minute Requests (RPM)"
                    value={`${groqQuota.per_minute_remaining.toLocaleString()} left`}
                    trend={`${groqQuota.requests_used_this_minute.toLocaleString()} / ${groqQuota.per_minute_limit.toLocaleString()} used this minute`}
                    trendDirection={groqRpmPercent >= 70 ? "down" : "up"}
                    progressPercent={groqRpmPercent}
                    progressColor={groqRpmColor}
                  />
                )}
                {groqQuota && (
                  <KpiCard
                    title="Daily Tokens (TPD)"
                    value={`${groqQuota.tokens_remaining_today.toLocaleString()} left`}
                    trend={`${groqQuota.tokens_used_today.toLocaleString()} / ${groqQuota.tokens_daily_limit.toLocaleString()} used today`}
                    trendDirection={groqTpdPercent >= 70 ? "down" : "up"}
                    progressPercent={groqTpdPercent}
                    progressColor={groqTpdColor}
                  />
                )}
                {groqQuota && (
                  <KpiCard
                    title="Per-Minute Tokens (TPM)"
                    value={`${groqQuota.tokens_per_minute_remaining.toLocaleString()} left`}
                    trend={`${groqQuota.tokens_used_this_minute.toLocaleString()} / ${groqQuota.tokens_per_minute_limit.toLocaleString()} used this minute`}
                    trendDirection={groqTpmPercent >= 70 ? "down" : "up"}
                    progressPercent={groqTpmPercent}
                    progressColor={groqTpmColor}
                  />
                )}
              </div>

              {groqQuota && groqTpmPercent >= 70 && (
                <div
                  className="edu-card"
                  style={{ padding: "12px 20px", marginBottom: "24px", borderLeft: `4px solid ${groqTpmColor}` }}
                >
                  <p style={{ fontSize: "13px", color: "#1B2330", margin: 0 }}>
                    {groqTpmPercent >= 100
                      ? "Groq's per-minute token quota (8K TPM) is exhausted — this is likely to be the first limit you hit in practice, before RPM (30/min)."
                      : "Groq's per-minute token quota is more than 70% used — this is likely to be the first Groq limit you hit in practice, before RPM."}
                  </p>
                </div>
              )}

              <div className="edu-card" style={{ padding: "0", overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid #E5E5E0" }}>
                  <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: 0 }}>
                    Breakdown by Endpoint
                  </h3>
                </div>

                {summary.by_endpoint.length === 0 ? (
                  <p style={{ padding: "20px", color: "#5F6774", fontSize: "14px" }}>
                    No LLM calls recorded in this window.
                  </p>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ backgroundColor: "#FAFAF7" }}>
                        {["Endpoint", "Calls", "Tokens (in/out)", "Avg Latency", "Est. Cost (₹)", "Fallback Rate"].map((h) => (
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
                      {summary.by_endpoint.map((row) => (
                        <tr key={row.endpoint} style={{ borderBottom: "1px solid #F0F0EC" }}>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330", fontFamily: "monospace" }}>
                            {row.endpoint}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>{row.call_count}</td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            {row.total_input_tokens.toLocaleString()} / {row.total_output_tokens.toLocaleString()}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            {row.avg_latency_ms != null ? `${Math.round(row.avg_latency_ms)} ms` : "—"}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: "#1B2330" }}>
                            ₹{row.total_estimated_cost_inr.toFixed(4)}
                          </td>
                          <td style={{ padding: "12px 20px", fontSize: "14px", color: row.fallback_count > 0 ? "#C97A2B" : "#5F6774" }}>
                            {row.call_count > 0 ? Math.round((row.fallback_count / row.call_count) * 100) : 0}%
                          </td>
                        </tr>
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

export default LlmUsage;