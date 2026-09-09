import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StudyMaterialCard } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

function mapMaterial(m) {
  return {
    id: m.id,
    title: m.title,
    subject: m.subject,
    fileType: m.original_filename.split(".").pop().toUpperCase(),
    originalFilename: m.original_filename,
    date: new Date(m.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }),
    fileSize: "—", // not tracked in backend yet
  };
}

export default function StudyMaterials() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const [materials, setMaterials] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchMaterials = async () => {
      try {
        const res = await apiClient.get("/student/study-materials");
        setMaterials(res.data.map(mapMaterial));
      } catch (err) {
        console.error("Failed to load study materials:", err);
      }
    };
    fetchMaterials();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const filteredMaterials = useMemo(() => {
    return materials.filter((item) => {
      return selectedSubject === "ALL" || item.subject.toUpperCase() === selectedSubject;
    });
  }, [materials, selectedSubject]);

  const handleFileAction = async (material, action) => {
  try {
    const res = await apiClient.get(
      `/student/study-materials/${material.id}/file`,
      { responseType: "blob" }
    );

    const contentType = res.headers["content-type"] || "application/octet-stream";
    const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: contentType }));

    if (action === "view") {
      window.open(blobUrl, "_blank");
    } else {
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = material.originalFilename || material.title;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    setTimeout(() => window.URL.revokeObjectURL(blobUrl), 10000);
  } catch (err) {
    console.error(`Failed to ${action} file:`, err);
    alert(`Could not ${action} the file. Please try again.`);
  }
};

  const handleDownload = (material) => handleFileAction(material, "download");
  const handleView = (material) => handleFileAction(material, "view");

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

          {filteredMaterials.length === 0 ? (
            <p style={{ fontSize: "13px", color: "#5F6774" }}>No study materials available yet.</p>
          ) : (
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
          )}
        </main>
      </div>

      <PortalAssistantWidget />
    </div>
  );
}