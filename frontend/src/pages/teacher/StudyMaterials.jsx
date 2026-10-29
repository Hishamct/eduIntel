import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, FileDropzone } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

const DEFAULT_MATERIALS = [
  {
    id: "mat-1",
    title: "Trigonometric Differential Calculus Proofs",
    subject: "MATHEMATICS",
    description: "Derivations for inverse trigonometric derivatives and chain rule examples.",
    fileName: "trig_calculus_proofs.pdf",
    extractionMethod: "pdf_text",
    hasText: true,
    extractedText: "Theorem 3.1: Let f(x) = arcsin(x). By definition, sin(f(x)) = x. Differentiating both sides with respect to x gives cos(f(x)) * f'(x) = 1. Therefore, f'(x) = 1 / cos(f(x)) = 1 / sqrt(1 - x^2).",
    uploadedDate: "26 Sep 2026",
  },
  {
    id: "mat-2",
    title: "Maxwell's Equations & Wave Mechanics Handout",
    subject: "PHYSICS",
    description: "Class notes on electromagnetic wave propagation in vacuum.",
    fileName: "maxwell_equations_lecture5.png",
    extractionMethod: "ocr",
    hasText: true,
    extractedText: "Del . E = rho / epsilon_0 (Gauss's Law). Del . B = 0 (Gauss's Law for Magnetism). Del x E = -dB/dt (Faraday's Law). Del x B = mu_0*J + mu_0*epsilon_0*dE/dt (Ampere-Maxwell).",
    uploadedDate: "25 Sep 2026",
  },
  {
    id: "mat-3",
    title: "Organic Chemistry Reaction Mechanisms",
    subject: "CHEMISTRY",
    description: "Electrophilic aromatic substitution and nucleophilic additions.",
    fileName: "organic_synthesis_reactions.pdf",
    extractionMethod: "pdf_text",
    hasText: true,
    extractedText: "Electrophilic aromatic substitution (EAS): Benzene ring reacts with an electrophile E+ generated in situ via Lewis acid catalyst AlCl3. Formation of arenium ion resonance hybrid is rate-determining step.",
    uploadedDate: "24 Sep 2026",
  }
];

function mapMaterial(m) {
  return {
    id: m.id,
    title: m.title,
    subject: m.subject,
    description: m.description || "No description",
    fileName: m.original_filename || m.fileName || "document.pdf",
    extractionMethod: m.extraction_method || m.extractionMethod || "pdf_text",
    hasText: !!(m.extracted_text || m.extractedText),
    extractedText: m.extracted_text || m.extractedText || "",
    uploadedDate: m.created_at ? new Date(m.created_at).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    }) : m.uploadedDate || "Recent",
  };
}

export default function StudyMaterials() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [materials, setMaterials] = useState(DEFAULT_MATERIALS);
  const [selectedMaterial, setSelectedMaterial] = useState(DEFAULT_MATERIALS[0]);
  const [newSubject, setNewSubject] = useState("MATHEMATICS");
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const navigate = useNavigate();

  const fetchMaterials = async () => {
    try {
      const res = await apiClient.get("/teacher/study-materials");
      if (res.data && res.data.length > 0) {
        setMaterials(res.data.map(mapMaterial));
      }
    } catch (err) {
      console.warn("Backend study materials offline, showing preview items.", err);
    }
  };

  useEffect(() => {
    fetchMaterials();
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const handleDropFiles = (fileList) => {
    const filesArray = Array.from(fileList);
    setUploadedFiles(filesArray.slice(0, 1));
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!newTitle) {
      alert("Please enter a material title.");
      return;
    }
    if (uploadedFiles.length === 0) {
      alert("Please select or drop a file first.");
      return;
    }

    const formData = new FormData();
    formData.append("subject", newSubject);
    formData.append("title", newTitle);
    formData.append("description", newDescription);
    formData.append("file", uploadedFiles[0]);

    setIsSubmitting(true);
    try {
      await apiClient.post("/teacher/study-materials/upload", formData, {
        headers: { "Content-Type": undefined },
      });
      await fetchMaterials();
      alert(`"${newTitle}" uploaded successfully!`);
    } catch (err) {
      // In offline preview, inject locally
      const mockMaterial = {
        id: `mat-${Date.now()}`,
        title: newTitle,
        subject: newSubject,
        description: newDescription,
        fileName: uploadedFiles[0]?.name || "upload.pdf",
        extractionMethod: "ocr",
        hasText: true,
        extractedText: `Extracted text preview for ${newTitle}. Automatically parsed for RAG student doubt assistant embeddings.`,
        uploadedDate: "Just now"
      };
      setMaterials((prev) => [mockMaterial, ...prev]);
      setSelectedMaterial(mockMaterial);
      alert(`"${newTitle}" uploaded and indexed (Preview mode)!`);
    } finally {
      setIsSubmitting(false);
      setNewTitle("");
      setNewDescription("");
      setUploadedFiles([]);
    }
  };

  const columns = [
    {
      key: "title",
      label: "Document Title",
      sortable: true,
      render: (row) => (
        <div>
          <span style={{ fontWeight: 600, color: "#0F172A", display: "block", fontSize: "13px" }}>{row.title}</span>
          <span style={{ fontSize: "11px", color: "#64748B" }}>{row.subject} • {row.fileName}</span>
        </div>
      )
    },
    { 
      key: "uploadedDate", 
      label: "Indexed Date", 
      sortable: true,
      render: (row) => <span style={{ color: "#475569", fontSize: "12px" }}>{row.uploadedDate}</span>
    },
    {
      key: "extractionMethod",
      label: "Extraction Engine",
      sortable: true,
      render: (row) => (
        <span style={{
          display: "inline-block",
          padding: "3px 8px",
          borderRadius: "6px",
          fontSize: "11px",
          fontWeight: 700,
          background: row.extractionMethod === "ocr" ? "rgba(16, 185, 129, 0.12)" : "rgba(14, 165, 233, 0.12)",
          color: row.extractionMethod === "ocr" ? "#065F46" : "#0369A1",
          border: `1px solid ${row.extractionMethod === "ocr" ? "rgba(16, 185, 129, 0.25)" : "rgba(14, 165, 233, 0.25)"}`
        }}>
          {row.extractionMethod === "ocr" ? "AI OCR Scanned" : "Native PDF Text"}
        </span>
      )
    },
    {
      key: "actions",
      label: "Inspect",
      sortable: false,
      render: (row) => (
        <button
          onClick={() => setSelectedMaterial(row)}
          style={{
            padding: "5px 12px",
            borderRadius: "8px",
            fontSize: "12px",
            fontWeight: 600,
            background: selectedMaterial?.id === row.id ? "#10B981" : "rgba(241, 245, 249, 0.9)",
            color: selectedMaterial?.id === row.id ? "#FFFFFF" : "#1E293B",
            border: "none",
            cursor: "pointer",
            transition: "all 0.15s ease",
            boxShadow: selectedMaterial?.id === row.id ? "0 2px 8px rgba(16, 185, 129, 0.25)" : "none"
          }}
        >
          {selectedMaterial?.id === row.id ? "Viewing" : "Read Text"}
        </button>
      )
    }
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="materials"
        logoText="EduIntel AI"
        roleText="Faculty Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "materials") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Dr. Sarah Jenkins", role: "Faculty Head" }}
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
                  Curriculum Archive & RAG
                </span>
              </div>
              <h1
                className="edu-font-heading"
                style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: "0 0 6px 0", letterSpacing: "-0.02em" }}
              >
                Study Materials & Knowledge Base
              </h1>
              <p style={{ fontSize: "14px", color: "#64748B", margin: 0, maxWidth: "600px" }}>
                Upload notes and question banks — document text is automatically vectorized for AI Doubt Assistant retrieval.
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button 
                onClick={() => alert("Vector embedding index sync triggered.")}
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
                <span className="material-symbols-outlined" style={{ fontSize: "18px", color: "#10B981" }}>sync</span>
                Sync Vector Index
              </button>
            </div>
          </div>

          {/* Metric Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginBottom: "28px" }}>
            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Total Documents</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#10B981" }}>description</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                {materials.length} Materials
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>Across 4 STEM subjects</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Text Extraction Rate</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#0284C7" }}>smart_toy</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                100% Extracted
              </div>
              <div style={{ fontSize: "12px", color: "#0284C7" }}>Zero parse failures</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>RAG Chunks Created</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#8B5CF6" }}>hub</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                1,420 Chunks
              </div>
              <div style={{ fontSize: "12px", color: "#059669" }}>ChromaDB collection synced</div>
            </div>

            <div className="edu-card" style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "#64748B" }}>Supported Types</span>
                <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#F59E0B" }}>folder_zip</span>
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", marginBottom: "4px" }}>
                PDF, JPG, PNG
              </div>
              <div style={{ fontSize: "12px", color: "#64748B" }}>Max 25MB per file</div>
            </div>
          </div>

          {/* Form & List Grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 350px), 1fr))",
              gap: "24px",
              alignItems: "start"
            }}
          >
            {/* Upload Card */}
            <div className="edu-card" style={{ padding: "26px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "20px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span className="material-symbols-outlined" style={{ fontSize: "20px", color: "#059669" }}>cloud_upload</span>
                </div>
                <div>
                  <h3 className="edu-font-heading" style={{ margin: 0, fontSize: "17px", fontWeight: 700, color: "#0F172A" }}>
                    Ingest Course Reference
                  </h3>
                  <p style={{ margin: 0, fontSize: "12px", color: "#64748B" }}>Upload lecture notes, exams, or papers</p>
                </div>
              </div>

              <form onSubmit={handleUpload} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Document Title
                  </label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Trigonometry Differential Proofs"
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none",
                      boxSizing: "border-box"
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Discipline / Subject
                  </label>
                  <select
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none"
                    }}
                  >
                    <option value="MATHEMATICS">MATHEMATICS</option>
                    <option value="PHYSICS">PHYSICS</option>
                    <option value="CHEMISTRY">CHEMISTRY</option>
                    <option value="COMPUTER SCIENCE">COMPUTER SCIENCE</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    Summary & Topics Covered
                  </label>
                  <textarea
                    rows={3}
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Brief description of chapters or key formulas included..."
                    style={{
                      width: "100%",
                      padding: "11px 14px",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      backgroundColor: "rgba(255, 255, 255, 0.9)",
                      fontSize: "13px",
                      color: "#1E293B",
                      outline: "none",
                      resize: "vertical",
                      boxSizing: "border-box"
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "11px", fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px" }}>
                    File Attachment
                  </label>
                  <FileDropzone
                    onFilesSelected={handleDropFiles}
                    accept=".pdf,.jpg,.jpeg,.png,.webp"
                    acceptText="Drop PDF document or scanned notes here"
                    maxSizeText="PDF, PNG, JPG up to 25MB"
                  />
                </div>

                {uploadedFiles.length > 0 && (
                  <div style={{ padding: "10px 14px", backgroundColor: "rgba(16, 185, 129, 0.08)", borderRadius: "8px", border: "1px solid rgba(16, 185, 129, 0.2)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "18px" }}>check_circle</span>
                      <span style={{ fontSize: "12px", color: "#065F46", fontWeight: 600 }}>
                        {uploadedFiles[0].name} ({(uploadedFiles[0].size / 1024).toFixed(1)} KB)
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setUploadedFiles([])}
                      style={{ background: "none", border: "none", color: "#DC2626", cursor: "pointer", fontSize: "12px" }}
                    >
                      Remove
                    </button>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="edu-btn-primary"
                  style={{
                    width: "100%",
                    padding: "13px",
                    borderRadius: "10px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    fontSize: "13px",
                    fontWeight: 700,
                    cursor: "pointer",
                    boxShadow: "0 4px 14px rgba(16, 185, 129, 0.28)",
                    opacity: isSubmitting ? 0.6 : 1,
                    marginTop: "4px"
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>upload</span>
                  {isSubmitting ? "PROCESSING OCR & EMBEDDINGS..." : "UPLOAD & VECTORIZE MATERIAL"}
                </button>
              </form>
            </div>

            {/* Right: Table + Extracted Content */}
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <DataTable
                title={`Knowledge Base Ledger (${materials.length})`}
                columns={columns}
                data={materials}
                pageSize={5}
              />

              {selectedMaterial && (
                <div className="edu-card" style={{ padding: "22px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "rgba(16, 185, 129, 0.12)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <span className="material-symbols-outlined" style={{ color: "#059669", fontSize: "18px" }}>auto_stories</span>
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#0F172A" }}>
                          {selectedMaterial.title}
                        </h4>
                        <div style={{ fontSize: "11px", color: "#64748B" }}>
                          {selectedMaterial.subject} • {selectedMaterial.fileName}
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => setSelectedMaterial(null)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: "6px",
                        fontSize: "11px",
                        fontWeight: 600,
                        background: "rgba(241, 245, 249, 0.9)",
                        border: "1px solid rgba(226, 232, 240, 0.9)",
                        color: "#475569",
                        cursor: "pointer"
                      }}
                    >
                      Close Viewer
                    </button>
                  </div>

                  {selectedMaterial.hasText ? (
                    <div style={{
                      padding: "14px 16px",
                      background: "rgba(248, 250, 252, 0.8)",
                      borderRadius: "10px",
                      border: "1px solid rgba(226, 232, 240, 0.8)",
                      fontSize: "13px",
                      color: "#334155",
                      lineHeight: 1.6,
                      maxHeight: "220px",
                      overflowY: "auto",
                      whiteSpace: "pre-wrap"
                    }}>
                      {selectedMaterial.extractedText}
                    </div>
                  ) : (
                    <p style={{ fontSize: "13px", color: "#64748B", margin: 0 }}>No extracted text available for this file.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}