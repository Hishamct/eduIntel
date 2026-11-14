import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  getPlatformFinOpsOverview,
  getPlatformFinOpsInstitutions,
  getPlatformFinOpsPlans,
  provisionTenantPlan,
  suspendTenantQuota,
  resumeTenantQuota,
  getReconciliationBacklog,
  manualSettleReservation,
  triggerReconciliationSweep,
} from "../../api/finops";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

export default function PlatformFinOps() {
  const [overview, setOverview] = useState(null);
  const [institutions, setInstitutions] = useState([]);
  const [plans, setPlans] = useState([]);
  const [backlog, setBacklog] = useState({ total_backlog: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("provisioning"); // 'provisioning' | 'backlog' | 'plans'
  const [searchTerm, setSearchTerm] = useState("");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  // Sweeper execution state
  const [sweeping, setSweeping] = useState(false);
  const [sweepResult, setSweepResult] = useState(null);

  // Provisioning Modal State
  const [provisionModalOpen, setProvisionModalOpen] = useState(false);
  const [selectedInst, setSelectedInst] = useState(null);
  const [provisionForm, setProvisionForm] = useState({
    plan_id: "starter",
    change_reason: "",
    override_limits: false,
    daily_exposure_limit_inr: 100,
    monthly_exposure_limit_inr: 2500,
    daily_token_limit_interactive: 200000,
    daily_token_limit_ingestion: 500000,
    daily_token_limit_other: 100000,
    max_reservation_tokens: 30000,
    risk_reserve_percent: 0.10,
  });
  const [provisionSubmitting, setProvisionSubmitting] = useState(false);

  // Manual Settle Modal State
  const [settleModalOpen, setSettleModalOpen] = useState(false);
  const [selectedReservation, setSelectedReservation] = useState(null);
  const [settleForm, setSettleForm] = useState({
    settled_tokens: 0,
    settled_cost_inr: "0.0000",
    resolution_reason: "INVOICE_RECONCILED",
    resolution_notes: "",
  });
  const [settleSubmitting, setSettleSubmitting] = useState(false);

  // Status Action Modal State
  const [statusModalOpen, setStatusModalOpen] = useState(false);
  const [statusActionTarget, setStatusActionTarget] = useState(null); // { inst, action: 'suspend' | 'resume' }
  const [statusReason, setStatusReason] = useState("");
  const [statusSubmitting, setStatusSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ovData, instData, plansData, backlogData] = await Promise.all([
        getPlatformFinOpsOverview(),
        getPlatformFinOpsInstitutions({ limit: 100 }),
        getPlatformFinOpsPlans(),
        getReconciliationBacklog({ limit: 50 }),
      ]);

      setOverview(ovData);
      setInstitutions(instData?.items || []);
      setPlans(plansData?.items || []);
      setBacklog(backlogData || { total_backlog: 0, items: [] });
    } catch (err) {
      console.error("Failed to load Platform FinOps data:", err);
      setError(err.response?.data?.detail || "Failed to load platform FinOps data.");
    } finally {
      setLoading(false);
    }
  }, []);

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

  const handleTriggerSweep = async () => {
    setSweeping(true);
    setError("");
    try {
      const result = await triggerReconciliationSweep(50);
      setSweepResult(result);
      // Reload backlog and overview data
      const [ovData, backlogData] = await Promise.all([
        getPlatformFinOpsOverview(),
        getReconciliationBacklog({ limit: 50 }),
      ]);
      setOverview(ovData);
      setBacklog(backlogData || { total_backlog: 0, items: [] });
    } catch (err) {
      console.error("Sweeper execution failed:", err);
      setError(err.response?.data?.detail || "Reconciliation sweeper failed.");
    } finally {
      setSweeping(false);
    }
  };

  const openProvisionModal = (inst) => {
    setSelectedInst(inst);
    const existingPlanId = inst.plan_id || "starter";
    const matchingPlan = plans.find((p) => p.plan_id === existingPlanId);

    setProvisionForm({
      plan_id: existingPlanId,
      change_reason: "",
      override_limits: existingPlanId === "custom",
      daily_exposure_limit_inr: inst.daily_exposure_limit_inr || matchingPlan?.daily_exposure_limit_inr || 100,
      monthly_exposure_limit_inr: inst.monthly_exposure_limit_inr || matchingPlan?.monthly_exposure_limit_inr || 2500,
      daily_token_limit_interactive: inst.daily_token_limit_interactive || matchingPlan?.daily_token_limit_interactive || 200000,
      daily_token_limit_ingestion: inst.daily_token_limit_ingestion || matchingPlan?.daily_token_limit_ingestion || 500000,
      daily_token_limit_other: inst.daily_token_limit_other || matchingPlan?.daily_token_limit_other || 100000,
      max_reservation_tokens: inst.max_reservation_tokens || matchingPlan?.max_reservation_tokens || 30000,
      risk_reserve_percent: inst.risk_reserve_percent !== undefined ? inst.risk_reserve_percent : 0.10,
    });
    setProvisionModalOpen(true);
  };

  const handlePlanSelectChange = (e) => {
    const pId = e.target.value;
    const matching = plans.find((p) => p.plan_id === pId);
    if (matching && pId !== "custom") {
      setProvisionForm((prev) => ({
        ...prev,
        plan_id: pId,
        override_limits: false,
        daily_exposure_limit_inr: matching.daily_exposure_limit_inr,
        monthly_exposure_limit_inr: matching.monthly_exposure_limit_inr,
        daily_token_limit_interactive: matching.daily_token_limit_interactive,
        daily_token_limit_ingestion: matching.daily_token_limit_ingestion,
        daily_token_limit_other: matching.daily_token_limit_other,
        max_reservation_tokens: matching.max_reservation_tokens,
        risk_reserve_percent: matching.risk_reserve_percent || 0.10,
      }));
    } else {
      setProvisionForm((prev) => ({
        ...prev,
        plan_id: pId,
        override_limits: true,
      }));
    }
  };

  const handleProvisionSubmit = async (e) => {
    e.preventDefault();
    if (!provisionForm.change_reason.trim()) {
      alert("A change reason is strictly required for the audit trail.");
      return;
    }
    setProvisionSubmitting(true);
    try {
      const payload = {
        plan_id: provisionForm.plan_id,
        change_reason: provisionForm.change_reason,
        daily_exposure_limit_inr: provisionForm.override_limits
          ? parseFloat(provisionForm.daily_exposure_limit_inr)
          : undefined,
        monthly_exposure_limit_inr: provisionForm.override_limits
          ? parseFloat(provisionForm.monthly_exposure_limit_inr)
          : undefined,
        daily_token_limit_interactive: provisionForm.override_limits
          ? parseInt(provisionForm.daily_token_limit_interactive, 10)
          : undefined,
        daily_token_limit_ingestion: provisionForm.override_limits
          ? parseInt(provisionForm.daily_token_limit_ingestion, 10)
          : undefined,
        daily_token_limit_other: provisionForm.override_limits
          ? parseInt(provisionForm.daily_token_limit_other, 10)
          : undefined,
        max_reservation_tokens: provisionForm.override_limits
          ? parseInt(provisionForm.max_reservation_tokens, 10)
          : undefined,
        risk_reserve_percent: provisionForm.override_limits
          ? parseFloat(provisionForm.risk_reserve_percent)
          : undefined,
      };

      await provisionTenantPlan(selectedInst.institution_id, payload);
      setProvisionModalOpen(false);
      await loadData();
    } catch (err) {
      console.error("Provisioning failed:", err);
      alert(err.response?.data?.detail || "Failed to provision plan.");
    } finally {
      setProvisionSubmitting(false);
    }
  };

  const openSettleModal = (res) => {
    setSelectedReservation(res);
    setSettleForm({
      settled_tokens: res.reserved_tokens || 0,
      settled_cost_inr: res.held_cost_inr || "0.0000",
      resolution_reason: "INVOICE_RECONCILED",
      resolution_notes: "",
    });
    setSettleModalOpen(true);
  };

  const handleSettleSubmit = async (e) => {
    e.preventDefault();
    setSettleSubmitting(true);
    try {
      const payload = {
        reservation_id: selectedReservation.reservation_id,
        settled_tokens: parseInt(settleForm.settled_tokens, 10),
        settled_cost_inr: parseFloat(settleForm.settled_cost_inr),
        resolution_reason: settleForm.resolution_reason,
        resolution_notes: settleForm.resolution_notes,
      };
      await manualSettleReservation(payload);
      setSettleModalOpen(false);
      await loadData();
    } catch (err) {
      console.error("Manual settlement failed:", err);
      alert(err.response?.data?.detail || "Manual settlement failed.");
    } finally {
      setSettleSubmitting(false);
    }
  };

  const openStatusModal = (inst, action) => {
    setStatusActionTarget({ inst, action });
    setStatusReason("");
    setStatusModalOpen(true);
  };

  const handleStatusSubmit = async (e) => {
    e.preventDefault();
    if (!statusReason.trim()) {
      alert("A reason is required to update tenant quota status.");
      return;
    }
    setStatusSubmitting(true);
    try {
      const { inst, action } = statusActionTarget;
      if (action === "suspend") {
        await suspendTenantQuota(inst.institution_id, statusReason);
      } else {
        await resumeTenantQuota(inst.institution_id, statusReason);
      }
      setStatusModalOpen(false);
      await loadData();
    } catch (err) {
      console.error("Status update failed:", err);
      alert(err.response?.data?.detail || "Failed to update quota status.");
    } finally {
      setStatusSubmitting(false);
    }
  };

  const filteredInstitutions = institutions.filter((inst) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      inst.institution_name?.toLowerCase().includes(term) ||
      inst.institution_code?.toLowerCase().includes(term) ||
      inst.institution_id?.toLowerCase().includes(term) ||
      inst.plan_id?.toLowerCase().includes(term)
    );
  });

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="platform_admin"
        activeId="finops"
        logoText="eduIntel"
        roleText="Platform Administration"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId === "dashboard") navigate("/platform-admin/dashboard");
          if (itemId === "institutions") navigate("/platform-admin/institutions");
          if (itemId === "finops") navigate("/platform-admin/finops");
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Platform Admin", role: "Global Root Administrator" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content" style={{ padding: "24px" }}>
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
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <h1 className="edu-font-heading" style={{ fontSize: "26px", fontWeight: 700, margin: 0, color: "#0F172A" }}>
                  AI FinOps & Platform Quotas
                </h1>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    padding: "4px 8px",
                    borderRadius: "6px",
                    background: "#EEF2FF",
                    color: "#4F46E5",
                    textTransform: "uppercase",
                  }}
                >
                  Global Governance
                </span>
              </div>
              <p style={{ margin: "4px 0 0 0", color: "#64748B", fontSize: "14px" }}>
                Multi-tenant AI quota provisioning, financial exposure monitoring, automated reconciliation & audit recovery.
              </p>
            </div>

            <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
              <button
                onClick={handleTriggerSweep}
                disabled={sweeping}
                className="edu-button-secondary"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "8px 16px",
                  background: sweeping ? "#E2E8F0" : "#F8FAFC",
                  border: "1px solid #CBD5E1",
                  borderRadius: "8px",
                  cursor: sweeping ? "not-allowed" : "pointer",
                  fontWeight: 600,
                  fontSize: "13px",
                  color: "#0F172A",
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px", color: sweeping ? "#94A3B8" : "#4F46E5" }}>
                  {sweeping ? "sync" : "cleaning_services"}
                </span>
                {sweeping ? "Sweeping Backlog..." : "Run Sweeper Now"}
              </button>

              <button
                onClick={loadData}
                disabled={loading}
                className="edu-button-secondary"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "8px 14px",
                  background: "#F8FAFC",
                  border: "1px solid #CBD5E1",
                  borderRadius: "8px",
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: "13px",
                  color: "#0F172A",
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                  refresh
                </span>
                Refresh
              </button>
            </div>
          </div>

          {/* Sweeper Result Toast / Alert */}
          {sweepResult && (
            <div
              style={{
                marginBottom: "20px",
                padding: "12px 16px",
                borderRadius: "8px",
                background: "#ECFDF5",
                border: "1px solid #A7F3D0",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "20px" }}>
                  check_circle
                </span>
                <span style={{ fontSize: "13px", color: "#065F46" }}>
                  <strong>Sweeper Completed:</strong> Released {sweepResult.expired_reservations_released} expired reservations, flagged {sweepResult.stale_dispatched_marked_unknown} stale dispatched attempts in {sweepResult.duration_ms}ms.
                </span>
              </div>
              <button
                onClick={() => setSweepResult(null)}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#059669", fontSize: "18px" }}
              >
                ×
              </button>
            </div>
          )}

          {error && (
            <div
              style={{
                marginBottom: "20px",
                padding: "12px 16px",
                borderRadius: "8px",
                background: "#FEF2F2",
                border: "1px solid #FCA5A5",
                color: "#991B1B",
                fontSize: "13px",
              }}
            >
              {error}
            </div>
          )}

          {/* Global KPI Summary Cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "16px",
              marginBottom: "24px",
            }}
          >
            <div className="edu-card" style={{ padding: "18px", borderRadius: "12px", background: "#FFFFFF", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                    Platform Spend (Today)
                  </span>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>
                    {formatINR(overview?.total_actual_cost_today_inr)}
                  </div>
                  <div style={{ fontSize: "12px", color: "#64748B", marginTop: "4px" }}>
                    Active reserved: {formatINR(overview?.total_reserved_exposure_inr)}
                  </div>
                </div>
                <div style={{ padding: "10px", borderRadius: "10px", background: "#EFF6FF", color: "#2563EB" }}>
                  <span className="material-symbols-outlined">payments</span>
                </div>
              </div>
            </div>

            <div className="edu-card" style={{ padding: "18px", borderRadius: "12px", background: "#FFFFFF", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                    Platform Spend (MTD)
                  </span>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>
                    {formatINR(overview?.total_actual_cost_month_inr)}
                  </div>
                  <div style={{ fontSize: "12px", color: "#64748B", marginTop: "4px" }}>
                    Across all institutions
                  </div>
                </div>
                <div style={{ padding: "10px", borderRadius: "10px", background: "#F5F3FF", color: "#7C3AED" }}>
                  <span className="material-symbols-outlined">calendar_month</span>
                </div>
              </div>
            </div>

            <div className="edu-card" style={{ padding: "18px", borderRadius: "12px", background: "#FFFFFF", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                    Institutions Provisioned
                  </span>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginTop: "6px" }}>
                    {overview?.active_institutions || 0} / {overview?.total_institutions || 0}
                  </div>
                  <div style={{ fontSize: "12px", color: "#64748B", marginTop: "4px" }}>
                    Active quota configurations
                  </div>
                </div>
                <div style={{ padding: "10px", borderRadius: "10px", background: "#ECFDF5", color: "#059669" }}>
                  <span className="material-symbols-outlined">domain</span>
                </div>
              </div>
            </div>

            <div className="edu-card" style={{ padding: "18px", borderRadius: "12px", background: "#FFFFFF", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B", textTransform: "uppercase" }}>
                    Reconciliation Backlog
                  </span>
                  <div
                    style={{
                      fontSize: "24px",
                      fontWeight: 700,
                      color: (overview?.reconciliation_backlog_count || 0) > 0 ? "#DC2626" : "#059669",
                      marginTop: "6px",
                    }}
                  >
                    {overview?.reconciliation_backlog_count || 0}
                  </div>
                  <div style={{ fontSize: "12px", color: "#64748B", marginTop: "4px" }}>
                    UNKNOWN_USAGE items
                  </div>
                </div>
                <div
                  style={{
                    padding: "10px",
                    borderRadius: "10px",
                    background: (overview?.reconciliation_backlog_count || 0) > 0 ? "#FEF2F2" : "#F0FDF4",
                    color: (overview?.reconciliation_backlog_count || 0) > 0 ? "#DC2626" : "#16A34A",
                  }}
                >
                  <span className="material-symbols-outlined">rule</span>
                </div>
              </div>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div style={{ borderBottom: "1px solid #E2E8F0", marginBottom: "20px", display: "flex", gap: "24px" }}>
            <button
              onClick={() => setActiveTab("provisioning")}
              style={{
                background: "none",
                border: "none",
                padding: "12px 4px",
                borderBottom: activeTab === "provisioning" ? "2px solid #4F46E5" : "2px solid transparent",
                fontWeight: activeTab === "provisioning" ? 700 : 500,
                color: activeTab === "provisioning" ? "#4F46E5" : "#64748B",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Institution Quota Provisioning
            </button>

            <button
              onClick={() => setActiveTab("backlog")}
              style={{
                background: "none",
                border: "none",
                padding: "12px 4px",
                borderBottom: activeTab === "backlog" ? "2px solid #4F46E5" : "2px solid transparent",
                fontWeight: activeTab === "backlog" ? 700 : 500,
                color: activeTab === "backlog" ? "#4F46E5" : "#64748B",
                cursor: "pointer",
                fontSize: "14px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
              }}
            >
              Reconciliation & Recovery Backlog
              {(backlog.total_backlog || 0) > 0 && (
                <span
                  style={{
                    background: "#DC2626",
                    color: "#FFFFFF",
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "2px 6px",
                    borderRadius: "10px",
                  }}
                >
                  {backlog.total_backlog}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab("plans")}
              style={{
                background: "none",
                border: "none",
                padding: "12px 4px",
                borderBottom: activeTab === "plans" ? "2px solid #4F46E5" : "2px solid transparent",
                fontWeight: activeTab === "plans" ? 700 : 500,
                color: activeTab === "plans" ? "#4F46E5" : "#64748B",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Subscription Plan Templates
            </button>
          </div>

          {/* TAB 1: Quota Provisioning */}
          {activeTab === "provisioning" && (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "16px",
                  flexWrap: "wrap",
                  gap: "12px",
                }}
              >
                <div style={{ position: "relative", minWidth: "280px" }}>
                  <input
                    type="text"
                    placeholder="Search by institution name, code, plan..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px 12px 8px 36px",
                      borderRadius: "8px",
                      border: "1px solid #CBD5E1",
                      fontSize: "13px",
                    }}
                  />
                  <span
                    className="material-symbols-outlined"
                    style={{ position: "absolute", left: "10px", top: "8px", fontSize: "18px", color: "#94A3B8" }}
                  >
                    search
                  </span>
                </div>
                <div style={{ fontSize: "13px", color: "#64748B" }}>
                  Showing {filteredInstitutions.length} of {institutions.length} institutions
                </div>
              </div>

              <div
                className="edu-card"
                style={{
                  borderRadius: "12px",
                  background: "#FFFFFF",
                  border: "1px solid #E2E8F0",
                  overflowX: "auto",
                }}
              >
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                  <thead>
                    <tr style={{ background: "#F8FAFC", borderBottom: "1px solid #E2E8F0", textAlign: "left", color: "#64748B" }}>
                      <th style={{ padding: "12px 16px" }}>Institution</th>
                      <th style={{ padding: "12px 16px" }}>Current Plan</th>
                      <th style={{ padding: "12px 16px" }}>Status</th>
                      <th style={{ padding: "12px 16px" }}>Daily Limit</th>
                      <th style={{ padding: "12px 16px" }}>Risk Reserve</th>
                      <th style={{ padding: "12px 16px" }}>Today's Spend</th>
                      <th style={{ padding: "12px 16px" }}>Monthly Spend</th>
                      <th style={{ padding: "12px 16px", textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredInstitutions.length === 0 ? (
                      <tr>
                        <td colSpan="8" style={{ padding: "32px", textAlign: "center", color: "#94A3B8" }}>
                          No institutions match your search criteria.
                        </td>
                      </tr>
                    ) : (
                      filteredInstitutions.map((inst) => (
                        <tr key={inst.institution_id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                          <td style={{ padding: "12px 16px" }}>
                            <div style={{ fontWeight: 600, color: "#0F172A" }}>{inst.institution_name}</div>
                            <div style={{ fontSize: "11px", color: "#64748B" }}>Code: {inst.institution_code || inst.institution_id.slice(0, 8)}</div>
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <span
                              style={{
                                padding: "4px 8px",
                                borderRadius: "6px",
                                fontWeight: 600,
                                fontSize: "11px",
                                textTransform: "uppercase",
                                background: inst.plan_id ? "#EEF2FF" : "#F1F5F9",
                                color: inst.plan_id ? "#4F46E5" : "#64748B",
                              }}
                            >
                              {inst.plan_id || "Unprovisioned"}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <span
                              style={{
                                padding: "3px 8px",
                                borderRadius: "12px",
                                fontSize: "11px",
                                fontWeight: 600,
                                background: inst.status === "ACTIVE" ? "#DCFCE7" : "#FEE2E2",
                                color: inst.status === "ACTIVE" ? "#16A34A" : "#DC2626",
                              }}
                            >
                              {inst.status || "UNKNOWN"}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px", fontWeight: 600, color: "#0F172A" }}>
                            {formatINR(inst.daily_exposure_limit_inr)}
                          </td>
                          <td style={{ padding: "12px 16px", color: "#64748B" }}>
                            {inst.risk_reserve_percent ? `${(parseFloat(inst.risk_reserve_percent) * 100).toFixed(0)}%` : "10%"}
                          </td>
                          <td style={{ padding: "12px 16px", color: "#0F172A" }}>
                            {formatINR(inst.actual_cost_today_inr)}
                          </td>
                          <td style={{ padding: "12px 16px", color: "#64748B" }}>
                            {formatINR(inst.actual_cost_month_inr)}
                          </td>
                          <td style={{ padding: "12px 16px", textAlign: "right" }}>
                            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                              <button
                                onClick={() => openProvisionModal(inst)}
                                style={{
                                  background: "#EEF2FF",
                                  color: "#4F46E5",
                                  border: "1px solid #C7D2FE",
                                  borderRadius: "6px",
                                  padding: "5px 10px",
                                  fontSize: "12px",
                                  fontWeight: 600,
                                  cursor: "pointer",
                                }}
                              >
                                Configure Plan
                              </button>
                              {inst.status === "ACTIVE" ? (
                                <button
                                  onClick={() => openStatusModal(inst, "suspend")}
                                  style={{
                                    background: "#FEF2F2",
                                    color: "#DC2626",
                                    border: "1px solid #FECACA",
                                    borderRadius: "6px",
                                    padding: "5px 10px",
                                    fontSize: "12px",
                                    fontWeight: 600,
                                    cursor: "pointer",
                                  }}
                                >
                                  Suspend
                                </button>
                              ) : (
                                <button
                                  onClick={() => openStatusModal(inst, "resume")}
                                  style={{
                                    background: "#F0FDF4",
                                    color: "#16A34A",
                                    border: "1px solid #BBF7D0",
                                    borderRadius: "6px",
                                    padding: "5px 10px",
                                    fontSize: "12px",
                                    fontWeight: 600,
                                    cursor: "pointer",
                                  }}
                                >
                                  Resume
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 2: Reconciliation & Recovery Backlog */}
          {activeTab === "backlog" && (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "16px",
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                    UNKNOWN_USAGE Reservations Requiring Manual Settlement
                  </h3>
                  <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "#64748B" }}>
                    When provider calls fail to return token usage or process crashes occur mid-flight, conservative financial holds are retained until manual or invoice audit.
                  </p>
                </div>
              </div>

              <div
                className="edu-card"
                style={{
                  borderRadius: "12px",
                  background: "#FFFFFF",
                  border: "1px solid #E2E8F0",
                  overflowX: "auto",
                }}
              >
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                  <thead>
                    <tr style={{ background: "#F8FAFC", borderBottom: "1px solid #E2E8F0", textAlign: "left", color: "#64748B" }}>
                      <th style={{ padding: "12px 16px" }}>Reservation ID</th>
                      <th style={{ padding: "12px 16px" }}>Institution</th>
                      <th style={{ padding: "12px 16px" }}>Operation & Category</th>
                      <th style={{ padding: "12px 16px" }}>Created At</th>
                      <th style={{ padding: "12px 16px" }}>Held Cost</th>
                      <th style={{ padding: "12px 16px" }}>Fallback / Provider</th>
                      <th style={{ padding: "12px 16px" }}>Review Status</th>
                      <th style={{ padding: "12px 16px", textAlign: "right" }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!backlog.items || backlog.items.length === 0 ? (
                      <tr>
                        <td colSpan="8" style={{ padding: "36px", textAlign: "center", color: "#16A34A" }}>
                          <span className="material-symbols-outlined" style={{ fontSize: "28px", verticalAlign: "middle", marginRight: "8px" }}>
                            verified
                          </span>
                          Clean ledger! Zero reservations requiring manual review.
                        </td>
                      </tr>
                    ) : (
                      backlog.items.map((item) => (
                        <tr key={item.reservation_id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                          <td style={{ padding: "12px 16px", fontFamily: "monospace", fontSize: "12px", color: "#0F172A" }}>
                            {item.reservation_id.slice(0, 12)}...
                          </td>
                          <td style={{ padding: "12px 16px", color: "#334155" }}>
                            {item.institution_id.slice(0, 8)}...
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <div style={{ fontWeight: 600, color: "#0F172A" }}>{item.operation_type}</div>
                            <div style={{ fontSize: "11px", color: "#64748B" }}>{item.quota_category}</div>
                          </td>
                          <td style={{ padding: "12px 16px", color: "#64748B", fontSize: "12px" }}>
                            {new Date(item.created_at).toLocaleString()}
                          </td>
                          <td style={{ padding: "12px 16px", fontWeight: 700, color: "#DC2626" }}>
                            {formatINR(item.held_cost_inr)}
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: "12px", color: "#475569" }}>
                            {item.provider_fallback_occurred ? "Fallback Used" : "Primary"} ({item.dispatched_provider || "N/A"})
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <span
                              style={{
                                padding: "3px 8px",
                                borderRadius: "10px",
                                fontSize: "11px",
                                fontWeight: 600,
                                background: "#FEF2F2",
                                color: "#DC2626",
                              }}
                            >
                              {item.review_status || "NEEDS_MANUAL_REVIEW"}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px", textAlign: "right" }}>
                            <button
                              onClick={() => openSettleModal(item)}
                              style={{
                                background: "#0F172A",
                                color: "#FFFFFF",
                                border: "none",
                                borderRadius: "6px",
                                padding: "6px 12px",
                                fontSize: "12px",
                                fontWeight: 600,
                                cursor: "pointer",
                              }}
                            >
                              Settle Reservation
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: Plan Templates & Catalog */}
          {activeTab === "plans" && (
            <div>
              <div style={{ marginBottom: "16px" }}>
                <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#0F172A" }}>
                  Standard Subscription AI Quota Plans
                </h3>
                <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "#64748B" }}>
                  Pre-configured tiers with protected 10% risk reserves and explicit category token allocations.
                </p>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                  gap: "20px",
                }}
              >
                {plans.map((p) => (
                  <div
                    key={p.plan_id}
                    className="edu-card"
                    style={{
                      borderRadius: "12px",
                      background: "#FFFFFF",
                      border: p.plan_id === "growth" ? "2px solid #4F46E5" : "1px solid #E2E8F0",
                      padding: "20px",
                      position: "relative",
                    }}
                  >
                    {p.plan_id === "growth" && (
                      <span
                        style={{
                          position: "absolute",
                          top: "-10px",
                          right: "16px",
                          background: "#4F46E5",
                          color: "#FFFFFF",
                          fontSize: "10px",
                          fontWeight: 700,
                          padding: "3px 8px",
                          borderRadius: "10px",
                          textTransform: "uppercase",
                        }}
                      >
                        Most Popular
                      </span>
                    )}

                    <h4 style={{ margin: 0, fontSize: "18px", fontWeight: 700, color: "#0F172A" }}>
                      {p.name}
                    </h4>
                    <p style={{ margin: "4px 0 16px 0", fontSize: "12px", color: "#64748B" }}>
                      {p.description}
                    </p>

                    <div style={{ padding: "12px", background: "#F8FAFC", borderRadius: "8px", marginBottom: "16px" }}>
                      <div style={{ fontSize: "22px", fontWeight: 700, color: "#0F172A" }}>
                        {formatINR(p.daily_exposure_limit_inr)}
                        <span style={{ fontSize: "12px", color: "#64748B", fontWeight: 400 }}> / day</span>
                      </div>
                      <div style={{ fontSize: "12px", color: "#64748B", marginTop: "2px" }}>
                        {formatINR(p.monthly_exposure_limit_inr)} / month ceiling
                      </div>
                    </div>

                    <div style={{ fontSize: "13px", color: "#334155", display: "flex", flexDirection: "column", gap: "8px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Risk Reserve:</span>
                        <strong>{(parseFloat(p.risk_reserve_percent || 0.1) * 100).toFixed(0)}% protected</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Interactive AI:</span>
                        <strong>{parseInt(p.daily_token_limit_interactive || 0).toLocaleString()} tokens</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Ingestion Embeddings:</span>
                        <strong>{parseInt(p.daily_token_limit_ingestion || 0).toLocaleString()} tokens</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Other Metered:</span>
                        <strong>{parseInt(p.daily_token_limit_other || 0).toLocaleString()} tokens</strong>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Max Reservation:</span>
                        <strong>{parseInt(p.max_reservation_tokens || 0).toLocaleString()} tokens</strong>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* MODAL 1: Provision / Change Plan */}
          {provisionModalOpen && (
            <div
              style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: "rgba(15, 23, 42, 0.6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: "20px",
              }}
            >
              <div
                style={{
                  background: "#FFFFFF",
                  borderRadius: "12px",
                  maxWidth: "520px",
                  width: "100%",
                  maxHeight: "90vh",
                  overflowY: "auto",
                  padding: "24px",
                  boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h3 style={{ margin: 0, fontSize: "18px", fontWeight: 700, color: "#0F172A" }}>
                    Configure Plan for {selectedInst?.institution_name}
                  </h3>
                  <button
                    onClick={() => setProvisionModalOpen(false)}
                    style={{ background: "none", border: "none", cursor: "pointer", fontSize: "20px", color: "#94A3B8" }}
                  >
                    ×
                  </button>
                </div>

                <form onSubmit={handleProvisionSubmit}>
                  <div style={{ marginBottom: "14px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                      Select Subscription Tier
                    </label>
                    <select
                      value={provisionForm.plan_id}
                      onChange={handlePlanSelectChange}
                      style={{
                        width: "100%",
                        padding: "8px 12px",
                        borderRadius: "8px",
                        border: "1px solid #CBD5E1",
                        fontSize: "13px",
                      }}
                    >
                      <option value="starter">Starter Plan (₹100/day, ₹2,500/mo)</option>
                      <option value="growth">Growth Plan (₹300/day, ₹7,500/mo)</option>
                      <option value="enterprise">Enterprise Plan (₹750/day, ₹20,000/mo)</option>
                      <option value="custom">Custom Limits Plan</option>
                    </select>
                  </div>

                  <div style={{ marginBottom: "14px" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", fontWeight: 600, color: "#334155" }}>
                      <input
                        type="checkbox"
                        checked={provisionForm.override_limits}
                        onChange={(e) => setProvisionForm({ ...provisionForm, override_limits: e.target.checked })}
                      />
                      Override Standard Plan Parameters (Custom Quotas)
                    </label>
                  </div>

                  {provisionForm.override_limits && (
                    <div
                      style={{
                        padding: "12px",
                        borderRadius: "8px",
                        background: "#F8FAFC",
                        border: "1px solid #E2E8F0",
                        marginBottom: "14px",
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "10px",
                      }}
                    >
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Daily Exposure (INR)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={provisionForm.daily_exposure_limit_inr}
                          onChange={(e) => setProvisionForm({ ...provisionForm, daily_exposure_limit_inr: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Monthly Exposure (INR)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={provisionForm.monthly_exposure_limit_inr}
                          onChange={(e) => setProvisionForm({ ...provisionForm, monthly_exposure_limit_inr: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Interactive Tokens / Day
                        </label>
                        <input
                          type="number"
                          value={provisionForm.daily_token_limit_interactive}
                          onChange={(e) => setProvisionForm({ ...provisionForm, daily_token_limit_interactive: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Ingestion Tokens / Day
                        </label>
                        <input
                          type="number"
                          value={provisionForm.daily_token_limit_ingestion}
                          onChange={(e) => setProvisionForm({ ...provisionForm, daily_token_limit_ingestion: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Risk Reserve Ratio (0.10 = 10%)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          max="0.5"
                          min="0"
                          value={provisionForm.risk_reserve_percent}
                          onChange={(e) => setProvisionForm({ ...provisionForm, risk_reserve_percent: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#64748B", marginBottom: "4px" }}>
                          Max Single Reservation Tokens
                        </label>
                        <input
                          type="number"
                          value={provisionForm.max_reservation_tokens}
                          onChange={(e) => setProvisionForm({ ...provisionForm, max_reservation_tokens: e.target.value })}
                          style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "12px" }}
                        />
                      </div>
                    </div>
                  )}

                  <div style={{ marginBottom: "16px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                      Reason for Change (Audit Requirement) *
                    </label>
                    <textarea
                      required
                      placeholder="e.g. Upgrade requested by institution administrator for mid-term exams..."
                      rows="3"
                      value={provisionForm.change_reason}
                      onChange={(e) => setProvisionForm({ ...provisionForm, change_reason: e.target.value })}
                      style={{
                        width: "100%",
                        padding: "8px 12px",
                        borderRadius: "8px",
                        border: "1px solid #CBD5E1",
                        fontSize: "13px",
                      }}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                    <button
                      type="button"
                      onClick={() => setProvisionModalOpen(false)}
                      style={{
                        padding: "8px 14px",
                        borderRadius: "6px",
                        border: "1px solid #CBD5E1",
                        background: "#F8FAFC",
                        cursor: "pointer",
                        fontSize: "13px",
                        color: "#475569",
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={provisionSubmitting}
                      style={{
                        padding: "8px 16px",
                        borderRadius: "6px",
                        border: "none",
                        background: "#4F46E5",
                        color: "#FFFFFF",
                        cursor: provisionSubmitting ? "not-allowed" : "pointer",
                        fontSize: "13px",
                        fontWeight: 600,
                      }}
                    >
                      {provisionSubmitting ? "Saving..." : "Save Quota Configuration"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* MODAL 2: Manual Settle Reservation */}
          {settleModalOpen && (
            <div
              style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: "rgba(15, 23, 42, 0.6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: "20px",
              }}
            >
              <div
                style={{
                  background: "#FFFFFF",
                  borderRadius: "12px",
                  maxWidth: "480px",
                  width: "100%",
                  padding: "24px",
                  boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h3 style={{ margin: 0, fontSize: "18px", fontWeight: 700, color: "#0F172A" }}>
                    Manual Settlement
                  </h3>
                  <button
                    onClick={() => setSettleModalOpen(false)}
                    style={{ background: "none", border: "none", cursor: "pointer", fontSize: "20px", color: "#94A3B8" }}
                  >
                    ×
                  </button>
                </div>

                <p style={{ margin: "0 0 16px 0", fontSize: "13px", color: "#64748B" }}>
                  Settling reservation <code style={{ color: "#0F172A" }}>{selectedReservation?.reservation_id.slice(0, 14)}...</code>.
                  Current held cost: <strong>{formatINR(selectedReservation?.held_cost_inr)}</strong>.
                </p>

                <form onSubmit={handleSettleSubmit}>
                  <div style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                      Settled Actual Tokens
                    </label>
                    <input
                      type="number"
                      required
                      min="0"
                      value={settleForm.settled_tokens}
                      onChange={(e) => setSettleForm({ ...settleForm, settled_tokens: e.target.value })}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px" }}
                    />
                  </div>

                  <div style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                      Settled Cost INR
                    </label>
                    <input
                      type="number"
                      step="0.0001"
                      min="0"
                      required
                      value={settleForm.settled_cost_inr}
                      onChange={(e) => setSettleForm({ ...settleForm, settled_cost_inr: e.target.value })}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px" }}
                    />
                  </div>

                  <div style={{ marginBottom: "12px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                      Resolution Reason
                    </label>
                    <select
                      value={settleForm.resolution_reason}
                      onChange={(e) => setSettleForm({ ...settleForm, resolution_reason: e.target.value })}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px" }}
                    >
                      <option value="INVOICE_RECONCILED">Provider Invoice Reconciliation</option>
                      <option value="ESTIMATED_FROM_LOGS">Estimated from Gateway Logs</option>
                      <option value="WRITE_OFF_ZERO">Write-off to Zero (Provider Failed Early)</option>
                      <option value="ADMIN_OVERRIDE">Administrative Override</option>
                    </select>
                  </div>

                  <div style={{ marginBottom: "16px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                      Resolution Notes / Reference
                    </label>
                    <textarea
                      placeholder="e.g. Verified with OpenAI/Gemini monthly invoice item #4920..."
                      rows="2"
                      value={settleForm.resolution_notes}
                      onChange={(e) => setSettleForm({ ...settleForm, resolution_notes: e.target.value })}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px" }}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                    <button
                      type="button"
                      onClick={() => setSettleModalOpen(false)}
                      style={{
                        padding: "8px 14px",
                        borderRadius: "6px",
                        border: "1px solid #CBD5E1",
                        background: "#F8FAFC",
                        cursor: "pointer",
                        fontSize: "13px",
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={settleSubmitting}
                      style={{
                        padding: "8px 16px",
                        borderRadius: "6px",
                        border: "none",
                        background: "#0F172A",
                        color: "#FFFFFF",
                        cursor: settleSubmitting ? "not-allowed" : "pointer",
                        fontSize: "13px",
                        fontWeight: 600,
                      }}
                    >
                      {settleSubmitting ? "Settling..." : "Confirm Settlement"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* MODAL 3: Suspend / Resume Confirmation */}
          {statusModalOpen && (
            <div
              style={{
                position: "fixed",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: "rgba(15, 23, 42, 0.6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: "20px",
              }}
            >
              <div
                style={{
                  background: "#FFFFFF",
                  borderRadius: "12px",
                  maxWidth: "440px",
                  width: "100%",
                  padding: "24px",
                  boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)",
                }}
              >
                <h3 style={{ margin: "0 0 10px 0", fontSize: "18px", fontWeight: 700, color: "#0F172A" }}>
                  {statusActionTarget?.action === "suspend" ? "Suspend Tenant AI Access" : "Resume Tenant AI Access"}
                </h3>
                <p style={{ margin: "0 0 16px 0", fontSize: "13px", color: "#64748B" }}>
                  {statusActionTarget?.action === "suspend"
                    ? `Suspending ${statusActionTarget?.inst?.institution_name} will reject all AI requests with QUOTA_SUSPENDED.`
                    : `Resuming ${statusActionTarget?.inst?.institution_name} will restore standard quota enforcement.`}
                </p>

                <form onSubmit={handleStatusSubmit}>
                  <div style={{ marginBottom: "16px" }}>
                    <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "#334155", marginBottom: "4px" }}>
                      Reason *
                    </label>
                    <input
                      type="text"
                      required
                      placeholder={statusActionTarget?.action === "suspend" ? "e.g. Overdue billing payment..." : "e.g. Account reinstated by finance..."}
                      value={statusReason}
                      onChange={(e) => setStatusReason(e.target.value)}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", border: "1px solid #CBD5E1", fontSize: "13px" }}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                    <button
                      type="button"
                      onClick={() => setStatusModalOpen(false)}
                      style={{
                        padding: "8px 14px",
                        borderRadius: "6px",
                        border: "1px solid #CBD5E1",
                        background: "#F8FAFC",
                        cursor: "pointer",
                        fontSize: "13px",
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={statusSubmitting}
                      style={{
                        padding: "8px 16px",
                        borderRadius: "6px",
                        border: "none",
                        background: statusActionTarget?.action === "suspend" ? "#DC2626" : "#16A34A",
                        color: "#FFFFFF",
                        cursor: statusSubmitting ? "not-allowed" : "pointer",
                        fontSize: "13px",
                        fontWeight: 600,
                      }}
                    >
                      {statusSubmitting ? "Processing..." : statusActionTarget?.action === "suspend" ? "Confirm Suspension" : "Confirm Resumption"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

