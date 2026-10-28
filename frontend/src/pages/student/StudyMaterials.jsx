import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, StudyMaterialCard } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";
import PortalAssistantWidget from "../../components/PortalAssistantWidget";

const DEFAULT_STUDENT_MATERIALS = [
  {
    id: "mat-1",
    title: "Trigonometric Differential Calculus Proofs",
    subject: "MATHEMATICS",
    fileType: "PDF",
    originalFilename: "trig_calculus_proofs.pdf",
    date: "26 Sep 2026",
    fileSize: "1.4 MB",
  },
  {
    id: "mat-2",
    title: "Maxwell's Equations & Wave Mechanics Handout",
    subject: "PHYSICS",
    fileType: "PDF",
    originalFilename: "maxwell_equations_lecture5.pdf",
    date: "25 Sep 2026",
    fileSize: "2.1 MB",
  },
  {
    id: "mat-3",
    title: "Organic Chemistry Reaction Mechanisms",
    subject: "CHEMISTRY",
    fileType: "PDF",
    originalFilename: "organic_synthesis_reactions.pdf",
    date: "24 Sep 2026",
    fileSize: "3.8 MB",
  },
  {
    id: "mat-4",
    title: "Data Structures AVL Rotations & Red-Black Trees",
    subject: "COMPUTER SCIENCE",
    fileType: "PDF",
    originalFilename: "avl_balanced_trees.pdf",
    date: "22 Sep 2026",
    fileSize: "1.8 MB",
  },
  {
    id: "mat-5",
    title: "Definite Integral Substitution Cheat Sheet",
    subject: "MATHEMATICS",
    fileType: "PDF",
    originalFilename: "calculus_integral_shortcuts.pdf",
    date: "20 Sep 2026",
    fileSize: "850 KB",
  },
  {
    id: "mat-6",
    title: "Electromagnetism Past Examination Solutions (2022-2025)",
    subject: "PHYSICS",
    fileType: "PDF",
    originalFilename: "physics_past_papers_solved.pdf",
    date: "18 Sep 2026",
    fileSize: "4.2 MB",
  }
];

function mapMaterial(m) {
  return {
    id: m.id,
    title: m.title,
    subject: m.subject,
    fileType: (m.original_filename || m.fileType || "PDF").split(".").pop().toUpperCase(),
    originalFilename: m.original_filename || m.originalFilename || "document.pdf",
    date: m.created_at ? new Date(m.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }) : m.date || "Recent",
    fileSize: m.fileSize || "1.2 MB",
  };
}

export default function StudyMaterials() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedSubject, setSelectedSubject] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [materials, setMaterials] = useState(DEFAULT_STUDENT_MATERIALS);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchMaterials = async () => {
      try {
        const res = await apiClient.get("/student/study-materials");
        if (res.data && res.data.length > 0) {
          setMaterials(res.data.map(mapMaterial));
        }
      } catch (err) {
        console.warn("Backend student study materials offline, displaying demo catalog.", err);
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
      const matchesSubject = selectedSubject === "ALL" || item.subject.toUpperCase() === selectedSubject.toUpperCase();
      const matchesSearch = !searchQuery || 
        item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.subject.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesSubject && matchesSearch;
    });
  }, [materials, selectedSubject, searchQuery]);

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
      alert(`Simulated demo: "${material.title}" ${action === "download" ? "downloaded" : "opened in document viewer"}.`);
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
                <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#059669" }}>menu_book</span>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "#059669", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Learning Repository & References
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Curated Study Materials & Lecture Notes
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Access verified faculty handouts, textbook references, and problem set solutions indexed for rapid review.
              </p>
            </div>
          </div>

          {/* Metric KPI Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Available Documents</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>auto_stories</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {materials.length} Materials
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Across 4 core STEM disciplines</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>New This Week</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>new_releases</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                3 Handouts
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Calculus & Maxwell notes added</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Search & RAG AI</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>smart_toy</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                Instant Query
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Ask AI widget searches notes</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Storage & Access</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>cloud_done</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                Offline Cached
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>One-click PDF download</div>
            </div>
          </div>

          {/* Filter Pills and Search Bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", gap: "8px", overflowX: "auto", paddingBottom: "4px" }}>
              {subjects.map((sub) => (
                <button
                  key={sub}
                  onClick={() => setSelectedSubject(sub)}
                  style={{
                    padding: "8px 16px",
                    borderRadius: "9999px",
                    fontSize: "12px",
                    fontWeight: 600,
                    border: "none",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    backgroundColor: selectedSubject === sub ? "#10B981" : "rgba(255, 255, 255, 0.75)",
                    color: selectedSubject === sub ? "#FFFFFF" : "#475569",
                    boxShadow: selectedSubject === sub ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  {sub === "ALL" ? "All Disciplines" : sub}
                </button>
              ))}
            </div>

            <div style={{ position: "relative", minWidth: "240px" }}>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search notes, formulas..."
                style={{
                  width: "100%",
                  padding: "9px 14px 9px 36px",
                  borderRadius: "10px",
                  border: "1px solid rgba(226, 232, 240, 0.9)",
                  backgroundColor: "rgba(255, 255, 255, 0.85)",
                  fontSize: "13px",
                  color: "#1E293B",
                  outline: "none",
                  boxSizing: "border-box"
                }}
              />
              <span className="material-symbols-outlined" style={{ position: "absolute", left: "10px", top: "9px", fontSize: "18px", color: "#94A3B8" }}>
                search
              </span>
            </div>
          </div>

          {/* Cards Grid */}
          {filteredMaterials.length === 0 ? (
            <div className="edu-card" style={{ padding: "40px", textAlign: "center" }}>
              <span className="material-symbols-outlined" style={{ fontSize: "40px", color: "#94A3B8", marginBottom: "8px" }}>search_off</span>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0 }}>No study materials matching your filter.</p>
            </div>
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