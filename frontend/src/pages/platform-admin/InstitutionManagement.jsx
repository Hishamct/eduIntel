import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

export default function InstitutionManagement() {
  const [institutions, setInstitutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Onboarding Modal State
  const [isOnboardModalOpen, setIsOnboardModalOpen] = useState(false);
  const [onboardForm, setOnboardForm] = useState({
    name: "",
    slug: "",
    contact_email: "",
    admin_name: "",
    admin_email: "",
  });
  const [onboardLoading, setOnboardLoading] = useState(false);
  const [onboardError, setOnboardError] = useState("");
  const [onboardSuccessData, setOnboardSuccessData] = useState(null);
  const [copiedToken, setCopiedToken] = useState(false);

  // Status Toggle Modal State
  const [statusModalOpen, setStatusModalOpen] = useState(false);
  const [selectedInst, setSelectedInst] = useState(null);
  const [statusUpdating, setStatusUpdating] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    fetchInstitutions();
    const params = new URLSearchParams(location.search);
    if (params.get("action") === "onboard") {
      setIsOnboardModalOpen(true);
    }
  }, [location.search]);

  const fetchInstitutions = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiClient.get("/institutions");
      setInstitutions(response.data || []);
    } catch (err) {
      console.error("Failed to load institutions:", err);
      setError(err.response?.data?.detail || "Failed to load institutions list.");
    } finally {
      setLoading(false);
    }
  };

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleNameChange = (e) => {
    const name = e.target.value;
    // Auto-generate slug if slug hasn't been manually diverged
    const autoSlug = name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    setOnboardForm((prev) => ({
      ...prev,
      name,
      slug: prev.slug === "" || prev.slug === autoSlug.slice(0, -1) ? autoSlug : prev.slug,
    }));
  };

  const handleOnboardSubmit = async (e) => {
    e.preventDefault();
    setOnboardError("");
    setOnboardLoading(true);

    try {
      const payload = {
        name: onboardForm.name.trim(),
        slug: onboardForm.slug.trim().toLowerCase(),
        contact_email: onboardForm.contact_email.trim() || null,
        admin_name: onboardForm.admin_name.trim(),
        admin_email: onboardForm.admin_email.trim().toLowerCase(),
      };

      const response = await apiClient.post("/institutions", payload);
      setOnboardSuccessData(response.data);
      fetchInstitutions();
    } catch (err) {
      console.error("Onboarding failed:", err);
      setOnboardError(err.response?.data?.detail || "Failed to provision institution.");
    } finally {
      setOnboardLoading(false);
    }
  };

  const handleCloseOnboardModal = () => {
    setIsOnboardModalOpen(false);
    setOnboardSuccessData(null);
    setOnboardError("");
    setCopiedToken(false);
    setOnboardForm({
      name: "",
      slug: "",
      contact_email: "",
      admin_name: "",
      admin_email: "",
    });
  };

  const handleCopyActivationLink = () => {
    if (!onboardSuccessData?.activation_token) return;
    const activationUrl = `${window.location.origin}/password-reset?token=${onboardSuccessData.activation_token}`;
    navigator.clipboard.writeText(activationUrl);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 3000);
  };

  const handleStatusToggleClick = (inst) => {
    setSelectedInst(inst);
    setStatusModalOpen(true);
  };

  const handleConfirmStatusToggle = async () => {
    if (!selectedInst) return;
    setStatusUpdating(true);
    try {
      const newStatus = !selectedInst.is_active;
      await apiClient.patch(`/institutions/${selectedInst.id}/status`, {
        is_active: newStatus,
      });
      setStatusModalOpen(false);
      setSelectedInst(null);
      fetchInstitutions();
    } catch (err) {
      console.error("Status update failed:", err);
      setError(err.response?.data?.detail || "Failed to update institution status.");
    } finally {
      setStatusUpdating(false);
    }
  };

  const filteredInstitutions = institutions.filter((inst) => {
    const matchesSearch =
      inst.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inst.slug.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inst.contact_email && inst.contact_email.toLowerCase().includes(searchQuery.toLowerCase()));

    if (statusFilter === "active") return matchesSearch && inst.is_active;
    if (statusFilter === "suspended") return matchesSearch && !inst.is_active;
    return matchesSearch;
  });

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="platform_admin"
        activeId="institutions"
        logoText="eduIntel"
        roleText="Platform Administration"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId === "dashboard") {
            navigate("/platform-admin/dashboard");
          }
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Platform Admin", role: "Global Root Administrator" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
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
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: "#059669",
                    textTransform: "uppercase",
                    backgroundColor: "#DCFCE7",
                    padding: "3px 10px",
                    borderRadius: "9999px",
                  }}
                >
                  TENANT DIRECTORY & LIFECYCLE
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{
                  fontSize: "26px",
                  fontWeight: 700,
                  color: "#0F172A",
                  margin: "0 0 6px 0",
                  letterSpacing: "-0.02em",
                }}
              >
                Institution Management
              </h1>
              <p style={{ color: "#64748B", margin: 0, fontSize: "14px" }}>
                Provision schools, oversee administrative activation, and manage operational status.
              </p>
            </div>

            <button
              onClick={() => setIsOnboardModalOpen(true)}
              className="edu-btn-accent"
              style={{ display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                add_business
              </span>
              Onboard Institution
            </button>
          </div>

          {error && (
            <div
              style={{
                padding: "12px 16px",
                backgroundColor: "#FEE2E2",
                border: "1px solid #EF4444",
                borderRadius: "8px",
                color: "#B91C1C",
                fontSize: "13px",
                marginBottom: "20px",
                display: "flex",
                alignItems: "center",
                gap: "10px",
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "20px" }}>
                error
              </span>
              <span>{error}</span>
            </div>
          )}

          {/* Search & Filter Toolbar */}
          <div
            className="edu-card"
            style={{
              padding: "16px 20px",
              marginBottom: "24px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "16px",
              flexWrap: "wrap",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1, minWidth: "260px" }}>
              <span className="material-symbols-outlined" style={{ color: "#94A3B8" }}>
                search
              </span>
              <input
                type="text"
                placeholder="Search by school name, slug, or contact email..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  width: "100%",
                  border: "none",
                  outline: "none",
                  backgroundColor: "transparent",
                  fontSize: "14px",
                  color: "#0F172A",
                }}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#94A3B8" }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                    close
                  </span>
                </button>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Status:</span>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                style={{
                  padding: "6px 12px",
                  borderRadius: "8px",
                  border: "1px solid #E2E8F0",
                  backgroundColor: "#FFFFFF",
                  fontSize: "13px",
                  color: "#1E293B",
                  outline: "none",
                  cursor: "pointer",
                }}
              >
                <option value="all">All Institutions</option>
                <option value="active">Active Only</option>
                <option value="suspended">Suspended Only</option>
              </select>
            </div>
          </div>

          {/* Institutions Table */}
          <div className="edu-card" style={{ padding: "24px" }}>
            {loading ? (
              <div style={{ padding: "40px", textAlign: "center", color: "#64748B" }}>
                Loading institutions...
              </div>
            ) : filteredInstitutions.length === 0 ? (
              <div style={{ padding: "40px", textAlign: "center", color: "#64748B" }}>
                {searchQuery || statusFilter !== "all"
                  ? "No institutions match your search filters."
                  : "No institutions found. Click 'Onboard Institution' to create one."}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13.5px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #E2E8F0", textAlign: "left" }}>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>INSTITUTION</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>SLUG</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>MEMBERSHIPS</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>STATUS</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600 }}>CREATED</th>
                      <th style={{ padding: "12px 16px", color: "#64748B", fontWeight: 600, textAlign: "right" }}>ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredInstitutions.map((inst) => (
                      <tr key={inst.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                        <td style={{ padding: "14px 16px", fontWeight: 600, color: "#0F172A" }}>
                          {inst.name}
                          {inst.contact_email && (
                            <div style={{ fontSize: "12px", fontWeight: 400, color: "#64748B", marginTop: "2px" }}>
                              {inst.contact_email}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: "14px 16px", color: "#475569", fontFamily: "var(--font-mono)" }}>
                          {inst.slug}
                        </td>
                        <td style={{ padding: "14px 16px" }}>
                          <div style={{ display: "flex", gap: "6px", fontSize: "12px" }}>
                            <span
                              style={{
                                backgroundColor: "#F1F5F9",
                                padding: "2px 8px",
                                borderRadius: "6px",
                                color: "#475569",
                              }}
                            >
                              {inst.student_count || 0} Students
                            </span>
                            <span
                              style={{
                                backgroundColor: "#F1F5F9",
                                padding: "2px 8px",
                                borderRadius: "6px",
                                color: "#475569",
                              }}
                            >
                              {inst.teacher_count || 0} Teachers
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: "14px 16px" }}>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 10px",
                              borderRadius: "9999px",
                              fontSize: "11px",
                              fontWeight: 600,
                              textTransform: "uppercase",
                              backgroundColor: inst.is_active ? "#DCFCE7" : "#FEE2E2",
                              color: inst.is_active ? "#15803D" : "#B91C1C",
                            }}
                          >
                            {inst.is_active ? "Active" : "Suspended"}
                          </span>
                        </td>
                        <td style={{ padding: "14px 16px", color: "#64748B", fontSize: "12.5px" }}>
                          {inst.created_at ? new Date(inst.created_at).toLocaleDateString() : "—"}
                        </td>
                        <td style={{ padding: "14px 16px", textAlign: "right" }}>
                          <button
                            onClick={() => handleStatusToggleClick(inst)}
                            style={{
                              padding: "6px 14px",
                              fontSize: "12px",
                              fontWeight: 600,
                              borderRadius: "8px",
                              border: "1px solid",
                              cursor: "pointer",
                              transition: "all 0.15s ease",
                              backgroundColor: inst.is_active ? "#FFF1F2" : "#F0FDF4",
                              borderColor: inst.is_active ? "#FECDD3" : "#BBF7D0",
                              color: inst.is_active ? "#E11D48" : "#16A34A",
                            }}
                          >
                            {inst.is_active ? "Suspend" : "Reactivate"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Onboarding Modal */}
          {isOnboardModalOpen && (
            <div
              style={{
                position: "fixed",
                inset: 0,
                backgroundColor: "rgba(15, 23, 42, 0.6)",
                backdropFilter: "blur(4px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 100,
                padding: "20px",
              }}
            >
              <div
                className="edu-card"
                style={{
                  maxWidth: "520px",
                  width: "100%",
                  padding: "32px",
                  backgroundColor: "#FFFFFF",
                  boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
                }}
              >
                {!onboardSuccessData ? (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" }}>
                      <div>
                        <h3 className="edu-font-heading" style={{ margin: "0 0 4px 0", fontSize: "20px", color: "#0F172A" }}>
                          Onboard New Institution
                        </h3>
                        <p style={{ margin: 0, fontSize: "13px", color: "#64748B" }}>
                          Provision an isolated institution and its initial administrator.
                        </p>
                      </div>
                      <button
                        onClick={handleCloseOnboardModal}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#94A3B8" }}
                      >
                        <span className="material-symbols-outlined">close</span>
                      </button>
                    </div>

                    {onboardError && (
                      <div
                        style={{
                          padding: "10px 14px",
                          backgroundColor: "#FEE2E2",
                          border: "1px solid #EF4444",
                          borderRadius: "8px",
                          color: "#B91C1C",
                          fontSize: "12.5px",
                          marginBottom: "16px",
                        }}
                      >
                        {onboardError}
                      </div>
                    )}

                    <div
                      style={{
                        padding: "12px 14px",
                        backgroundColor: "#F0F9FF",
                        border: "1px solid #BAE6FD",
                        borderRadius: "8px",
                        color: "#0369A1",
                        fontSize: "12px",
                        marginBottom: "20px",
                        lineHeight: 1.5,
                      }}
                    >
                      <strong>Security Note:</strong> The initial administrator will be created in an inactive state with an unusable random password. A single-use 48-hour activation link will be generated.
                    </div>

                    <form onSubmit={handleOnboardSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                      <div>
                        <label style={{ display: "block", fontSize: "12.5px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                          Institution Name *
                        </label>
                        <input
                          type="text"
                          required
                          placeholder="e.g. Apex International Academy"
                          value={onboardForm.name}
                          onChange={handleNameChange}
                          style={{
                            width: "100%",
                            padding: "9px 12px",
                            borderRadius: "8px",
                            border: "1px solid #CBD5E1",
                            fontSize: "13.5px",
                            outline: "none",
                          }}
                        />
                      </div>

                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                        <div>
                          <label style={{ display: "block", fontSize: "12.5px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                            Tenant Slug *
                          </label>
                          <input
                            type="text"
                            required
                            placeholder="e.g. apex-academy"
                            value={onboardForm.slug}
                            onChange={(e) => setOnboardForm({ ...onboardForm, slug: e.target.value.toLowerCase().trim() })}
                            style={{
                              width: "100%",
                              padding: "9px 12px",
                              borderRadius: "8px",
                              border: "1px solid #CBD5E1",
                              fontSize: "13.5px",
                              outline: "none",
                              fontFamily: "var(--font-mono)",
                            }}
                          />
                        </div>

                        <div>
                          <label style={{ display: "block", fontSize: "12.5px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                            Contact Email
                          </label>
                          <input
                            type="email"
                            placeholder="contact@apex.edu"
                            value={onboardForm.contact_email}
                            onChange={(e) => setOnboardForm({ ...onboardForm, contact_email: e.target.value })}
                            style={{
                              width: "100%",
                              padding: "9px 12px",
                              borderRadius: "8px",
                              border: "1px solid #CBD5E1",
                              fontSize: "13.5px",
                              outline: "none",
                            }}
                          />
                        </div>
                      </div>

                      <div style={{ borderTop: "1px solid #E2E8F0", paddingTop: "16px" }}>
                        <div style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A", marginBottom: "12px" }}>
                          Initial Administrator Details
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                          <div>
                            <label style={{ display: "block", fontSize: "12.5px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                              Admin Full Name *
                            </label>
                            <input
                              type="text"
                              required
                              placeholder="Dr. Alex Rivera"
                              value={onboardForm.admin_name}
                              onChange={(e) => setOnboardForm({ ...onboardForm, admin_name: e.target.value })}
                              style={{
                                width: "100%",
                                padding: "9px 12px",
                                borderRadius: "8px",
                                border: "1px solid #CBD5E1",
                                fontSize: "13.5px",
                                outline: "none",
                              }}
                            />
                          </div>

                          <div>
                            <label style={{ display: "block", fontSize: "12.5px", fontWeight: 600, color: "#334155", marginBottom: "6px" }}>
                              Admin Email *
                            </label>
                            <input
                              type="email"
                              required
                              placeholder="alex@apex.edu"
                              value={onboardForm.admin_email}
                              onChange={(e) => setOnboardForm({ ...onboardForm, admin_email: e.target.value })}
                              style={{
                                width: "100%",
                                padding: "9px 12px",
                                borderRadius: "8px",
                                border: "1px solid #CBD5E1",
                                fontSize: "13.5px",
                                outline: "none",
                              }}
                            />
                          </div>
                        </div>
                      </div>

                      <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "12px" }}>
                        <button
                          type="button"
                          onClick={handleCloseOnboardModal}
                          className="edu-btn-secondary"
                          disabled={onboardLoading}
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="edu-btn-accent"
                          disabled={onboardLoading}
                          style={{ minWidth: "140px" }}
                        >
                          {onboardLoading ? "Provisioning..." : "Provision Tenant"}
                        </button>
                      </div>
                    </form>
                  </>
                ) : (
                  /* Success View */
                  <div>
                    <div style={{ textAlign: "center", marginBottom: "20px" }}>
                      <div
                        style={{
                          width: "56px",
                          height: "56px",
                          borderRadius: "50%",
                          backgroundColor: "#DCFCE7",
                          color: "#16A34A",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          margin: "0 auto 12px",
                        }}
                      >
                        <span className="material-symbols-outlined" style={{ fontSize: "32px" }}>
                          check_circle
                        </span>
                      </div>
                      <h3 className="edu-font-heading" style={{ margin: "0 0 6px 0", fontSize: "20px", color: "#0F172A" }}>
                        Tenant Provisioned Successfully
                      </h3>
                      <p style={{ margin: 0, fontSize: "13px", color: "#64748B" }}>
                        {onboardSuccessData.name} ({onboardSuccessData.slug})
                      </p>
                    </div>

                    <div
                      style={{
                        backgroundColor: "#F8FAFC",
                        border: "1px solid #E2E8F0",
                        borderRadius: "10px",
                        padding: "16px",
                        marginBottom: "20px",
                        fontSize: "13px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                        <span style={{ color: "#64748B" }}>Initial Administrator:</span>
                        <span style={{ fontWeight: 600, color: "#0F172A" }}>{onboardSuccessData.admin_name}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                        <span style={{ color: "#64748B" }}>Admin Email:</span>
                        <span style={{ fontWeight: 600, color: "#0F172A" }}>{onboardSuccessData.admin_email}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                        <span style={{ color: "#64748B" }}>Account Status:</span>
                        <span style={{ color: "#D97706", fontWeight: 600 }}>Inactive (Pending Activation)</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ color: "#64748B" }}>Invitation Channel:</span>
                        <span style={{ color: "#16A34A", fontWeight: 600 }}>
                          {onboardSuccessData.invitation_sent ? "Dispatched via SMTP" : "Offline Link Only"}
                        </span>
                      </div>
                    </div>

                    {onboardSuccessData.activation_token && (
                      <div style={{ marginBottom: "24px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                          <span style={{ fontSize: "12px", fontWeight: 600, color: "#475569" }}>
                            One-Time Activation Token (Expires in 48 Hours)
                          </span>
                          <span style={{ fontSize: "11px", color: "#B91C1C", fontWeight: 600 }}>
                            Displayed Once Only
                          </span>
                        </div>
                        <div
                          style={{
                            padding: "10px 12px",
                            backgroundColor: "#F1F5F9",
                            border: "1px dashed #94A3B8",
                            borderRadius: "8px",
                            fontFamily: "var(--font-mono)",
                            fontSize: "12px",
                            wordBreak: "break-all",
                            color: "#0F172A",
                            marginBottom: "10px",
                          }}
                        >
                          {onboardSuccessData.activation_token}
                        </div>
                        <button
                          onClick={handleCopyActivationLink}
                          className="edu-btn-secondary"
                          style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}
                        >
                          <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>
                            {copiedToken ? "check" : "content_copy"}
                          </span>
                          {copiedToken ? "Activation Link Copied!" : "Copy Full Activation Link"}
                        </button>
                      </div>
                    )}

                    <button
                      onClick={handleCloseOnboardModal}
                      className="edu-btn-primary"
                      style={{ width: "100%", padding: "12px" }}
                    >
                      Done & Return to Directory
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Status Suspension / Reactivation Confirmation Modal */}
          {statusModalOpen && selectedInst && (
            <div
              style={{
                position: "fixed",
                inset: 0,
                backgroundColor: "rgba(15, 23, 42, 0.6)",
                backdropFilter: "blur(4px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 100,
                padding: "20px",
              }}
            >
              <div
                className="edu-card"
                style={{
                  maxWidth: "460px",
                  width: "100%",
                  padding: "28px",
                  backgroundColor: "#FFFFFF",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                  <div
                    style={{
                      width: "44px",
                      height: "44px",
                      borderRadius: "50%",
                      backgroundColor: selectedInst.is_active ? "#FEE2E2" : "#DCFCE7",
                      color: selectedInst.is_active ? "#DC2626" : "#16A34A",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "24px" }}>
                      {selectedInst.is_active ? "warning" : "check_circle"}
                    </span>
                  </div>
                  <div>
                    <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "18px", color: "#0F172A" }}>
                      {selectedInst.is_active ? "Suspend Institution" : "Reactivate Institution"}
                    </h3>
                    <p style={{ margin: "2px 0 0 0", fontSize: "13px", color: "#64748B" }}>
                      {selectedInst.name}
                    </p>
                  </div>
                </div>

                <p style={{ fontSize: "13.5px", color: "#475569", lineHeight: 1.5, marginBottom: "20px" }}>
                  {selectedInst.is_active
                    ? "Suspending this institution will immediately block all its exclusive members (students, teachers, administrators) from authenticating and accessing academic resources. Users with memberships in other active institutions will retain access to those schools."
                    : "Reactivating this institution will immediately restore authentication and tenant workspace access for all active members."}
                </p>

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                  <button
                    type="button"
                    onClick={() => setStatusModalOpen(false)}
                    className="edu-btn-secondary"
                    disabled={statusUpdating}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmStatusToggle}
                    disabled={statusUpdating}
                    style={{
                      padding: "10px 18px",
                      borderRadius: "10px",
                      fontWeight: 600,
                      fontSize: "13px",
                      border: "none",
                      cursor: "pointer",
                      backgroundColor: selectedInst.is_active ? "#DC2626" : "#16A34A",
                      color: "#FFFFFF",
                    }}
                  >
                    {statusUpdating
                      ? "Updating..."
                      : selectedInst.is_active
                      ? "Confirm Suspension"
                      : "Confirm Reactivation"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

