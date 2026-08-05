import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, KpiCard, StatusBadge } from "../../components/ui";
import { selfEvaluationData } from "../../data/studentMockData";
import { logout } from "../../api/auth";

export default function SelfEvaluation() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [habits, setHabits] = useState(selfEvaluationData.studyHabitsChecklist);
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const toggleHabit = (id) => {
    setHabits((prev) =>
      prev.map((h) => (h.id === id ? { ...h, completed: !h.completed } : h))
    );
  };

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="student"
        activeId="self-eval"
        logoText="EduIntel AI"
        roleText="Student Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "self-eval") navigate(`/student/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Arjun Nair", role: "Student" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header Bar */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              marginBottom: "24px",
              flexWrap: "wrap",
              gap: "12px"
            }}
          >
            <div>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  color: "#5F6774",
                  textTransform: "uppercase"
                }}
              >
                PERSONAL ACADEMIC REFLECTION
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Self-Evaluation & Growth Tracker
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Review personal learning reflections, track study habits, and monitor your academic goals.
              </p>
            </div>
          </div>

          {/* Encouraging Banner */}
          <div
            className="edu-card"
            style={{
              padding: "20px 24px",
              marginBottom: "24px",
              backgroundColor: "#FFFFFF",
              borderLeft: "4px solid #3C8C5D",
              boxShadow: "0 4px 12px rgba(60, 140, 93, 0.08)"
            }}
          >
            <h3 className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 600, color: "#26415E", margin: "0 0 6px 0" }}>
              {selfEvaluationData.encouragementBanner.headline}
            </h3>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: 0, lineHeight: 1.5 }}>
              {selfEvaluationData.encouragementBanner.subtext}
            </p>
          </div>

          {/* Subject Reflections Cards */}
          <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 16px 0" }}>
            Subject Progress & Reflections
          </h4>
          <div className="edu-kpi-grid" style={{ marginBottom: "24px" }}>
            {selfEvaluationData.subjectStrengths.map((item) => (
              <div key={item.subject} className="edu-card" style={{ padding: "20px", display: "flex", flexDirection: "column", justifyBetween: "space-between" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase" }}>{item.subject}</span>
                  <StatusBadge variant={item.statusVariant} label={item.statusLabel} />
                </div>
                <h3 className="edu-font-heading" style={{ fontSize: "28px", fontWeight: 600, color: "#26415E", margin: "4px 0 12px 0" }}>
                  {item.score}
                </h3>
                <p style={{ fontSize: "12px", color: "#5F6774", margin: 0, lineHeight: 1.4, backgroundColor: "#F4F4F1", padding: "8px 12px", borderRadius: "4px" }}>
                  "{item.reflection}"
                </p>
              </div>
            ))}
          </div>

          {/* 2-Column Section: Study Habits & Personal Goals */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
              gap: "24px"
            }}
          >
            {/* Left: Study Habits Checklist */}
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 14px 0" }}>
                Daily Learning Routine Checklist
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {habits.map((habit) => (
                  <label
                    key={habit.id}
                    onClick={() => toggleHabit(habit.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      padding: "10px 14px",
                      borderRadius: "4px",
                      border: "1px solid #E5E5E1",
                      backgroundColor: habit.completed ? "rgba(60, 140, 93, 0.05)" : "#FFFFFF",
                      cursor: "pointer",
                      transition: "all 0.15s ease"
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={habit.completed}
                      onChange={() => {}}
                      style={{ accentColor: "#3C8C5D", width: "16px", height: "16px" }}
                    />
                    <span style={{ fontSize: "13px", color: "#1B2330", textDecoration: habit.completed ? "line-through" : "none" }}>
                      {habit.task}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* Right: Personal Goals */}
            <div className="edu-card" style={{ padding: "20px" }}>
              <h4 className="edu-font-heading" style={{ fontSize: "16px", fontWeight: 600, color: "#1B2330", margin: "0 0 14px 0" }}>
                Semester Goals Progress
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {selfEvaluationData.personalGoals.map((g, idx) => (
                  <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "#1B2330" }}>
                      <span style={{ fontWeight: 600 }}>{g.goal}</span>
                      <span style={{ color: "#3C8C5D", fontWeight: 700 }}>{g.current}</span>
                    </div>
                    <div style={{ width: "100%", height: "6px", backgroundColor: "#F4F4F1", borderRadius: "3px", overflow: "hidden" }}>
                      <div style={{ width: `${g.progressPercent}%`, height: "100%", backgroundColor: "#3C8C5D", transition: "width 0.6s ease" }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
