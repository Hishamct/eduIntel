import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  getFinOpsOverview,
  getFinOpsDaily,
  getFinOpsByCategory,
  getFinOpsByProvider,
  getFinOpsReservations,
  getFinOpsAdjustments,
} from "../../api/finops";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

export default function FinOpsDashboard() {
  const [overview, setOverview] = useState(null);
  const [dailySeries, setDailySeries] = useState([]);
  const [categories, setCategories] = useState([]);
  const [providers, setProviders] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [adjustments, setAdjustments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [timeRangeDays, setTimeRangeDays] = useState(30);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const today = new Date();
      const startDate = new Date();
      startDate.setDate(today.getDate() - timeRangeDays);
      const startStr = startDate.toISOString().split("T")[0];
      const endStr = today.toISOString().split("T")[0];

      const [ovData, dailyData, catData, provData, resData, adjData] = await Promise.all([
        getFinOpsOverview(),
        getFinOpsDaily({ start_date: startStr, end_date: endStr }),
        getFinOpsByCategory({ start_date: startStr, end_date: endStr }),
        getFinOpsByProvider({ start_date: startStr, end_date: endStr }),
        getFinOpsReservations({ limit: 15 }),
        getFinOpsAdjustments({ limit: 10 }),
      ]);

      setOverview(ovData);
      setDailySeries(dailyData || []);
      setCategories(catData || []);
      setProviders(provData || []);
      setReservations(resData?.items || []);
      setAdjustments(adjData?.items || []);
    } catch (err) {
      console.error("FinOps data loading error:", err);
      setError(
        err.response?.data?.detail || "Failed to load FinOps telemetry data. Please ensure AI quotas are provisioned."
      );
    } finally {
      setLoading(false);
    }
  }, [timeRangeDays]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const formatINR = (val) => {
    const num = parseFloat(val || 0);
    return `₹${num.toFixed(2)}`;
  };

  const getStatusBadgeStyle = (status) => {
    switch (status) {
      case "COMMITTED":
      case "SUCCEEDED":
        return { background: "#ECFDF5", color: "#059669", border: "1px solid #A7F3D0" };
      case "RESERVED":
      case "DISPATCHED":
        return { background: "#EFF6FF", color: "#2563EB", border: "1px solid #BFDBFE" };
      case "RELEASED":
        return { background: "#F1F5F9", color: "#64748B", border: "1px solid #CBD5E1" };
      case "UNKNOWN_USAGE":
      case "TIMEOUT_UNCERTAIN":
        return { background: "#FFFBEB", color: "#D97706", border: "1px solid #FDE68A" };
      default:
        return { background: "#FEF2F2", color: "#DC2626", border: "1px solid #FECACA" };
    }
  };

  return (
    <div className="edu-portal-layout">
      <Sidebar
        logoText="eduIntel"
        roleText="Administrator Portal"
        activeId="finops"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "finops") {
            navigate(`/admin/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          pageTitle="FinOps & AI Token Quotas"
          role="admin"
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-content-area" style={{ padding: "24px 32px", maxWidth: "1400px", margin: "0 auto" }}>
          {/* Header Controls */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                Financial Exposure & Quota Management
              </h2>
              <p style={{ fontSize: "14px", color: "#64748B", margin: "4px 0 0 0" }}>
                Real-time multi-attempt provider accounting, category budgets, and risk reserve enforcement.
              </p>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <select
                value={timeRangeDays}
                onChange={(e) => setTimeRangeDays(Number(e.target.value))}
                className="edu-input-select"
                style={{ padding: "8px 14px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px", fontWeight: 500 }}
              >
                <option value={7}>Last 7 Days</option>
                <option value={30}>Last 30 Days</option>
                <option value={90}>Last 90 Days</option>
              </select>

              <button
                onClick={loadData}
                className="edu-btn-secondary"
                disabled={loading}
                style={{ display: "flex", alignItems: "center", gap: "6px", padding: "8px 14px", fontSize: "13px" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>refresh</span>
                Refresh
              </button>
            </div>
          </div>

          {error && (
            <div style={{ background: "#FEF2F2", border: "1px solid #FCA5A5", borderRadius: "10px", padding: "16px", marginBottom: "24px", display: "flex", alignItems: "center", gap: "12px" }}>
              <span className="material-symbols-outlined" style={{ color: "#DC2626" }}>warning</span>
              <div style={{ flex: 1 }}>
                <p style={{ margin: 0, fontWeight: 600, color: "#991B1B", fontSize: "14px" }}>FinOps Configuration Notice</p>
                <p style={{ margin: "2px 0 0 0", color: "#B91C1C", fontSize: "13px" }}>{error}</p>
              </div>
            </div>
          )}

          {loading ? (
            <div style={{ textAlign: "center", padding: "80px 0" }}>
              <span className="material-symbols-outlined" style={{ fontSize: "40px", color: "#059669", animation: "spin 1s linear infinite" }}>sync</span>
              <p style={{ marginTop: "12px", color: "#64748B", fontSize: "14px" }}>Aggregating FinOps financial ledgers...</p>
            </div>
          ) : overview && overview.configured ? (
            <>
              {/* Financial KPI Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "24px" }}>
                <div className="edu-card" style={{ padding: "18px", borderLeft: "4px solid #059669" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "#64748B", letterSpacing: "0.05em" }}>Daily AI Ceiling</div>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>{formatINR(overview.financial?.daily_ceiling_inr)}</div>
                  <div style={{ fontSize: "12px", color: "#059669", fontWeight: 500, marginTop: "4px" }}>Tier: {overview.tier_name || overview.plan_id}</div>
                </div>

                <div className="edu-card" style={{ padding: "18px", borderLeft: "4px solid #2563EB" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "#64748B", letterSpacing: "0.05em" }}>Confirmed Spend Today</div>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>{formatINR(overview.financial?.confirmed_cost_inr)}</div>
                  <div style={{ fontSize: "12px", color: "#64748B", marginTop: "4px" }}>{overview.tokens_today?.total_committed_tokens.toLocaleString()} tokens confirmed</div>
                </div>

                <div className="edu-card" style={{ padding: "18px", borderLeft: "4px solid #D97706" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "#64748B", letterSpacing: "0.05em" }}>Reserved Exposure</div>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>{formatINR(overview.financial?.total_reserved_exposure_inr)}</div>
                  <div style={{ fontSize: "12px", color: "#D97706", marginTop: "4px" }}>Pending in-flight operations</div>
                </div>

                <div className="edu-card" style={{ padding: "18px", borderLeft: "4px solid #7C3AED" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "#64748B", letterSpacing: "0.05em" }}>Protected Risk Reserve</div>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>{formatINR(overview.financial?.risk_reserve_inr)}</div>
                  <div style={{ fontSize: "12px", color: "#7C3AED", marginTop: "4px" }}>{(parseFloat(overview.financial?.risk_reserve_percent || 0.1) * 100).toFixed(0)}% safety buffer</div>
                </div>

                <div className="edu-card" style={{ padding: "18px", borderLeft: "4px solid #0284C7" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase", color: "#64748B", letterSpacing: "0.05em" }}>Available Capacity</div>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>{formatINR(overview.financial?.available_admission_capacity_inr)}</div>
                  <div style={{ fontSize: "12px", color: "#0284C7", marginTop: "4px" }}>{overview.financial?.percent_capacity_utilized}% capacity utilized</div>
                </div>
              </div>

              {/* Token Quota Progress by Category */}
              <div className="edu-card" style={{ padding: "20px", marginBottom: "24px" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#0F172A" }}>
                  Daily Token Quota Budgets by Category (Decision #3)
                </h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "20px" }}>
                  {overview.categories && Object.entries(overview.categories).map(([catKey, cat]) => {
                    const label = catKey === "interactive_ai" ? "Interactive AI (Agent / Chat)" : catKey === "ingestion_embeddings" ? "Ingestion Embeddings (RAG / OCR)" : "Other Metered Workflows";
                    const barColor = cat.percent_used > 85 ? "#DC2626" : cat.percent_used > 60 ? "#D97706" : "#059669";
                    return (
                      <div key={catKey} style={{ background: "#F8FAFC", padding: "16px", borderRadius: "10px", border: "1px solid #E2E8F0" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                          <span style={{ fontWeight: 600, fontSize: "14px", color: "#1E293B" }}>{label}</span>
                          <span style={{ fontSize: "13px", fontWeight: 700, color: barColor }}>{cat.percent_used}%</span>
                        </div>
                        <div style={{ background: "#E2E8F0", height: "8px", borderRadius: "4px", overflow: "hidden", marginBottom: "8px" }}>
                          <div style={{ width: `${Math.min(100, cat.percent_used)}%`, height: "100%", background: barColor, transition: "width 0.3s ease" }} />
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#64748B" }}>
                          <span>Used: {cat.committed_tokens.toLocaleString()}</span>
                          <span>Budget: {cat.limit_tokens.toLocaleString()}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Daily Trend Time Series Chart */}
              <div className="edu-card" style={{ padding: "20px", marginBottom: "24px" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#0F172A" }}>
                  Daily Financial Spend Trend (INR)
                </h3>
                {dailySeries.length === 0 ? (
                  <p style={{ color: "#64748B", fontSize: "14px", textAlign: "center", padding: "30px 0" }}>No daily financial history recorded in selected date range.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <div style={{ display: "flex", alignItems: "flex-end", gap: "10px", height: "160px", paddingBottom: "20px", minWidth: `${dailySeries.length * 36}px` }}>
                      {dailySeries.map((d, idx) => {
                        const cost = parseFloat(d.committed_cost_inr || 0);
                        const maxCost = Math.max(...dailySeries.map((s) => parseFloat(s.committed_cost_inr || 0)), 1);
                        const barHeight = Math.max(4, Math.round((cost / maxCost) * 120));
                        return (
                          <div key={idx} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "6px" }} title={`${d.usage_date}: ₹${cost.toFixed(2)} (${d.committed_total_tokens.toLocaleString()} tokens)`}>
                            <span style={{ fontSize: "10px", color: "#64748B" }}>₹{cost.toFixed(0)}</span>
                            <div style={{ width: "16px", height: `${barHeight}px`, background: cost > 0 ? "linear-gradient(180deg, #10B981 0%, #059669 100%)" : "#E2E8F0", borderRadius: "3px" }} />
                            <span style={{ fontSize: "10px", color: "#94A3B8", transform: "rotate(-45deg)", whiteSpace: "nowrap", marginTop: "4px" }}>{d.usage_date.slice(5)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* Provider & Category Breakdown Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "24px", marginBottom: "24px" }}>
                {/* Provider Breakdown */}
                <div className="edu-card" style={{ padding: "20px" }}>
                  <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#0F172A" }}>
                    Provider & Model Distribution
                  </h3>
                  {providers.length === 0 ? (
                    <p style={{ color: "#64748B", fontSize: "13px" }}>No provider attempt records recorded yet.</p>
                  ) : (
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E2E8F0", textAlign: "left", color: "#64748B" }}>
                          <th style={{ padding: "8px 4px" }}>Provider/Model</th>
                          <th style={{ padding: "8px 4px" }}>Calls</th>
                          <th style={{ padding: "8px 4px" }}>Tokens</th>
                          <th style={{ padding: "8px 4px" }}>Cost (INR)</th>
                          <th style={{ padding: "8px 4px" }}>Latency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {providers.map((p, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid #F1F5F9" }}>
                            <td style={{ padding: "10px 4px", fontWeight: 600 }}>{p.provider} ({p.model})</td>
                            <td style={{ padding: "10px 4px" }}>{p.attempt_count}</td>
                            <td style={{ padding: "10px 4px" }}>{p.total_tokens.toLocaleString()}</td>
                            <td style={{ padding: "10px 4px", fontWeight: 600, color: "#059669" }}>₹{parseFloat(p.actual_cost_inr).toFixed(2)}</td>
                            <td style={{ padding: "10px 4px", color: "#64748B" }}>{p.avg_latency_ms} ms</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* Adjustments & Reconciliation Status */}
                <div className="edu-card" style={{ padding: "20px" }}>
                  <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#0F172A" }}>
                    Audit Adjustments & True-Ups
                  </h3>
                  {adjustments.length === 0 ? (
                    <p style={{ color: "#64748B", fontSize: "13px" }}>Zero variance adjustments recorded for this institution.</p>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      {adjustments.map((adj, idx) => (
                        <div key={idx} style={{ padding: "10px", background: "#F8FAFC", borderRadius: "8px", border: "1px solid #E2E8F0", fontSize: "12px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600 }}>
                            <span style={{ color: "#2563EB" }}>{adj.adjustment_type}</span>
                            <span style={{ color: parseFloat(adj.cost_inr_delta) >= 0 ? "#DC2626" : "#059669" }}>
                              {parseFloat(adj.cost_inr_delta) >= 0 ? "+" : ""}₹{parseFloat(adj.cost_inr_delta).toFixed(4)}
                            </span>
                          </div>
                          <p style={{ margin: "4px 0 0 0", color: "#475569" }}>{adj.adjustment_reason} — {adj.notes}</p>
                          <span style={{ color: "#94A3B8", fontSize: "11px" }}>By {adj.adjusted_by_actor} on {new Date(adj.created_at).toLocaleDateString()}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Outstanding & Recent Reservations Ledger */}
              <div className="edu-card" style={{ padding: "20px" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 700, margin: "0 0 16px 0", color: "#0F172A" }}>
                  Recent Token Reservations & Dispatches
                </h3>
                {reservations.length === 0 ? (
                  <p style={{ color: "#64748B", fontSize: "13px" }}>No reservations found.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #E2E8F0", textAlign: "left", color: "#64748B" }}>
                          <th style={{ padding: "10px" }}>Reservation ID</th>
                          <th style={{ padding: "10px" }}>Endpoint</th>
                          <th style={{ padding: "10px" }}>Category</th>
                          <th style={{ padding: "10px" }}>Status</th>
                          <th style={{ padding: "10px" }}>Tokens (Res / Act)</th>
                          <th style={{ padding: "10px" }}>Cost (INR)</th>
                          <th style={{ padding: "10px" }}>Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reservations.map((r) => (
                          <tr key={r.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                            <td style={{ padding: "10px", fontFamily: "monospace", fontSize: "12px" }}>{r.id.slice(0, 8)}...</td>
                            <td style={{ padding: "10px" }}>{r.endpoint}</td>
                            <td style={{ padding: "10px", color: "#64748B" }}>{r.usage_category}</td>
                            <td style={{ padding: "10px" }}>
                              <span style={{ padding: "3px 8px", borderRadius: "12px", fontSize: "11px", fontWeight: 600, ...getStatusBadgeStyle(r.status) }}>
                                {r.status}
                              </span>
                            </td>
                            <td style={{ padding: "10px" }}>{r.total_reserved_tokens} / {r.actual_total_tokens}</td>
                            <td style={{ padding: "10px", fontWeight: 600 }}>₹{parseFloat(r.actual_cost_inr || r.reserved_cost_inr).toFixed(2)}</td>
                            <td style={{ padding: "10px", color: "#94A3B8", fontSize: "12px" }}>{new Date(r.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div style={{ textAlign: "center", padding: "60px 20px", background: "#FFFFFF", borderRadius: "12px", border: "1px solid #E2E8F0" }}>
              <span className="material-symbols-outlined" style={{ fontSize: "48px", color: "#94A3B8" }}>account_balance_wallet</span>
              <h3 style={{ margin: "16px 0 8px 0", color: "#0F172A" }}>AI Quota Not Provisioned</h3>
              <p style={{ color: "#64748B", maxWidth: "500px", margin: "0 auto 20px auto", fontSize: "14px" }}>
                This institution does not currently have an active AI token quota or financial budget assigned. Please contact your platform administrator to activate an approved quota plan.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

