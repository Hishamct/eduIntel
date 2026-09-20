import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sidebar, TopBar, DataTable, StatusBadge, Modal } from "../../components/ui";
import { logout } from "../../api/auth";
import apiClient from "../../api/client";

export default function FlaggedStudents() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [students, setStudents] = useState([]);
  const [isLoadingStudents, setIsLoadingStudents] = useState(true);

  const [selectedStudent, setSelectedStudent] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [diagnosis, setDiagnosis] = useState(null);
  const [isDiagnosing, setIsDiagnosing] = useState(false);
  const [diagnosisError, setDiagnosisError] = useState("");

  // recommendations keyed by "subject|topic" so each topic tracks its own loading/result independently
  const [recommendations, setRecommendations] = useState({});
  const [loadingTopicKey, setLoadingTopicKey] = useState(null);

  const [loadingWorksheetKey, setLoadingWorksheetKey] = useState(null);

  // SHAP explanation state — fetched on demand, separate from the initial diagnosis call
  const [explanation, setExplanation] = useState(null);
  const [isLoadingExplanation, setIsLoadingExplanation] = useState(false);
  const [explanationError, setExplanationError] = useState("");

  const navigate = useNavigate();

  useEffect(() => {
    apiClient
      .get("/teacher/students")
      .then((res) => setStudents(res.data))
      .catch((err) => console.error("Failed to load students:", err))
      .finally(() => setIsLoadingStudents(false));
  }, []);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") logout(navigate);
  };

  const handleViewRiskAssessment = async (student) => {
    setSelectedStudent(student);
    setIsModalOpen(true);
    setDiagnosis(null);
    setDiagnosisError("");
    setRecommendations({});
    setExplanation(null);
    setExplanationError("");
    setIsDiagnosing(true);

    try {
      const { data } = await apiClient.get(`/ml/diagnose/${student.id}`);
      setDiagnosis(data);
    } catch (err) {
      console.error("Diagnosis failed:", err);
      setDiagnosisError("Could not generate a risk assessment for this student. They may not have enough history yet.");
    } finally {
      setIsDiagnosing(false);
    }
  };

  const handleGetExplanation = async () => {
    if (!selectedStudent) return;
    setIsLoadingExplanation(true);
    setExplanationError("");
    try {
      const { data } = await apiClient.get(`/ml/explain/at-risk/${selectedStudent.id}`);
      setExplanation(data);
    } catch (err) {
      console.error("SHAP explanation failed:", err);
      setExplanationError("Could not generate an explanation for this student right now.");
    } finally {
      setIsLoadingExplanation(false);
    }
  };

  const handleGetRecommendation = async (subject, topic) => {
    const key = `${subject}|${topic}`;
    setLoadingTopicKey(key);
    try {
      const { data } = await apiClient.get("/ml/recommend-topic", {
        params: { subject, topic },
      });
      setRecommendations((prev) => ({ ...prev, [key]: data }));
    } catch (err) {
      console.error("Recommendation fetch failed:", err);
      setRecommendations((prev) => ({
        ...prev,
        [key]: { recommendation: "Could not fetch a recommendation right now. Please try again." },
      }));
    } finally {
      setLoadingTopicKey(null);
    }
  };

  const handleGenerateWorksheet = async (subject, topic) => {
    const key = `${subject}|${topic}`;
    setLoadingWorksheetKey(key);
    try {
      const response = await apiClient.get("/ml/generate-worksheet", {
        params: { subject, topic, student_name: selectedStudent?.name },
        responseType: "blob",
      });
      const blobUrl = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `${topic.replace(/\s+/g, "_")}_worksheet.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => window.URL.revokeObjectURL(blobUrl), 10000);
    } catch (err) {
      console.error("Worksheet generation failed:", err);
      alert("Could not generate the worksheet. Please try again.");
    } finally {
      setLoadingWorksheetKey(null);
    }
  };

  const columns = [
    {
      key: "name",
      label: "Student Name",
      sortable: true,
      render: (row) => (
        <div>
          <span style={{ fontWeight: 600, color: "#1B2330", display: "block" }}>{row.name || "Unnamed"}</span>
          <span style={{ fontSize: "11px", color: "#5F6774" }}>{row.email}</span>
        </div>
      ),
    },
    {
      key: "classSection",
      label: "Class / Section",
      sortable: true,
      render: (row) => `${row.grade || "-"}-${row.section || "-"}`,
    },
    { key: "roll_number", label: "Roll No.", sortable: true },
    {
      key: "actions",
      label: "Risk Assessment",
      sortable: false,
      render: (row) => (
        <div style={{ textAlign: "right" }}>
          <button
            onClick={() => handleViewRiskAssessment(row)}
            className="edu-btn-accent"
            style={{ padding: "6px 12px", fontSize: "11px" }}
          >
            View Risk Assessment
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="teacher"
        activeId="flagged"
        logoText="EduIntel AI"
        roleText="Teacher Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "flagged") navigate(`/teacher/${itemId}`);
        }}
      />

      <div className="edu-main-wrapper">
        <TopBar
          user={{ name: "Faculty Portal", role: "Educator" }}
          onProfileMenuSelect={handleProfileSelect}
        />

        <main className="edu-page-content">
          <div style={{ marginBottom: "24px" }}>
            <span
              style={{
                fontSize: "11px",
                fontWeight: 700,
                letterSpacing: "0.05em",
                color: "#5F6774",
                textTransform: "uppercase",
              }}
            >
              CLASSROOM INTELLIGENCE
            </span>
            <h2
              className="edu-font-heading"
              style={{ fontSize: "24px", fontWeight: 600, color: "#1B2330", margin: "4px 0 0 0" }}
            >
              Flagged Students
            </h2>
            <p style={{ fontSize: "14px", color: "#5F6774", margin: "4px 0 0 0" }}>
              Select a student to run an on-demand AI risk assessment based on their attendance, homework, and exam history.
            </p>
          </div>

          {isLoadingStudents ? (
            <p style={{ fontSize: "13px", color: "#5F6774" }}>Loading students...</p>
          ) : (
            <DataTable
              title="Students"
              columns={columns}
              data={students}
              pageSize={10}
            />
          )}
        </main>
      </div>

      {selectedStudent && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          title={`Risk Assessment: ${selectedStudent.name || selectedStudent.email}`}
          icon="analytics"
          iconVariant={diagnosis?.is_at_risk ? "danger" : "success"}
          primaryLabel="CLOSE"
          onPrimary={() => setIsModalOpen(false)}
          secondaryLabel=""
          footerNote={`STUDENT ID: ${selectedStudent.id}`}
          description={
            <div style={{ textAlign: "left" }}>
              {isDiagnosing && (
                <p style={{ fontSize: "13px", color: "#5F6774", fontStyle: "italic" }}>
                  Running risk assessment...
                </p>
              )}

              {diagnosisError && (
                <p style={{ fontSize: "13px", color: "#B23A2E" }}>{diagnosisError}</p>
              )}

              {diagnosis && (
                <>
                  <div style={{ marginBottom: "16px" }}>
                    <StatusBadge
                      variant={diagnosis.is_at_risk ? "flagged-at-risk" : "on-track"}
                      label={diagnosis.is_at_risk ? "AT RISK" : "NOT CURRENTLY AT RISK"}
                    />
                    {diagnosis.risk_probability !== null && (
                      <span style={{ fontSize: "12px", color: "#5F6774", marginLeft: "10px" }}>
                        Confidence: {(diagnosis.risk_probability * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>

                  {/* --- SHAP explainability: why did the model produce this score? --- */}
                  <div style={{ marginBottom: "16px" }}>
                    {!explanation && !isLoadingExplanation && (
                      <button
                        onClick={handleGetExplanation}
                        className="edu-btn-secondary"
                        style={{ padding: "6px 12px", fontSize: "11px" }}
                      >
                        Why is this student flagged?
                      </button>
                    )}

                    {isLoadingExplanation && (
                      <p style={{ fontSize: "12px", color: "#5F6774", fontStyle: "italic" }}>
                        Analyzing contributing factors...
                      </p>
                    )}

                    {explanationError && (
                      <p style={{ fontSize: "12px", color: "#B23A2E" }}>{explanationError}</p>
                    )}

                    {explanation && explanation.top_factors?.length > 0 && (
                      <div
                        style={{
                          border: "1px solid #E5E5E1",
                          borderRadius: "6px",
                          padding: "12px",
                          backgroundColor: "#FAFAF7",
                        }}
                      >
                        <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 8px 0" }}>
                          Why the Model Scored This Student This Way
                        </p>
                        <p style={{ fontSize: "12px", color: "#1B2330", margin: "0 0 12px 0", lineHeight: 1.5 }}>
                          {explanation.summary}
                        </p>

                        {explanation.top_factors.map((f) => {
                          const isIncreasing = f.direction === "increases_risk";
                          return (
                            <div
                              key={f.feature}
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                padding: "8px 10px",
                                borderLeft: `4px solid ${isIncreasing ? "#B23A2E" : "#2F7A52"}`,
                                backgroundColor: "#FFFFFF",
                                marginBottom: "6px",
                                fontSize: "12px",
                              }}
                            >
                              <div>
                                <span style={{ fontWeight: 600, color: "#1B2330" }}>{f.label}</span>
                                <span style={{ color: "#5F6774", marginLeft: "6px" }}>({f.value})</span>
                              </div>
                              <span style={{ fontWeight: 700, color: isIncreasing ? "#B23A2E" : "#2F7A52" }}>
                                {isIncreasing ? "↑ increases risk" : "↓ reduces risk"}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {explanation && explanation.top_factors?.length === 0 && (
                      <p style={{ fontSize: "12px", color: "#5F6774" }}>
                        {explanation.summary}
                      </p>
                    )}
                  </div>

                  {diagnosis.contributing_factors?.length > 0 && (
                    <div style={{ marginBottom: "16px" }}>
                      <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 8px 0" }}>
                        Academic / Attendance Factors
                      </p>
                      {diagnosis.contributing_factors.map((f, idx) => (
                        <div
                          key={idx}
                          style={{
                            padding: "10px 12px",
                            backgroundColor: "#FAFAF7",
                            borderLeft: "4px solid #B23A2E",
                            marginBottom: "6px",
                            fontSize: "13px",
                            color: "#1B2330",
                          }}
                        >
                          {f.detail}
                        </div>
                      ))}
                    </div>
                  )}

                  {diagnosis.broadly_weak_across_subjects && (
                    <p style={{ fontSize: "12px", color: "#D9922E", fontWeight: 600, marginBottom: "16px" }}>
                      This student shows weakness broadly across most subjects, not one isolated topic ({diagnosis.total_weak_topic_count} topics flagged).
                    </p>
                  )}

                  {diagnosis.top_weak_topics?.length > 0 && (
                    <div>
                      <p style={{ fontSize: "11px", fontWeight: 700, color: "#5F6774", textTransform: "uppercase", margin: "0 0 8px 0" }}>
                        Top Weak Topics
                      </p>
                      {diagnosis.top_weak_topics.map((wt) => {
                        const key = `${wt.subject}|${wt.topic}`;
                        const rec = recommendations[key];
                        const isLoadingRec = loadingTopicKey === key;
                        const isLoadingWorksheet = loadingWorksheetKey === key;

                        return (
                          <div
                            key={key}
                            style={{
                              border: "1px solid #E5E5E1",
                              borderRadius: "6px",
                              padding: "12px",
                              marginBottom: "10px",
                            }}
                          >
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                              <div>
                                <span style={{ fontWeight: 600, fontSize: "13px", color: "#1B2330" }}>{wt.topic}</span>
                                <span style={{ fontSize: "11px", color: "#5F6774", marginLeft: "6px" }}>({wt.subject})</span>
                              </div>
                              <div style={{ display: "flex", gap: "8px" }}>
                                {!rec && (
                                  <button
                                    onClick={() => handleGetRecommendation(wt.subject, wt.topic)}
                                    disabled={isLoadingRec}
                                    className="edu-btn-secondary"
                                    style={{ padding: "5px 10px", fontSize: "11px", opacity: isLoadingRec ? 0.6 : 1 }}
                                  >
                                    {isLoadingRec ? "Loading..." : "Get Study Recommendations"}
                                  </button>
                                )}
                                <button
                                  onClick={() => handleGenerateWorksheet(wt.subject, wt.topic)}
                                  disabled={isLoadingWorksheet}
                                  className="edu-btn-accent"
                                  style={{ padding: "5px 10px", fontSize: "11px", opacity: isLoadingWorksheet ? 0.6 : 1 }}
                                >
                                  {isLoadingWorksheet ? "Generating..." : "Generate Worksheet"}
                                </button>
                              </div>
                            </div>
                            {rec && (
                              <p style={{ fontSize: "12px", color: "#1B2330", marginTop: "8px", lineHeight: 1.5, whiteSpace: "pre-line" }}>
                                {rec.recommendation}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </div>
          }
        />
      )}
    </div>
  );
}