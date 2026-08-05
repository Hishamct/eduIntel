import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StudyMaterialCard } from "../../components/ui";
import { studyMaterialsListData } from "../../data/studentMockData";
import { logout } from "../../api/auth";

export default function StudyMaterials() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const navigate = useNavigate();

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredMaterials = useMemo(() => {
    return studyMaterialsListData.filter((item) => {
      return selectedSubject === "ALL" || item.subject === selectedSubject;
    });
  }, [selectedSubject]);

  const handleDownload = (material) => {
    alert(`Downloading ${material.title} (${material.fileSize})`);
  };

  const handleView = (material) => {
    alert(`Opening viewer for ${material.title}`);
  };

  const subjects = ["ALL", "MATHEMATICS", "PHYSICS", "CHEMISTRY", "COMPUTER SCIENCE"];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="student"
        activeId="materials"
        logoText="EduIntel AI"
        roleText="Student Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "materials") navigate(`/student/${itemId}`);
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
                LEARNING REPOSITORY
              </span>
              <h2
                className="edu-font-heading"
                style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
              >
                Study Materials
              </h2>
              <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
                Access curated lecture notes, textbook references, and problem set solutions.
              </p>
            </div>
          </div>

          {/* Subject Filter Pills */}
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "24px" }}>
            {subjects.map((sub) => {
              const isSelected = selectedSubject === sub;
              return (
                <button
                  key={sub}
                  onClick={() => setSelectedSubject(sub)}
                  style={{
                    padding: "8px 16px",
                    borderRadius: "4px",
                    border: `1px solid ${isSelected ? "#26415E" : "#E5E5E1"}`,
                    backgroundColor: isSelected ? "#26415E" : "#FFFFFF",
                    color: isSelected ? "#FFFFFF" : "#1B2330",
                    fontFamily: "var(--font-body)",
                    fontSize: "12px",
                    fontWeight: isSelected ? 600 : 400,
                    cursor: "pointer",
                    transition: "all 0.15s ease"
                  }}
                >
                  {sub}
                </button>
              );
            })}
          </div>

          {/* Cards Grid */}
          <div className="edu-kpi-grid">
            {filteredMaterials.map((material) => (
              <StudyMaterialCard
                key={material.id}
                title={material.title}
                subject={material.subject}
                fileType={material.fileType}
                date={material.date}
                fileSize={material.fileSize}
                onDownload={() => handleDownload(material)}
                onView={() => handleView(material)}
              />
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
