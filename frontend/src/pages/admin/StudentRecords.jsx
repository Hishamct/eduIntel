import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, Modal } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

const SECTIONS = ["Grade 10-A", "Grade 10-B", "Grade 11-A", "Grade 11-B", "Grade 12-A"];

function initials(name, email) {
  const source = name || email;
  const parts = source.split(name ? " " : "@")[0].split(" ");
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function mapStudent(s) {
  return {
    id: s.id,
    name: s.name || "(No name set)",
    avatarInitials: initials(s.name, s.email),
    email: s.email,
    gradeClass: s.section || "Unassigned",
    rollNumber: s.roll_number || "--",
    joinedDate: new Date(s.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }),
    phone: s.phone || "Not provided",
    address: s.address || "Not provided",
    parentEmail: s.parent_email || "Not provided",
    guardianName: s.guardian_name || "Not provided",
    guardianPhone: s.guardian_phone || "Not provided",
  };
}

const emptyForm = {
  name: "", email: "", password: "", grade: "", section: "Grade 12-A",
  roll_number: "", parent_email: "", phone: "", address: "",
  guardian_name: "", guardian_phone: "",
};

export default function StudentRecords() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedClass, setSelectedClass] = useState("All");
  const [students, setStudents] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
  const [isEnrollModalOpen, setIsEnrollModalOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [isSaving, setIsSaving] = useState(false);
  const navigate = useNavigate();

  const fetchStudents = async () => {
    try {
      const res = await apiClient.get("/admin/students");
      setStudents(res.data.map(mapStudent));
    } catch (err) {
      console.error("Failed to load students:", err);
    }
  };

  useEffect(() => {
    fetchStudents();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredData = useMemo(() => {
    if (selectedClass === "All") return students;
    return students.filter((s) => s.gradeClass === selectedClass);
  }, [students, selectedClass]);

  const handleViewProfile = (student) => {
    setSelectedStudent(student);
    setIsProfileModalOpen(true);
  };

  const handleFormChange = (field) => (e) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
  };

  const handleEnrollStudent = async () => {
    if (!form.name || !form.email || !form.password) {
      alert("Name, email, and password are required.");
      return;
    }

    setIsSaving(true);
    try {
      await apiClient.post("/admin/students", {
        email: form.email,
        password: form.password,
        name: form.name,
        grade: form.grade || null,
        section: form.section || null,
        roll_number: form.roll_number || null,
        parent_email: form.parent_email || null,
        phone: form.phone || null,
        address: form.address || null,
        guardian_name: form.guardian_name || null,
        guardian_phone: form.guardian_phone || null,
      });
      await fetchStudents();
      setForm(emptyForm);
      setIsEnrollModalOpen(false);
      alert(`Student "${form.name}" enrolled successfully!`);
    } catch (err) {
      const detail = err.response?.data?.detail || "Failed to enroll student.";
      alert(detail);
      console.error("Failed to enroll student:", err);
    } finally {
      setIsSaving(false);
    }
  };

  const columns = [
    {
      key: "name",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              width: "32px", height: "32px", borderRadius: "50%",
              backgroundColor: "rgba(38, 65, 94, 0.1)", color: "#26415E",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 700, fontSize: "12px", fontFamily: "var(--font-heading)"
            }}
          >
            {row.avatarInitials}
          </div>
          <div>
            <span style={{ fontWeight: 600, color: "#1B2330" }}>{row.name}</span>
            <span style={{ display: "block", fontSize: "10px", color: "#5F6774" }}>{row.email}</span>
          </div>
        </div>
      )
    },
    { key: "gradeClass", label: "Class Section", sortable: true },
    { key: "rollNumber", label: "Roll Number", sortable: true },
    { key: "joinedDate", label: "Joined Date", sortable: true },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => handleViewProfile(row)}
            className="edu-btn-secondary"
            style={{ padding: "4px 10px", fontSize: "11px" }}
          >
            View Profile
          </button>
        </div>
      )
    }
  ];

  const formFieldStyle = {
    padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1",
    backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330", width: "100%",
  };
  const labelStyle = { fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" };

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="students"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "students") navigate(`/admin/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Administrator Portal", role: "Admin" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "flex-end",
              marginBottom: "24px", flexWrap: "wrap", gap: "12px"
            }}
          >
            <div>
              <span style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.05em", color: "#5F6774", textTransform: "uppercase" }}>
                ADMINISTRATOR PORTAL
              </span>
              <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
                Student Records
              </h2>
            </div>
          </div>

          <div
            className="edu-card"
            style={{
              padding: "16px 20px", marginBottom: "24px", display: "flex",
              alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "16px"
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <label style={labelStyle}>Class Filter</label>
              <select
                value={selectedClass}
                onChange={(e) => setSelectedClass(e.target.value)}
                style={{ padding: "6px 12px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", color: "#1B2330", outline: "none" }}
              >
                <option value="All">All Classes</option>
                {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>

            <button
              onClick={() => setIsEnrollModalOpen(true)}
              className="edu-btn-primary"
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>add</span>
              New Student
            </button>
          </div>

          <DataTable
            title="Student Directory Master List"
            columns={columns}
            data={filteredData}
            pageSize={10}
          />
        </main>
      </div>

      {selectedStudent && (
        <Modal
          isOpen={isProfileModalOpen}
          onClose={() => setIsProfileModalOpen(false)}
          title={`Student Profile: ${selectedStudent.name}`}
          icon="person"
          iconVariant="info"
          primaryLabel="CLOSE PROFILE"
          onPrimary={() => setIsProfileModalOpen(false)}
          description={
            <div style={{ display: "flex", flexDirection: "column", gap: "16px", textAlign: "left" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "16px", paddingBottom: "16px", borderBottom: "1px solid #E5E5E1" }}>
                <div
                  style={{
                    width: "52px", height: "52px", borderRadius: "50%", backgroundColor: "#26415E",
                    color: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "20px", fontWeight: 700, fontFamily: "var(--font-heading)"
                  }}
                >
                  {selectedStudent.avatarInitials}
                </div>
                <div>
                  <h4 style={{ margin: 0, color: "#1B2330", fontSize: "18px" }}>{selectedStudent.name}</h4>
                  <p style={{ margin: "2px 0 0 0", color: "#5F6774", fontSize: "12px", fontFamily: "var(--font-mono)" }}>
                    {selectedStudent.gradeClass} • Roll {selectedStudent.rollNumber}
                  </p>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                <div className="edu-card" style={{ padding: "12px", backgroundColor: "#FAFAF7" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", margin: 0, textTransform: "uppercase" }}>
                    Contact Information
                  </p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "6px 0 2px 0" }}>📧 {selectedStudent.email}</p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "2px 0" }}>📞 {selectedStudent.phone}</p>
                  <p style={{ fontSize: "12px", color: "#5F6774", margin: "2px 0 0 0" }}>📍 {selectedStudent.address}</p>
                </div>

                <div className="edu-card" style={{ padding: "12px", backgroundColor: "#FAFAF7" }}>
                  <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", margin: 0, textTransform: "uppercase" }}>
                    Guardian Details
                  </p>
                  <p style={{ fontSize: "12px", fontWeight: 600, color: "#1B2330", margin: "6px 0 2px 0" }}>{selectedStudent.guardianName}</p>
                  <p style={{ fontSize: "12px", color: "#1B2330", margin: "2px 0" }}>📞 {selectedStudent.guardianPhone}</p>
                  <p style={{ fontSize: "12px", color: "#5F6774", margin: "2px 0 0 0" }}>✉️ {selectedStudent.parentEmail}</p>
                </div>
              </div>

              <div className="edu-card" style={{ padding: "12px", border: "1px dashed #C9C9C3", backgroundColor: "#FAFAF8" }}>
                <p style={{ fontSize: "11px", fontWeight: 700, color: "#92ADCF", margin: 0, textTransform: "uppercase" }}>
                  Performance Pulse — Preview
                </p>
                <p style={{ fontSize: "12px", color: "#92ADCF", margin: "6px 0 0 0" }}>
                  Attendance and GPA tracking unlock once the admin attendance module and ML analytics are live.
                </p>
              </div>
            </div>
          }
        />
      )}

      <Modal
        isOpen={isEnrollModalOpen}
        onClose={() => setIsEnrollModalOpen(false)}
        title="Enroll New Student"
        icon="person_add"
        iconVariant="info"
        primaryLabel={isSaving ? "SAVING..." : "ENROLL STUDENT"}
        onPrimary={handleEnrollStudent}
        secondaryLabel="CANCEL"
        onSecondary={() => setIsEnrollModalOpen(false)}
        description={
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", textAlign: "left" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div>
                <label style={labelStyle}>Full Name *</label>
                <input style={formFieldStyle} value={form.name} onChange={handleFormChange("name")} placeholder="Priya Krishnan" />
              </div>
              <div>
                <label style={labelStyle}>Email *</label>
                <input style={formFieldStyle} value={form.email} onChange={handleFormChange("email")} placeholder="priya@example.com" />
              </div>
            </div>

            <div>
              <label style={labelStyle}>Temporary Password *</label>
              <input style={formFieldStyle} type="password" value={form.password} onChange={handleFormChange("password")} placeholder="Set a temporary password" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
              <div>
                <label style={labelStyle}>Grade</label>
                <input style={formFieldStyle} value={form.grade} onChange={handleFormChange("grade")} placeholder="12" />
              </div>
              <div>
                <label style={labelStyle}>Section</label>
                <select style={formFieldStyle} value={form.section} onChange={handleFormChange("section")}>
                  {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label style={labelStyle}>Roll Number</label>
                <input style={formFieldStyle} value={form.roll_number} onChange={handleFormChange("roll_number")} placeholder="12A-07" />
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div>
                <label style={labelStyle}>Phone</label>
                <input style={formFieldStyle} value={form.phone} onChange={handleFormChange("phone")} placeholder="+91 98765 43210" />
              </div>
              <div>
                <label style={labelStyle}>Address</label>
                <input style={formFieldStyle} value={form.address} onChange={handleFormChange("address")} placeholder="Kaloor, Kochi" />
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div>
                <label style={labelStyle}>Guardian Name</label>
                <input style={formFieldStyle} value={form.guardian_name} onChange={handleFormChange("guardian_name")} placeholder="Ramesh Krishnan" />
              </div>
              <div>
                <label style={labelStyle}>Guardian Phone</label>
                <input style={formFieldStyle} value={form.guardian_phone} onChange={handleFormChange("guardian_phone")} placeholder="+91 98765 43211" />
              </div>
            </div>

            <div>
              <label style={labelStyle}>Parent Email</label>
              <input style={formFieldStyle} value={form.parent_email} onChange={handleFormChange("parent_email")} placeholder="parent@example.com" />
            </div>
          </div>
        }
      />
    </div>
  );
}