import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

function mapRecord(record, teacherMap) {
  const net = Number(record.base_salary) + Number(record.bonus) - Number(record.deduction);
  return {
    id: record.id,
    teacherEmail: teacherMap[record.teacher_id] || "Unknown",
    month: new Date(record.month).toLocaleDateString("en-IN", { month: "long", year: "numeric" }),
    baseSalary: Number(record.base_salary).toFixed(2),
    bonus: Number(record.bonus).toFixed(2),
    deduction: Number(record.deduction).toFixed(2),
    netPay: net.toFixed(2),
    statusVariant: record.payment_status === "paid" ? "on-track" : "needs-attention",
    statusLabel: record.payment_status.toUpperCase(),
  };
}

export default function SalaryManagement() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [records, setRecords] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [newTeacherId, setNewTeacherId] = useState("");
  const [newMonth, setNewMonth] = useState("");
  const [newBaseSalary, setNewBaseSalary] = useState(45000);
  const [newBonus, setNewBonus] = useState(0);
  const [newDeduction, setNewDeduction] = useState(0);
  const [newStatus, setNewStatus] = useState("pending");
  const [isSaving, setIsSaving] = useState(false);
  const navigate = useNavigate();

  const teacherMap = teachers.reduce((acc, t) => {
    acc[t.id] = t.email;
    return acc;
  }, {});

  const fetchRecords = async () => {
    try {
      const res = await apiClient.get("/admin/salary");
      setRecords(res.data.map((r) => mapRecord(r, teacherMap)));
    } catch (err) {
      console.error("Failed to load salary records:", err);
    }
  };

  const fetchTeachers = async () => {
    try {
      const res = await apiClient.get("/admin/teachers");
      setTeachers(res.data);
      if (res.data.length > 0) setNewTeacherId(res.data[0].id);
    } catch (err) {
      console.error("Failed to load teachers:", err);
    }
  };

  useEffect(() => {
    fetchTeachers();
  }, []);

  useEffect(() => {
    if (teachers.length >= 0) {
      fetchRecords();
    }
  }, [teachers]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleCreateRecord = async (e) => {
    e.preventDefault();
    if (!newTeacherId) {
      alert("Please select a teacher.");
      return;
    }
    if (!newMonth) {
      alert("Please select a month.");
      return;
    }

    setIsSaving(true);
    try {
      await apiClient.post("/admin/salary", {
        teacher_id: newTeacherId,
        month: `${newMonth}-01`,
        base_salary: Number(newBaseSalary),
        bonus: Number(newBonus),
        deduction: Number(newDeduction),
        payment_status: newStatus,
      });
      await fetchRecords();
      alert("Salary record created!");
    } catch (err) {
      console.error("Failed to create salary record:", err);
      alert("Failed to create salary record.");
    } finally {
      setIsSaving(false);
    }
  };

  const columns = [
    { key: "teacherEmail", label: "Teacher", sortable: true },
    { key: "month", label: "Month", sortable: true },
    { key: "baseSalary", label: "Base Salary", sortable: true, render: (row) => `₹${row.baseSalary}` },
    { key: "bonus", label: "Bonus", sortable: true, render: (row) => `₹${row.bonus}` },
    { key: "deduction", label: "Deduction", sortable: true, render: (row) => `₹${row.deduction}` },
    { key: "netPay", label: "Net Pay", sortable: true, render: (row) => <strong>₹{row.netPay}</strong> },
    {
      key: "status",
      label: "Status",
      sortable: true,
      render: (row) => <StatusBadge variant={row.statusVariant} label={row.statusLabel} />
    },
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="salary"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "salary") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Administrator Portal", role: "Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ marginBottom: "24px" }}>
            <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
              PAYROLL
            </span>
            <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
              Salary Management
            </h2>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
              Record and review monthly teacher compensation.
            </p>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px",
              alignItems: "start"
            }}
          >
            <div className="edu-card" style={{ padding: "24px" }}>
              <h3 className="edu-font-heading" style={{ margin: "0 0 16px 0", fontSize: "16px", fontWeight: 600, color: "#1B2330" }}>
                Create Salary Record
              </h3>

              <form onSubmit={handleCreateRecord} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Teacher</label>
                  <select
                    value={newTeacherId}
                    onChange={(e) => setNewTeacherId(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    {teachers.length === 0 && <option value="">No teachers found</option>}
                    {teachers.map((t) => <option key={t.id} value={t.id}>{t.email}</option>)}
                  </select>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Month</label>
                  <input
                    type="month"
                    value={newMonth}
                    onChange={(e) => setNewMonth(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Base Salary (₹)</label>
                    <input
                      type="number"
                      value={newBaseSalary}
                      onChange={(e) => setNewBaseSalary(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                    />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Bonus (₹)</label>
                    <input
                      type="number"
                      value={newBonus}
                      onChange={(e) => setNewBonus(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                    />
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Deduction (₹)</label>
                  <input
                    type="number"
                    value={newDeduction}
                    onChange={(e) => setNewDeduction(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Payment Status</label>
                  <select
                    value={newStatus}
                    onChange={(e) => setNewStatus(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    <option value="pending">Pending</option>
                    <option value="paid">Paid</option>
                  </select>
                </div>

                <button
                  className="edu-btn-primary"
                  type="submit"
                  disabled={isSaving}
                  style={{ width: "100%", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", opacity: isSaving ? 0.6 : 1 }}
                >
                  {isSaving ? "SAVING..." : "CREATE RECORD"}
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>add</span>
                </button>
              </form>
            </div>

            <DataTable
              title="Salary Records"
              columns={columns}
              data={records}
              pageSize={8}
            />
          </div>
        </main>
      </div>
    </div>
  );
}