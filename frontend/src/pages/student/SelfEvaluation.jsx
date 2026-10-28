import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StatusBadge } from "../../components/ui";
import { selfEvaluationData } from "../../data/studentMockData";
import { logout } from "../../api/auth";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

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

  const completedHabitsCount = habits.filter(h => h.completed).length;
  const habitPercentage = Math.round((completedHabitsCount / habits.length) * 100);

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
          user={{ name: "Arjun Nair", role: "Grade 11-A" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          {/* Header */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              marginBottom: "28px",
              flexWrap: "wrap",
              gap: "16px"
            }}
          >
            <div>
              <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "9999px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", marginBottom: "8px" }}>
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>psychology</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Personal Academic Reflection
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Self-Evaluation & Growth Tracker
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Reflect on subject-wise conceptual mastery, manage daily learning routines, and track semester achievement milestones.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => alert("Personal self-evaluation journal exported as PDF.")}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "9px 16px",
                  borderRadius: "10px",
                  fontSize: "13px",
                  fontWeight: 600,
                  background: "rgba(255, 255, 255, 0.8)",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  color: "#1E293B",
                  cursor: "pointer",
                  backdropFilter: "blur(12px)"
                }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px", color: "#64748B" }}>download</span>
                Export Reflection
              </button>
            </div>
          </div>

          {/* Metric KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Habit Consistency</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>checklist</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {habitPercentage}% Completed
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>{completedHabitsCount} of {habits.length} daily habits checked</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Confidence Average</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>sentiment_very_satisfied</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                88.5% Mastery
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>High across 3 subjects</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Milestones on Track</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>flag</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                3 of 4 Targets
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Ahead of schedule</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Weekly Study Time</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>schedule</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                26.5 Hours
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>+3.2 hrs vs last week</div>
            </div>
          </div>

          {/* Encouraging Banner */}
          <div
            className="edu-card"
            style={{
              padding: "22px 26px",
              marginBottom: "28px",
              background: "linear-gradient(135deg, rgba(16, 185, 129, 0.08), rgba(255, 255, 255, 0.95))",
              border: "1px solid rgba(16, 185, 129, 0.25)",
              display: "flex",
              alignItems: "center",
              gap: "18px"
            }}
          >
            <div style={{ width: "48px", height: "48px", borderRadius: "14px", background: "rgba(16, 185, 129, 0.15)", color: "#059669", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <span className="material-symbols-outlined" style={{ fontSize: "28px" }}>emoji_events</span>
            </div>
            <div>
              <h3 className="edu-font-heading" style={{ fontSize: "17px", fontWeight: 700, color: "#0F172A", margin: "0 0 4px 0" }}>
                {selfEvaluationData.encouragementBanner.headline}
              </h3>
              <p style={{ fontSize: "13px", color: "#64748B", margin: 0, lineHeight: 1.5 }}>
                {selfEvaluationData.encouragementBanner.subtext}
              </p>
            </div>
          </div>

          {/* Subject Progress & Reflections Grid */}
          <div style={{ marginBottom: "28px" }}>
            <h3 className="edu-font-heading" style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", margin: "0 0 16px 0" }}>
              Subject Progress & Reflections
            </h3>
            <div className="edu-kpi-grid">
              {selfEvaluationData.subjectStrengths.map((item) => (
                <div
                  key={item.subject}
                  className="edu-card"
                  style={{
                    padding: "20px",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between"
                  }}
                >
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <span style={{ fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        {item.subject}
                      </span>
                      <StatusBadge variant={item.statusVariant} label={item.statusLabel} />
                    </div>
                    <div style={{ fontSize: "28px", fontWeight: 800, color: "#0F172A", margin: "4px 0 12px 0" }}>
                      {item.score}
                    </div>
                  </div>
                  <div style={{
                    fontSize: "12px",
                    color: "#334155",
                    lineHeight: 1.5,
                    backgroundColor: "rgba(248, 250, 252, 0.8)",
                    padding: "10px 14px",
                    borderRadius: "10px",
                    border: "1px solid rgba(226, 232, 240, 0.7)",
                    fontStyle: "italic"
                  }}>
                    "{item.reflection}"
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 2-Column Split: Habits Checklist & Semester Goals */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 350px), 1fr))",
              gap: "24px"
            }}
          >
            {/* Left: Study Habits Checklist */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "17px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                  Daily Learning Routine Checklist
                </h3>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", background: "rgba(16, 185, 129, 0.1)", padding: "3px 8px", borderRadius: "9999px" }}>
                  {completedHabitsCount} / {habits.length} Done
                </span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {habits.map((habit) => (
                  <label
                    key={habit.id}
                    onClick={() => toggleHabit(habit.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      padding: "12px 14px",
                      borderRadius: "10px",
                      border: habit.completed ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(226, 232, 240, 0.8)",
                      backgroundColor: habit.completed ? "rgba(16, 185, 129, 0.06)" : "rgba(255, 255, 255, 0.8)",
                      cursor: "pointer",
                      transition: "all 0.15s ease"
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={habit.completed}
                      onChange={() => {}}
                      style={{ accentColor: "#10B981", width: "18px", height: "18px", cursor: "pointer" }}
                    />
                    <span style={{ fontSize: "13px", color: habit.completed ? "#059669" : "#1E293B", fontWeight: habit.completed ? 600 : 500, textDecoration: habit.completed ? "line-through" : "none" }}>
                      {habit.task}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* Right: Personal Semester Goals */}
            <div className="edu-card" style={{ padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h3 className="edu-font-heading" style={{ fontSize: "17px", fontWeight: 700, color: "#0F172A", margin: 0 }}>
                  Semester Goals Milestones
                </h3>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#0284C7", background: "rgba(14, 165, 233, 0.1)", padding: "3px 8px", borderRadius: "9999px" }}>
                  Active Goals
                </span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
                {selfEvaluationData.personalGoals.map((g, idx) => (
                  <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "13px" }}>
                      <span style={{ fontWeight: 600, color: "#0F172A" }}>{g.goal}</span>
                      <span style={{ color: "#059669", fontWeight: 700 }}>{g.current}</span>
                    </div>
                    <div style={{ width: "100%", height: "8px", backgroundColor: "rgba(226, 232, 240, 0.8)", borderRadius: "9999px", overflow: "hidden" }}>
                      <div style={{ width: `${g.progressPercent}%`, height: "100%", backgroundColor: "#10B981", borderRadius: "9999px", transition: "width 0.6s ease" }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>

      <PortalAssistantWidget />
    </div>
  );
}