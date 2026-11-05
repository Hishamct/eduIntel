import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import StudentDashboard from "../src/pages/student/StudentDashboard";
import HomeworkUpload from "../src/pages/student/HomeworkUpload";
import apiClient from "../src/api/client";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("Student Academic Portal Views", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    mockNavigate.mockReset();
    vi.restoreAllMocks();
    window.alert = vi.fn();
  });

  describe("StudentDashboard Component", () => {
    it("renders academic overview, attendance metrics, and quick actions", async () => {
      vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
        if (url === "/student/dashboard") {
          return {
            data: {
              message: "Welcome, Arjun!",
              homework_count: 4,
              unresolved_doubts: 2,
              attendance_rate: 97.5,
              cumulative_gpa: "3.92 / 4.0",
              recent_activity: [],
            },
          };
        }
        return { data: {} };
      });

      render(
        <MemoryRouter>
          <StudentDashboard />
        </MemoryRouter>
      );

      // Verify portal branding and heading
      expect(screen.getByText(/Student Academic Portal/i)).toBeTruthy();
      expect(screen.getByText(/Academic Overview & Learning Trajectory/i)).toBeTruthy();

      // Verify KPI metrics after API resolution
      await waitFor(() => {
        expect(screen.getByText("4 Tasks Due")).toBeTruthy();
        expect(screen.getByText("2 Unresolved")).toBeTruthy();
        expect(screen.getByText("97.5%")).toBeTruthy();
      });

      // Verify action buttons
      const submitBtn = screen.getByRole("button", { name: /Submit Homework/i });
      const doubtBtn = screen.getByRole("button", { name: /Ask AI Doubt/i });
      expect(submitBtn).toBeTruthy();
      expect(doubtBtn).toBeTruthy();

      fireEvent.click(submitBtn);
      expect(mockNavigate).toHaveBeenCalledWith("/student/homework");

      fireEvent.click(doubtBtn);
      expect(mockNavigate).toHaveBeenCalledWith("/student/doubts");
    });
  });

  describe("HomeworkUpload Component", () => {
    it("renders assignment submission workspace and handles file upload validation", async () => {
      vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
        if (url === "/student/homework") {
          return {
            data: [
              {
                id: "sub-1",
                title: "Calculus Problem Set #4",
                subject: "MATHEMATICS",
                status: "graded",
                score: 95,
                max_score: 100,
                feedback: "Excellent work!",
                original_filename: "calculus_hw.pdf",
              },
            ],
          };
        }
        if (url === "/student/assignments") {
          return {
            data: [
              {
                id: "asg-1",
                title: "Physics Lab Report",
                subject: "PHYSICS",
                due_date: "2026-10-15",
                max_score: 100,
                instructions: "Upload lab write-up",
              },
            ],
          };
        }
        return { data: {} };
      });

      const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({
        data: { message: "Upload success" },
      });

      render(
        <MemoryRouter>
          <HomeworkUpload />
        </MemoryRouter>
      );

      // Verify workspace renders
      expect(screen.getByText(/Homework Upload & History/i)).toBeTruthy();
      expect(screen.getByText(/Pending Assignments Queue/i)).toBeTruthy();

      await waitFor(() => {
        expect(screen.getByText("Physics Lab Report")).toBeTruthy();
        expect(screen.getByText("Calculus Problem Set #4")).toBeTruthy();
      });

      // Verify button is disabled when no file is uploaded
      const submitBtn = screen.getByRole("button", { name: /SUBMIT COURSEWORK/i });
      expect(submitBtn.disabled).toBe(true);

      // Simulate file upload
      const fileInput = document.querySelector('input[type="file"]');
      expect(fileInput).toBeTruthy();

      const testFile = new File(["dummy pdf content"], "lab_report.pdf", {
        type: "application/pdf",
      });
      fireEvent.change(fileInput, { target: { files: [testFile] } });

      // Click submit with file attached
      expect(submitBtn.disabled).toBe(false);
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith(
          "/student/homework/upload",
          expect.any(FormData),
          expect.objectContaining({
            headers: { "Content-Type": undefined },
          })
        );
      });
    });
  });
});
