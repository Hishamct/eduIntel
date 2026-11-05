import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TeacherDashboard from "../src/pages/teacher/TeacherDashboard";
import AssignmentsGrading from "../src/pages/teacher/AssignmentsGrading";
import apiClient from "../src/api/client";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("Teacher Portal Views & Grading Workflow", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    mockNavigate.mockReset();
    vi.restoreAllMocks();
    window.alert = vi.fn();
  });

  describe("TeacherDashboard Component", () => {
    it("renders faculty overview, loads dashboard metrics, and handles quick actions", async () => {
      vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
        if (url === "/teacher/dashboard") {
          return {
            data: {
              message: "Welcome, Dr. Jenkins!",
              students_assigned: 82,
              pending_grading: 19,
              avg_attendance: 94.5,
              flagged_count: 5,
            },
          };
        }
        return { data: {} };
      });

      render(
        <MemoryRouter>
          <TeacherDashboard />
        </MemoryRouter>
      );

      // Verify portal branding and heading
      expect(screen.getByText(/Faculty Intelligence/i)).toBeTruthy();
      expect(screen.getByText(/Classroom Overview & Student Metrics/i)).toBeTruthy();

      // Verify KPI metrics after API resolution
      await waitFor(() => {
        expect(screen.getByText("82 Students")).toBeTruthy();
        expect(screen.getByText("19 Items")).toBeTruthy();
        expect(screen.getByText("94.5%")).toBeTruthy();
        expect(screen.getByText("5 Flagged")).toBeTruthy();
      });

      // Verify quick action button navigation
      const gradeBtn = screen.getByText(/Grade Submissions \(19\)/i);
      fireEvent.click(gradeBtn);
      expect(mockNavigate).toHaveBeenCalledWith("/teacher/grading");

      const uploadBtn = screen.getByText(/Upload Material/i);
      fireEvent.click(uploadBtn);
      expect(mockNavigate).toHaveBeenCalledWith("/teacher/materials");
    });
  });

  describe("AssignmentsGrading Component", () => {
    it("renders workbench, submits new assignment, selects submission, and evaluates student submission", async () => {
      const mockPost = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { success: true } });
      const mockPatch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: { success: true } });
      vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
        if (url === "/teacher/homework") {
          return {
            data: [
              {
                id: "sub-201",
                student_email: "priya.sharma@eduintel.ac.in",
                student_id: "STU-2026-099",
                title: "Calculus Optimization Lab",
                subject: "MATHEMATICS",
                description: "All critical points calculated.",
                max_score: 100,
                score: null,
                feedback: null,
                status: "pending",
                extracted_text: "f'(x) = 3x^2 - 12 = 0 => x = +/- 2. Second derivative test confirms minimum at x = 2.",
                ocr_confidence: 0.98,
              },
            ],
          };
        }
        if (url === "/teacher/assignments") {
          return {
            data: [
              {
                id: "a-101",
                title: "Thermodynamics Lab Report",
                subject: "PHYSICS",
                class_section: "Grade 11-A",
                due_date: "2026-10-15",
              },
            ],
          };
        }
        return { data: {} };
      });

      render(
        <MemoryRouter>
          <AssignmentsGrading />
        </MemoryRouter>
      );

      // Verify heading and subheader
      expect(screen.getByText(/Academic Evaluation/i)).toBeTruthy();
      expect(screen.getByText(/Assignments & Grading Workbench/i)).toBeTruthy();

      // Verify assignment publishing form
      const titleInput = screen.getByPlaceholderText(/e\.g\. Mid-Term Analytical Calculus Essay/i);
      fireEvent.change(titleInput, { target: { value: "Linear Algebra Vectors Problem Set" } });

      const cohortSelect = screen.getByDisplayValue("Grade 12-A");
      fireEvent.change(cohortSelect, { target: { value: "Grade 11-A" } });

      const publishBtn = screen.getByText("PUBLISH ASSIGNMENT");
      fireEvent.click(publishBtn);

      await waitFor(() => {
        expect(mockPost).toHaveBeenCalledWith(
          "/teacher/assignments",
          expect.objectContaining({
            title: "Linear Algebra Vectors Problem Set",
            class_section: "Grade 11-A",
            subject: "MATHEMATICS",
            max_score: 100,
          })
        );
        expect(window.alert).toHaveBeenCalledWith(
          expect.stringContaining("Linear Algebra Vectors Problem Set")
        );
      });

      // Verify submission loaded into table and select it
      await waitFor(() => {
        expect(screen.getByText(/priya\.sharma@eduintel\.ac\.in/i)).toBeTruthy();
      });

      const evaluateBtn = screen.getByRole("button", { name: /^Evaluate$/i });
      fireEvent.click(evaluateBtn);

      // Verify that selecting the submission switched inspection to priya.sharma
      await waitFor(() => {
        expect(screen.getByText("Grading: priya.sharma@eduintel.ac.in")).toBeTruthy();
      });

      // Find the score input inside the grading card
      const scoreInput = screen.getByPlaceholderText("0");
      fireEvent.change(scoreInput, { target: { value: "96" } });

      const feedbackInput = screen.getByPlaceholderText(
        /Provide qualitative assessment, rubric observations, or revision notes\.\.\./i
      );
      fireEvent.change(feedbackInput, {
        target: { value: "Exemplary critical point derivations and step clarity." },
      });

      const saveGradesBtn = screen.getByText(/SAVE GRADES/i);
      fireEvent.click(saveGradesBtn);

      await waitFor(() => {
        expect(mockPatch).toHaveBeenCalledWith(
          "/teacher/homework/sub-201/grade",
          expect.objectContaining({
            score: 96,
            max_score: 100,
            feedback: "Exemplary critical point derivations and step clarity.",
          })
        );
        expect(window.alert).toHaveBeenCalledWith(
          expect.stringContaining("priya.sharma@eduintel.ac.in")
        );
      });
    });
  });
});
