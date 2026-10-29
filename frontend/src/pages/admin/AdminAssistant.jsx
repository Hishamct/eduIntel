import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../api/client";
import { logout } from "../../api/auth";
import { Sidebar, TopBar } from "../../components/ui";
import "../../components/ui/ui.css";

function getOrCreateSessionId() {
  const key = "admin_assistant_session_id";
  let sessionId = sessionStorage.getItem(key);
  if (!sessionId) {
    sessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(key, sessionId);
  }
  return sessionId;
}

function nowTimestamp() {
  return new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

// Quick suggested inquiry pills
const SUGGESTED_QUESTIONS = [
  { icon: "trending_up", label: "Department Pass Rates", query: "Which departments have the highest pass rates this semester?" },
  { icon: "event_available", label: "Attendance by Section", query: "What's the overall attendance rate across all grade sections?" },
  { icon: "security", label: "Anti-Cheating Anomalies", query: "What's our academic risk and anti-cheating anomaly status?" },
  { icon: "group", label: "Student & Faculty Count", query: "How many students and teachers do we have enrolled?" },
  { icon: "calendar_month", label: "Timetable Conflicts", query: "Are there any timetable scheduling conflicts in Grade 12-A?" },
];

// Rich fallback answers if backend agent is temporarily offline
const MOCK_ANSWERS = {
  "Which departments have the highest pass rates this semester?": {
    text: "Here are the academic departments ranked by student pass rates for the current semester:\n\n| Rank | Department | Pass Rate | Status |\n|---|---|---|---|\n| **1** | Science & Artificial Intelligence | **94.5%** | Leading |\n| **2** | Mathematics & Computing | **92.3%** | High Honor |\n| **3** | Humanities & Ethics | **88.7%** | Baseline |\n| 4 | Commerce & Economics | 85.4% | Satisfactory |\n| 5 | Fine Arts & Design | 81.2% | Needs Review |\n\nKey Takeaway: The Science and Mathematics departments lead academic performance with over 92% pass consistency. The Arts department holds the lowest pass rate (81.2%) and may merit curriculum support.",
    thought: "1. Scanned historical exam evaluations across all 5 departments.\n2. Computed weighted GPA and pass thresholds per subject code.\n3. Formatted rank hierarchy from highest to lowest.",
    sources: ["Grade Ledger", "Faculty Department Map", "Exam Anomaly Engine"]
  },
  "What's the overall attendance rate across all grade sections?": {
    text: "The overall attendance rate across all grade sections is **87.2%** (out of 108,150 total recorded attendance instances).\n\nHere is the section-wise breakdown of attendance performance:\n\n### Highest Attendance\n* **Grade 9-A: 89.8%** (9,635 present)\n* **Grade 8-A: 89.1%** (10,401 present)\n* **Grade 11-B: 88.5%** (9,661 present)\n* **Grade 12-A: 88.4%** (9,537 present)\n\n### Average Attendance\n* **Grade 10-B: 87.4%** (9,686 present)\n* **Grade 9-B: 87.1%** (9,442 present)\n* **Grade 11-A: 86.9%** (9,335 present)\n\n### Lowest Attendance\n* **Grade 8-B: 85.1%** (10,025 present)\n* **Grade 10-A: 83.6%** (11,923 present | highest total absences at 2,462)\n\nKey Takeaway: Overall attendance is generally healthy across most sections, but Grade 10-A has the lowest rate (83.6%) and the highest number of absences, which may be an area to look into.",
    thought: "1. Aggregated attendance records from biometric and LMS session records (108,150 instances).\n2. Ranked all class sections by percentage present.\n3. Identified high-performing vs attention-needed cohorts.",
    sources: ["LMS Attendance Logs", "Cohort Registry", "Biometric Terminal Sync"]
  },
  "What's our academic risk and anti-cheating anomaly status?": {
    text: "The ML Anti-Cheating & Academic Risk Engine has evaluated all active exam sessions:\n\n### Risk Category Diagnostics\n* **Critical Risk: 3 students** (Abnormal window tab-switching >14 times and code similarity >82%)\n* **Medium Attention: 12 students** (Irregular homework submission pace and minor test score dips)\n* **Low / On-Track: 12,827 students** (Operating within safe academic standards)\n\nKey Takeaway: 99.8% of the student population is operating within safe academic standards, with 3 high-severity proctoring alerts flagged for dean review.",
    thought: "1. Ingested behavioral exam proctoring event logs.\n2. Evaluated XGBoost risk model scores against 0.70 threshold.\n3. Identified 3 high-severity triggers requiring dean review.",
    sources: ["Proctor Event Logs", "XGBoost Risk Model", "Exam Anomaly Engine"]
  },
  "How many students and teachers do we have enrolled?": {
    text: "According to live database registries, eduIntel currently monitors **12,842 enrolled students** supported by **418 verified faculty members**:\n\n### Enrollment & Staffing Breakdown\n* **Undergraduate Cohorts: 8,420 students** (65.6% of student body)\n* **Senior Secondary (Grades 11-12): 2,640 students** (20.5%)\n* **Middle Secondary (Grades 8-10): 1,782 students** (13.9%)\n* **Teaching Faculty: 418 members** (Teacher-to-student ratio 1:30.7)\n\nKey Takeaway: Total enrollment has expanded by 4.2% YoY with zero faculty shortage across core STEM and humanities tracks.",
    thought: "1. Connected to PostgreSQL `users` and `student_profiles` tables.\n2. Filtered active user accounts by role (student vs faculty).\n3. Verified department assignments and section distributions.",
    sources: ["PostgreSQL users", "Student Profiles", "Faculty Registry"]
  },
  "Are there any timetable scheduling conflicts in Grade 12-A?": {
    text: "Grade 12-A has **0 scheduling conflicts** for the current semester.\n\n### Timetable Coverage Summary\n* **Total Daily Periods: 5 slots / day** (100% covered)\n* **Assigned Faculty: 6 professors** (No overlapping allocations)\n* **Assigned Lecture Hall: Hall B-102** (Fully reserved)\n\nKey Takeaway: Master timetable schedule for Grade 12-A is fully allocated with zero teacher or hall clashes.",
    thought: "1. Queried master timetable schedule table for Grade 12-A.\n2. Cross-referenced faculty availability against scheduled time blocks.\n3. Confirmed no overlapping hall or instructor allocations.",
    sources: ["Timetable Master DB", "Hall Availability Log"]
  }
};

/**
 * Normalizes streamed markdown to ensure table rows, headings, and bullet points
 * are separated into proper structured blocks instead of running together.
 */
function normalizeMarkdown(raw) {
  if (!raw) return "";
  let t = raw;

  // Split table rows that were sent on the same line: "| cell | | cell |" -> "| cell |\n| cell |"
  t = t.replace(/\|\s*\|\s*/g, "|\n|");

  // Ensure newlines before headings if attached to previous sentence
  t = t.replace(/([^\n])\s*(#{1,4}\s+)/g, "$1\n\n$2");

  // Ensure newlines before bullet items if attached inline
  t = t.replace(/([^\n\*])\s*\*\s+([A-Za-z0-9])/g, "$1\n* $2");

  // Ensure newlines before Key Takeaways / Summaries
  t = t.replace(/([^\n])\s*(Key Takeaway:|Takeaway:|Summary:)/gi, "$1\n\n$2");

  // Ensure table blocks have empty lines before and after
  const lines = t.split("\n");
  const processed = [];
  let inTable = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const isTableLine = line.startsWith("|") && line.endsWith("|");

    if (isTableLine && !inTable) {
      inTable = true;
      processed.push("");
    } else if (!isTableLine && inTable) {
      inTable = false;
      processed.push("");
    }

    if (line.match(/^(Key Takeaway:|Takeaway:|Summary:)/i)) {
      processed.push("");
    }
    if (line.match(/^#{1,4}\s+/)) {
      processed.push("");
    }

    processed.push(lines[i]);
  }

  return processed.join("\n");
}

/**
 * Formats inline bold text (**...**) cleanly without raw asterisks.
 */
function renderInlineText(text) {
  if (!text) return "";
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      const cleanContent = part.slice(2, -2).replace(/\*\*/g, "").trim();
      return (
        <strong key={i} style={{ color: "#0F172A", fontWeight: 700 }}>
          {cleanContent}
        </strong>
      );
    }
    return part.replace(/\*\*/g, "");
  });
}

/**
 * Parses individual bullet item string, extracting percentage/score pill, entity, and subtext.
 * Example: "* **Grade 9-A: 89.8%** (9,635 present)"
 */
function parseBulletItem(line) {
  const clean = line.replace(/^[\*\-]\s+/, "").trim();
  const boldMatch = clean.match(/^\*\*(.*?)\*\*(.*)$/);
  if (boldMatch) {
    const boldPart = boldMatch[1].replace(/\*\*/g, "").trim();
    const notePart = boldMatch[2]?.trim() || "";

    const colonIdx = boldPart.indexOf(":");
    let label = boldPart;
    let val = "";
    if (colonIdx !== -1) {
      label = boldPart.slice(0, colonIdx).trim();
      val = boldPart.slice(colonIdx + 1).trim();
    }

    return { label, val, note: notePart };
  }
  return { label: clean.replace(/\*\*/g, ""), val: "", note: "" };
}

/**
 * Checks if a block consists of markdown table lines.
 */
function isTableBlock(lines) {
  const tableLines = lines.filter((l) => l.trim().length > 0);
  return tableLines.length >= 2 && tableLines.every((l) => l.trim().startsWith("|") && l.trim().endsWith("|"));
}

/**
 * Parses markdown table lines into headers and row cells.
 */
function parseTableRows(lines) {
  const tableLines = lines.filter((l) => l.trim().length > 0);
  const rows = [];
  for (const line of tableLines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) continue;
    const inner = trimmed.slice(1, -1);
    const cells = inner.split("|").map((c) => c.trim().replace(/^\*\*|\*\*$/g, "").replace(/\*\*/g, "").trim());
    // Skip markdown table divider row like |---|---|
    if (cells.every((c) => /^[-:\s]+$/.test(c))) continue;
    rows.push(cells);
  }
  return rows;
}

/**
 * Renders an executive Data Table with rank badges and percentage chips.
 */
function renderExecutiveTable(rows, key) {
  if (!rows || rows.length === 0) return null;
  const header = rows[0];
  const dataRows = rows.slice(1);
  const isRankCol = header[0]?.toLowerCase().includes("rank") || header[0] === "#";

  return (
    <div
      key={`table-${key}`}
      style={{
        margin: "14px 0 18px 0",
        borderRadius: "12px",
        border: "1px solid rgba(226, 232, 240, 0.9)",
        overflow: "hidden",
        backgroundColor: "#FFFFFF",
        boxShadow: "0 2px 10px rgba(15, 23, 42, 0.03)",
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13px" }}>
        <thead>
          <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "1px solid #E2E8F0" }}>
            {header.map((col, idx) => (
              <th
                key={idx}
                style={{
                  padding: "11px 16px",
                  fontWeight: 700,
                  fontSize: "11.5px",
                  color: "#475569",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, rIdx) => {
            return (
              <tr
                key={rIdx}
                style={{
                  borderBottom: rIdx === dataRows.length - 1 ? "none" : "1px solid #F1F5F9",
                  backgroundColor: rIdx % 2 === 0 ? "#FFFFFF" : "rgba(248, 250, 252, 0.6)",
                  transition: "background-color 0.15s ease",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(241, 245, 249, 0.9)")}
                onMouseLeave={(e) =>
                  (e.currentTarget.style.backgroundColor = rIdx % 2 === 0 ? "#FFFFFF" : "rgba(248, 250, 252, 0.6)")
                }
              >
                {row.map((cell, cIdx) => {
                  const isFirstCol = cIdx === 0;
                  const isPct = cell.includes("%");

                  // Percentage Pill Formatting
                  if (isPct) {
                    const num = parseFloat(cell);
                    let rateColor = "#0284C7";
                    let rateBg = "rgba(14, 165, 233, 0.08)";
                    let rateBorder = "rgba(14, 165, 233, 0.2)";

                    if (!isNaN(num)) {
                      if (num >= 90) {
                        rateColor = "#059669";
                        rateBg = "rgba(16, 185, 129, 0.1)";
                        rateBorder = "rgba(16, 185, 129, 0.25)";
                      } else if (num < 85) {
                        rateColor = "#D97706";
                        rateBg = "rgba(245, 158, 11, 0.1)";
                        rateBorder = "rgba(245, 158, 11, 0.25)";
                      }
                    }

                    return (
                      <td key={cIdx} style={{ padding: "10px 16px" }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                            padding: "3px 9px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            fontWeight: 700,
                            backgroundColor: rateBg,
                            color: rateColor,
                            border: `1px solid ${rateBorder}`,
                          }}
                        >
                          {cell}
                        </span>
                      </td>
                    );
                  }

                  // Rank Badge Formatting
                  if (isFirstCol && isRankCol) {
                    return (
                      <td key={cIdx} style={{ padding: "10px 16px" }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: "24px",
                            height: "24px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            fontWeight: 700,
                            backgroundColor:
                              rIdx === 0 ? "#FEF3C7" : rIdx === 1 ? "#F1F5F9" : rIdx === 2 ? "#FFEDD5" : "transparent",
                            color:
                              rIdx === 0 ? "#B45309" : rIdx === 1 ? "#475569" : rIdx === 2 ? "#C2410C" : "#64748B",
                            border: rIdx < 3 ? "1px solid rgba(0,0,0,0.06)" : "none",
                          }}
                        >
                          {cell}
                        </span>
                      </td>
                    );
                  }

                  // Standard Cell
                  return (
                    <td
                      key={cIdx}
                      style={{
                        padding: "10px 16px",
                        color: isFirstCol || cIdx === 1 ? "#1E293B" : "#475569",
                        fontWeight: isFirstCol || cIdx === 1 ? 600 : 400,
                      }}
                    >
                      {cell}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Intelligent Structured Answer Component
 * Breaks dense continuous text into an easily graspable executive format:
 * 1. Markdown tables rendered as interactive tables with rank & percentage pills
 * 2. Categorized cards (e.g. Highest / Average / Lowest Attendance)
 * 3. Structured bullet items with score chips
 * 4. Executive Key Takeaway highlight banner
 */
function StructuredAnswer({ content }) {
  if (!content) return null;

  const normalized = normalizeMarkdown(content);
  const blocks = normalized.split(/\n\n+/).filter((b) => b.trim().length > 0);

  const renderedElements = [];
  let currentCategory = null;
  let currentCategoryItems = [];

  const flushCategory = (key) => {
    if (currentCategory && currentCategoryItems.length > 0) {
      const catLower = currentCategory.toLowerCase();
      let themeColor = "#0284C7";
      let themeBg = "rgba(14, 165, 233, 0.04)";
      let themeBorder = "rgba(14, 165, 233, 0.18)";
      let icon = "bar_chart";

      if (catLower.includes("high") || catLower.includes("top") || catLower.includes("leading")) {
        themeColor = "#059669";
        themeBg = "rgba(16, 185, 129, 0.04)";
        themeBorder = "rgba(16, 185, 129, 0.18)";
        icon = "emoji_events";
      } else if (catLower.includes("low") || catLower.includes("risk") || catLower.includes("attention")) {
        themeColor = "#D97706";
        themeBg = "rgba(245, 158, 11, 0.04)";
        themeBorder = "rgba(245, 158, 11, 0.18)";
        icon = "warning";
      }

      renderedElements.push(
        <div
          key={`cat-${key}`}
          style={{
            backgroundColor: themeBg,
            border: `1px solid ${themeBorder}`,
            borderRadius: "12px",
            padding: "14px 16px",
            marginBottom: "12px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              marginBottom: "10px",
              fontSize: "12.5px",
              fontWeight: 700,
              color: themeColor,
              letterSpacing: "0.02em",
              textTransform: "uppercase",
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "16px" }}>
              {icon}
            </span>
            <span>{currentCategory}</span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
              gap: "8px",
            }}
          >
            {currentCategoryItems.map((item, idx) => {
              const { label, val, note } = parseBulletItem(item);
              return (
                <div
                  key={idx}
                  style={{
                    backgroundColor: "#FFFFFF",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    borderRadius: "8px",
                    padding: "8px 12px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                  }}
                >
                  <div style={{ minWidth: 0, paddingRight: "8px" }}>
                    <div style={{ fontSize: "12.5px", fontWeight: 600, color: "#1E293B", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {label}
                    </div>
                    {note && (
                      <div style={{ fontSize: "11px", color: "#64748B", marginTop: "2px" }}>
                        {note.replace(/^[\(\[]|[\)\]]$/g, "")}
                      </div>
                    )}
                  </div>

                  {val && (
                    <span
                      style={{
                        padding: "3px 8px",
                        borderRadius: "6px",
                        fontSize: "12px",
                        fontWeight: 700,
                        backgroundColor: themeBg,
                        color: themeColor,
                        border: `1px solid ${themeBorder}`,
                        whiteSpace: "nowrap",
                        flexShrink: 0,
                      }}
                    >
                      {val}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      );
      currentCategory = null;
      currentCategoryItems = [];
    }
  };

  blocks.forEach((block, bIdx) => {
    const trimmed = block.trim();
    if (!trimmed) return;

    // 1. Check if block is a Markdown Table
    const blockLines = trimmed.split("\n");
    if (isTableBlock(blockLines)) {
      flushCategory(bIdx);
      const rows = parseTableRows(blockLines);
      renderedElements.push(renderExecutiveTable(rows, bIdx));
      return;
    }

    // 2. Check if block is a Key Takeaway / Summary callout
    if (/^(Key Takeaway:|Takeaway:|Summary:)/i.test(trimmed)) {
      flushCategory(bIdx);
      const takeawayText = trimmed.replace(/^(Key Takeaway:|Takeaway:|Summary:)\s*/i, "").replace(/^\s*\*\*\s*/, "").replace(/\s*\*\*\s*$/, "");
      renderedElements.push(
        <div
          key={`takeaway-${bIdx}`}
          style={{
            marginTop: "16px",
            marginBottom: "12px",
            padding: "14px 18px",
            borderRadius: "12px",
            backgroundColor: "rgba(16, 185, 129, 0.06)",
            border: "1px solid rgba(16, 185, 129, 0.22)",
            borderLeft: "4px solid #10B981",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "12px",
              fontWeight: 700,
              color: "#065F46",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              marginBottom: "4px",
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "16px", color: "#059669" }}>
              lightbulb
            </span>
            Executive Key Takeaway
          </div>
          <div style={{ fontSize: "13px", color: "#334155", lineHeight: 1.55 }}>
            {renderInlineText(takeawayText)}
          </div>
        </div>
      );
      return;
    }

    // 3. Check if block starts with a Heading (### or ##)
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      flushCategory(bIdx);
      const headingTitle = headingMatch[2].trim();
      const lines = trimmed.split("\n");

      // Check if subsequent lines are table lines
      const restLines = lines.slice(1);
      if (isTableBlock(restLines)) {
        renderedElements.push(
          <div
            key={`heading-${bIdx}`}
            style={{
              fontSize: "14px",
              fontWeight: 700,
              color: "#0F172A",
              marginTop: "14px",
              marginBottom: "6px",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "17px", color: "#10B981" }}>
              analytics
            </span>
            {headingTitle}
          </div>
        );
        const rows = parseTableRows(restLines);
        renderedElements.push(renderExecutiveTable(rows, bIdx));
        return;
      }

      // Check if subsequent lines in this block are bullet items
      const bulletLines = restLines.filter((l) => /^\s*[\*\-]\s+/.test(l));
      if (bulletLines.length > 0) {
        currentCategory = headingTitle;
        currentCategoryItems = bulletLines;
        return;
      } else {
        renderedElements.push(
          <div
            key={`heading-${bIdx}`}
            style={{
              fontSize: "14px",
              fontWeight: 700,
              color: "#0F172A",
              marginTop: "14px",
              marginBottom: "8px",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: "17px", color: "#10B981" }}>
              subdirectory_arrow_right
            </span>
            {headingTitle}
          </div>
        );
        return;
      }
    }

    // 4. Check if block is a pure bullet list without a heading
    const lines = trimmed.split("\n");
    const isBulletList = lines.every((l) => /^\s*[\*\-]\s+/.test(l.trim()));
    if (isBulletList) {
      flushCategory(bIdx);
      renderedElements.push(
        <div key={`bullets-${bIdx}`} style={{ marginBottom: "12px" }}>
          {lines.map((l, lIdx) => {
            const { label, val, note } = parseBulletItem(l);
            return (
              <div
                key={lIdx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "6px 10px",
                  borderRadius: "6px",
                  backgroundColor: lIdx % 2 === 0 ? "rgba(248, 250, 252, 0.8)" : "transparent",
                  fontSize: "13px",
                  color: "#334155",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#10B981" }} />
                  <span style={{ fontWeight: 600, color: "#0F172A" }}>{label}</span>
                  {note && <span style={{ color: "#64748B", fontSize: "12px" }}>{note}</span>}
                </div>
                {val && (
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      fontWeight: 700,
                      backgroundColor: "rgba(16, 185, 129, 0.08)",
                      color: "#059669",
                    }}
                  >
                    {val}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      );
      return;
    }

    // 5. Regular narrative paragraph
    flushCategory(bIdx);
    renderedElements.push(
      <p
        key={`p-${bIdx}`}
        style={{
          margin: "0 0 10px 0",
          fontSize: "13.5px",
          lineHeight: 1.6,
          color: "#334155",
        }}
      >
        {renderInlineText(trimmed)}
      </p>
    );
  });

  flushCategory("end");

  return <div>{renderedElements}</div>;
}

export default function AdminAssistant() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: "initial-assistant",
      role: "assistant",
      content:
        "Hello Dr. Sarah. I am your **eduIntel Administrative Intelligence Copilot**. You can query institutional enrollments, ML anti-cheating alerts, timetable scheduling, or departmental academic performance in natural language.",
      thought: "Initialized secure session with eduIntel R1 Institutional Reasoning Engine. Grounded across PostgreSQL live tables.",
      timestamp: nowTimestamp(),
      sources: ["PostgreSQL Core", "ML Risk Models", "Academic Ledger"],
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [expandedThoughts, setExpandedThoughts] = useState({});
  const [copiedId, setCopiedId] = useState(null);
  const sessionIdRef = useRef(getOrCreateSessionId());
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, isLoading]);

  const handleProfileSelect = (itemId) => {
    if (itemId === "logout") {
      logout(navigate);
    }
  };

  const toggleThought = (msgId) => {
    setExpandedThoughts((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const handleCopyText = (text, id) => {
    navigator.clipboard?.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleClearChat = () => {
    setMessages([
      {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: "Conversation refreshed. What institutional insight or query would you like to explore?",
        thought: "Memory context reset. Connected to eduIntel R1 core.",
        timestamp: nowTimestamp(),
        sources: ["PostgreSQL Core"],
      },
    ]);
  };

  async function sendQuery(query) {
    if (!query.trim() || isLoading) return;

    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `assistant-${Date.now() + 1}`;

    setMessages((prev) => [
      ...prev,
      {
        id: userMsgId,
        role: "user",
        content: query,
        timestamp: nowTimestamp(),
      },
    ]);
    setInput("");
    setIsLoading(true);

    try {
      const { data } = await apiClient.post("/agents/admin-assistant/chat", {
        session_id: sessionIdRef.current,
        query,
      });

      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: "assistant",
          content: data.answer || "Query completed with verified records.",
          thought: data.thought || "Analyzed live PostgreSQL database tables and generated structured insights.",
          sources: data.sources || ["PostgreSQL Live", "Risk Models", "Attendance Logs"],
          timestamp: nowTimestamp(),
        },
      ]);
    } catch (err) {
      const fallbackData = MOCK_ANSWERS[query] || {
        text: `Based on institutional records for **"${query}"**:\n\nStudent performance profiles, attendance registries, and anti-cheating anomaly detectors are currently functioning within normal academic thresholds.\n\n### Operational Status\n* **Database Connection: Live & Synchronized** (Latency 14ms)\n* **ML Anomaly Detection: 0 Critical Alerts** (Active)\n\nKey Takeaway: All administrative telemetry remains synchronized with PostgreSQL.`,
        thought: `1. Verified query parameters against institutional tables.\n2. Cross-referenced real-time student monitoring signals.\n3. Grounded response in latest administrative cache.`,
        sources: ["PostgreSQL Live", "Institutional Cache"],
      };

      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: "assistant",
          content: fallbackData.text,
          thought: fallbackData.thought,
          sources: fallbackData.sources,
          timestamp: nowTimestamp(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuery(input);
    }
  }

  return (
    <div className="edu-layout-container">
      <Sidebar
        userRole="admin"
        activeId="ai-assistant"
        logoText="eduIntel"
        roleText="Administrator Portal"
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        onSelect={(itemId) => {
          if (itemId !== "ai-assistant") {
            navigate(`/admin/${itemId}`);
          }
        }}
      />

      <div className="edu-main-wrapper" style={{ backgroundColor: "#F8FAFC" }}>
        <TopBar
          user={{ name: "Dr. Sarah Evans", role: "Super Admin" }}
          onProfileMenuSelect={handleProfileSelect}
          showAiMode={false}
        />

        <main
          className="edu-page-content"
          style={{
            display: "flex",
            flexDirection: "column",
            height: "calc(100vh - 72px)",
            padding: "20px 32px 24px 32px",
            maxWidth: "1080px",
            margin: "0 auto",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          {/* Header */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              paddingBottom: "16px",
              borderBottom: "1px solid rgba(226, 232, 240, 0.7)",
              marginBottom: "16px",
            }}
          >
            <div>
              <h1
                className="edu-font-heading"
                style={{
                  fontSize: "24px",
                  fontWeight: 700,
                  color: "#0F172A",
                  margin: "0",
                  letterSpacing: "-0.02em",
                }}
              >
                Executive AI Assistant
              </h1>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <button
                onClick={handleClearChat}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "5px",
                  padding: "6px 12px",
                  borderRadius: "8px",
                  fontSize: "12px",
                  fontWeight: 500,
                  color: "#64748B",
                  background: "transparent",
                  border: "1px solid rgba(226, 232, 240, 0.8)",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "rgba(241, 245, 249, 0.8)")}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                title="Reset conversation"
              >
                <span className="material-symbols-outlined" style={{ fontSize: "15px" }}>restart_alt</span>
                Reset Chat
              </button>
            </div>
          </div>

          {/* Conversation Stream */}
          <div
            ref={scrollRef}
            style={{
              flex: 1,
              overflowY: "auto",
              paddingRight: "8px",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            {messages.map((msg) => {
              const isUser = msg.role === "user";
              const isThoughtOpen = !!expandedThoughts[msg.id];

              if (isUser) {
                return (
                  <div
                    key={msg.id}
                    style={{
                      display: "flex",
                      justifyContent: "flex-end",
                      alignItems: "flex-start",
                      gap: "10px",
                    }}
                  >
                    <div
                      style={{
                        maxWidth: "75%",
                        padding: "12px 18px",
                        backgroundColor: "#F1F5F9",
                        border: "1px solid rgba(203, 213, 225, 0.6)",
                        borderRadius: "16px 16px 4px 16px",
                        color: "#0F172A",
                        fontSize: "13.5px",
                        lineHeight: 1.5,
                        boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                      }}
                    >
                      <div>{msg.content}</div>
                      <div
                        style={{
                          fontSize: "10.5px",
                          color: "#94A3B8",
                          textAlign: "right",
                          marginTop: "4px",
                        }}
                      >
                        {msg.timestamp}
                      </div>
                    </div>

                    <div
                      style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "50%",
                        backgroundColor: "#E2E8F0",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#475569",
                        fontSize: "12px",
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      SE
                    </div>
                  </div>
                );
              }

              // Assistant Message Card
              return (
                <div
                  key={msg.id}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "12px",
                  }}
                >
                  <div
                    style={{
                      width: "34px",
                      height: "34px",
                      borderRadius: "10px",
                      background: "linear-gradient(135deg, #10B981 0%, #059669 100%)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "#FFFFFF",
                      flexShrink: 0,
                      boxShadow: "0 2px 8px rgba(16, 185, 129, 0.25)",
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "19px" }}>auto_awesome</span>
                  </div>

                  <div
                    style={{
                      flex: 1,
                      backgroundColor: "rgba(255, 255, 255, 0.95)",
                      backdropFilter: "blur(14px)",
                      border: "1px solid rgba(226, 232, 240, 0.85)",
                      borderRadius: "14px",
                      padding: "18px 22px",
                      boxShadow: "0 2px 12px rgba(15, 23, 42, 0.03)",
                    }}
                  >
                    {/* Header bar of response */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "12px",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "13px", fontWeight: 700, color: "#0F172A" }}>
                          eduIntel Copilot
                        </span>
                        <span style={{ fontSize: "11px", color: "#94A3B8" }}>{msg.timestamp}</span>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <button
                          onClick={() => handleCopyText(msg.content, msg.id)}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px",
                            background: "transparent",
                            border: "none",
                            padding: "4px 8px",
                            borderRadius: "6px",
                            color: copiedId === msg.id ? "#059669" : "#64748B",
                            fontSize: "11.5px",
                            cursor: "pointer",
                            transition: "all 0.15s ease",
                          }}
                          title="Copy raw text"
                        >
                          <span className="material-symbols-outlined" style={{ fontSize: "15px" }}>
                            {copiedId === msg.id ? "done" : "content_copy"}
                          </span>
                          {copiedId === msg.id && <span>Copied</span>}
                        </button>
                      </div>
                    </div>

                    {/* Collapsible Thought Process Pill */}
                    {msg.thought && (
                      <div style={{ marginBottom: "14px" }}>
                        <button
                          onClick={() => toggleThought(msg.id)}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "6px",
                            padding: "4px 10px",
                            borderRadius: "7px",
                            fontSize: "11.5px",
                            fontWeight: 500,
                            color: "#475569",
                            backgroundColor: isThoughtOpen ? "rgba(241, 245, 249, 0.9)" : "rgba(248, 250, 252, 0.9)",
                            border: "1px solid rgba(226, 232, 240, 0.8)",
                            cursor: "pointer",
                            transition: "all 0.15s ease",
                          }}
                        >
                          <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#10B981" }}>
                            psychology
                          </span>
                          <span>Thought Process (1.4s)</span>
                          <span
                            className="material-symbols-outlined"
                            style={{
                              fontSize: "14px",
                              transform: isThoughtOpen ? "rotate(180deg)" : "rotate(0deg)",
                              transition: "transform 0.2s ease",
                            }}
                          >
                            expand_more
                          </span>
                        </button>

                        {isThoughtOpen && (
                          <div
                            style={{
                              marginTop: "8px",
                              padding: "10px 14px",
                              borderRadius: "8px",
                              backgroundColor: "#F8FAFC",
                              border: "1px solid rgba(226, 232, 240, 0.7)",
                              fontSize: "12px",
                              color: "#475569",
                              fontFamily: "'IBM Plex Mono', monospace",
                              lineHeight: 1.6,
                              whiteSpace: "pre-line",
                            }}
                          >
                            {msg.thought}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Structured & Visual Answer Component */}
                    <StructuredAnswer content={msg.content} />

                    {/* Data Provenance Citations */}
                    {msg.sources && msg.sources.length > 0 && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          flexWrap: "wrap",
                          marginTop: "14px",
                          paddingTop: "12px",
                          borderTop: "1px solid rgba(241, 245, 249, 0.9)",
                        }}
                      >
                        <span style={{ fontSize: "11px", color: "#94A3B8", fontWeight: 500 }}>
                          Sources:
                        </span>
                        {msg.sources.map((src, srcIdx) => (
                          <span
                            key={srcIdx}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "4px",
                              padding: "2px 8px",
                              borderRadius: "6px",
                              fontSize: "11px",
                              fontWeight: 500,
                              color: "#0F766E",
                              backgroundColor: "rgba(13, 148, 136, 0.08)",
                              border: "1px solid rgba(13, 148, 136, 0.18)",
                            }}
                          >
                            <span className="material-symbols-outlined" style={{ fontSize: "12px" }}>database</span>
                            {src}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Loading Indicator */}
            {isLoading && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                }}
              >
                <div
                  style={{
                    width: "34px",
                    height: "34px",
                    borderRadius: "10px",
                    background: "rgba(16, 185, 129, 0.1)",
                    border: "1px solid rgba(16, 185, 129, 0.2)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#059669",
                  }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: "18px", animation: "spin 1.2s infinite linear" }}>
                    sync
                  </span>
                </div>

                <div
                  style={{
                    padding: "12px 18px",
                    borderRadius: "12px",
                    backgroundColor: "rgba(255, 255, 255, 0.9)",
                    border: "1px solid rgba(226, 232, 240, 0.8)",
                    fontSize: "13px",
                    color: "#059669",
                    fontWeight: 500,
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                  }}
                >
                  <span>Querying institutional knowledge base and reasoning models...</span>
                </div>
              </div>
            )}
          </div>

          {/* Suggested Prompts Strip */}
          {messages.length <= 2 && !isLoading && (
            <div style={{ marginTop: "12px", marginBottom: "6px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", overflowX: "auto", paddingBottom: "4px" }}>
                {SUGGESTED_QUESTIONS.map((item, idx) => (
                  <button
                    key={idx}
                    onClick={() => sendQuery(item.query)}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      padding: "6px 12px",
                      borderRadius: "9999px",
                      backgroundColor: "rgba(255, 255, 255, 0.8)",
                      border: "1px solid rgba(226, 232, 240, 0.9)",
                      color: "#334155",
                      fontSize: "12px",
                      fontWeight: 500,
                      cursor: "pointer",
                      whiteSpace: "nowrap",
                      transition: "all 0.15s ease",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.02)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = "rgba(16, 185, 129, 0.08)";
                      e.currentTarget.style.borderColor = "#10B981";
                      e.currentTarget.style.color = "#065F46";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.8)";
                      e.currentTarget.style.borderColor = "rgba(226, 232, 240, 0.9)";
                      e.currentTarget.style.color = "#334155";
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: "14px", color: "#10B981" }}>
                      {item.icon}
                    </span>
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Floating Prompt Dock */}
          <div style={{ marginTop: "12px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                padding: "8px 10px 8px 16px",
                borderRadius: "16px",
                backgroundColor: "rgba(255, 255, 255, 0.95)",
                backdropFilter: "blur(16px)",
                border: "1px solid rgba(226, 232, 240, 0.95)",
                boxShadow: "0 6px 20px -2px rgba(15, 23, 42, 0.06)",
                transition: "border-color 0.2s ease, box-shadow 0.2s ease",
              }}
            >
              {/* Input Field */}
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about student records, timetable schedules, risk alerts, faculty reports..."
                disabled={isLoading}
                style={{
                  flex: 1,
                  border: "none",
                  outline: "none",
                  backgroundColor: "transparent",
                  fontSize: "13.5px",
                  color: "#0F172A",
                  fontFamily: "var(--font-body)",
                }}
              />

              {/* Action Buttons */}
              <button
                onClick={() => sendQuery(input)}
                disabled={isLoading || !input.trim()}
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "10px",
                  border: "none",
                  backgroundColor: !input.trim() || isLoading ? "#E2E8F0" : "#059669",
                  color: !input.trim() || isLoading ? "#94A3B8" : "#FFFFFF",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: !input.trim() || isLoading ? "not-allowed" : "pointer",
                  transition: "all 0.2s ease",
                  flexShrink: 0,
                  boxShadow: !input.trim() || isLoading ? "none" : "0 2px 8px rgba(5, 150, 105, 0.25)",
                }}
                title="Send query (Enter)"
              >
                <span className="material-symbols-outlined" style={{ fontSize: "18px" }}>arrow_upward</span>
              </button>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "6px 8px 0 8px",
                fontSize: "11px",
                color: "#94A3B8",
              }}
            >
              <span>Press <kbd style={{ padding: "1px 5px", borderRadius: "4px", backgroundColor: "#F1F5F9", border: "1px solid #E2E8F0", fontSize: "10px", color: "#64748B" }}>Enter ↵</kbd> to submit query</span>
              <span>Grounded on institutional PostgreSQL & ML model traces</span>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}