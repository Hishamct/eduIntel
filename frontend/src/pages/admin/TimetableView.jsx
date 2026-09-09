import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const SECTIONS = ["Grade 10-A", "Grade 10-B", "Grade 11-A", "Grade 11-B", "Grade 12-A"];
const SUBJECTS = ["MATHEMATICS", "PHYSICS", "CHEMISTRY", "COMPUTER SCIENCE"];

function mapEntry(entry, teacherMap) {
  return {
    id: entry.id,
    classSection: entry.class_section,
    dayOfWeek: entry.day_of_week,
    period: entry.period,
    subject: entry.subject,
    teacherEmail: entry.teacher_id ? (teacherMap[entry.teacher_id] || "Unknown") : "Unassigned",
  };
}

export default function TimetableView() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [entries, setEntries] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [newSection, setNewSection] = useState("Grade 12-A");
  const [newDay, setNewDay] = useState("Monday");
  const [newPeriod, setNewPeriod] = useState(1);
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newTeacherId, setNewTeacherId] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const navigate = useNavigate();

  const teacherMap = teachers.reduce((acc, t) => {
    acc[t.id] = t.email;
    return acc;
  }, {});

  const fetchEntries = async () => {
    try {
      const res = await apiClient.get("/admin/timetable");
      setEntries(res.data.map((e) => mapEntry(e, teacherMap)));
    } catch (err) {
      console.error("Failed to load timetable:", err);
    }
  };

  const fetchTeachers = async () => {
    try {
      const res = await apiClient.get("/admin/teachers");
      setTeachers(res.data);
    } catch (err) {
      console.error("Failed to load teachers:", err);
    }
  };

  useEffect(() => {
    fetchTeachers();
  }, []);

  useEffect(() => {
    if (teachers.length >= 0) {
      fetchEntries();
    }
  }, [teachers]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleCreateEntry = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await apiClient.post("/admin/timetable", {
        class_section: newSection,
        day_of_week: newDay,
        period: Number(newPeriod),
        subject: newSubject,
        teacher_id: newTeacherId || null,
      });
      await fetchEntries();
      alert("Timetable entry created!");
    } catch (err) {
      console.error("Failed to create entry:", err);
      alert("Failed to create timetable entry.");
    } finally {
      setIsSaving(false);
    }
  };

  const columns = [
    { key: "classSection", label: "Class Section", sortable: true },
    { key: "dayOfWeek", label: "Day", sortable: true },
    { key: "period", label: "Period", sortable: true },
    { key: "subject", label: "Subject", sortable: true },
    { key: "teacherEmail", label: "Teacher", sortable: true },
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="timetable"
        logoText="EduIntel AI"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "timetable") navigate(`/admin/${itemId}`);
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
              CLASS SCHEDULING
            </span>
            <h2 className="edu-font-heading" style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}>
              Timetable Management
            </h2>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
              Create and review class period schedules across sections.
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
                Create Timetable Entry
              </h3>

              <form onSubmit={handleCreateEntry} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Class Section</label>
                  <select
                    value={newSection}
                    onChange={(e) => setNewSection(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Day</label>
                    <select
                      value={newDay}
                      onChange={(e) => setNewDay(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                    >
                      {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
                    </select>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Period</label>
                    <input
                      type="number"
                      min="1"
                      max="10"
                      value={newPeriod}
                      onChange={(e) => setNewPeriod(e.target.value)}
                      style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                    />
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Subject</label>
                  <select
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>Assign Teacher (optional)</label>
                  <select
                    value={newTeacherId}
                    onChange={(e) => setNewTeacherId(e.target.value)}
                    style={{ padding: "10px", borderRadius: "4px", border: "1px solid #E5E5E1", backgroundColor: "#F4F4F1", fontSize: "13px", outline: "none", color: "#1B2330" }}
                  >
                    <option value="">Unassigned</option>
                    {teachers.map((t) => <option key={t.id} value={t.id}>{t.email}</option>)}
                  </select>
                </div>

                <button
                  className="edu-btn-primary"
                  type="submit"
                  disabled={isSaving}
                  style={{ width: "100%", padding: "12px", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", opacity: isSaving ? 0.6 : 1 }}
                >
                  {isSaving ? "SAVING..." : "CREATE ENTRY"}
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>add</span>
                </button>
              </form>
            </div>

            <DataTable
              title="Timetable Entries"
              columns={columns}
              data={entries}
              pageSize={8}
            />
          </div>
        </main>
      </div>
    </div>
  );
}