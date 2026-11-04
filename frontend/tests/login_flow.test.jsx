import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "../src/pages/auth/Login";
import apiClient from "../src/api/client";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("Login Flow & Atomic Session State (SEC-02)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    mockNavigate.mockReset();
    vi.restoreAllMocks();
  });

  it("clears pre-existing stale session items on submit before API calls", async () => {
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "student");
    sessionStorage.setItem("is_platform_admin", "false");
    localStorage.setItem("access_token", "stale-jwt");

    let sessionStateDuringApiCall = null;
    vi.spyOn(apiClient, "post").mockImplementation(async (url) => {
      if (url === "/auth/login") {
        sessionStateDuringApiCall = {
          is_authenticated: sessionStorage.getItem("is_authenticated"),
          user_role: sessionStorage.getItem("user_role"),
          access_token: localStorage.getItem("access_token"),
        };
        return { data: { message: "ok" } };
      }
      return { data: {} };
    });

    vi.spyOn(apiClient, "get").mockImplementation(async (url) => {
      if (url === "/users/me") {
        return { data: { role: "admin", is_platform_admin: true } };
      }
      return { data: {} };
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText("admin@eduintel.ai");
    const passwordInput = screen.getByPlaceholderText("••••••••");
    const submitBtn = screen.getByRole("button", { name: /Sign In to EduIntel/i });

    fireEvent.change(emailInput, { target: { value: "admin@eduintel.ai" } });
    fireEvent.change(passwordInput, { target: { value: "SecretPass123!@" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/platform-admin/dashboard");
    });

    // Verify state was cleared prior to or during the initial API call
    expect(sessionStateDuringApiCall.is_authenticated).toBeNull();
    expect(sessionStateDuringApiCall.user_role).toBeNull();
    expect(sessionStateDuringApiCall.access_token).toBeNull();
  });

  it("atomically sets session state and redirects Platform Admin to /platform-admin/dashboard", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({ data: { message: "ok" } });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { role: "admin", is_platform_admin: true },
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("admin@eduintel.ai"), {
      target: { value: "superadmin@eduintel.ai" },
    });
    fireEvent.change(screen.getByPlaceholderText("••••••••"), {
      target: { value: "SuperPassword123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In to EduIntel/i }));

    await waitFor(() => {
      expect(sessionStorage.getItem("is_authenticated")).toBe("true");
      expect(sessionStorage.getItem("user_role")).toBe("admin");
      expect(sessionStorage.getItem("is_platform_admin")).toBe("true");
      expect(mockNavigate).toHaveBeenCalledWith("/platform-admin/dashboard");
    });
  });

  it("redirects institutional teacher to /teacher/dashboard", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({ data: { message: "ok" } });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { role: "teacher", is_platform_admin: false },
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("admin@eduintel.ai"), {
      target: { value: "teacher@school.edu" },
    });
    fireEvent.change(screen.getByPlaceholderText("••••••••"), {
      target: { value: "TeacherPassword123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In to EduIntel/i }));

    await waitFor(() => {
      expect(sessionStorage.getItem("is_authenticated")).toBe("true");
      expect(sessionStorage.getItem("user_role")).toBe("teacher");
      expect(sessionStorage.getItem("is_platform_admin")).toBe("false");
      expect(mockNavigate).toHaveBeenCalledWith("/teacher/dashboard");
    });
  });

  it("wipes all session state if /users/me fails post-login", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({ data: { message: "ok" } });
    vi.spyOn(apiClient, "get").mockRejectedValueOnce({
      response: { data: { detail: "Failed to fetch user profile" } },
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("admin@eduintel.ai"), {
      target: { value: "broken@eduintel.ai" },
    });
    fireEvent.change(screen.getByPlaceholderText("••••••••"), {
      target: { value: "Password123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In to EduIntel/i }));

    await waitFor(() => {
      expect(screen.getByText("Failed to fetch user profile")).toBeTruthy();
    });

    // Guarantee no partially authenticated session remains
    expect(sessionStorage.getItem("is_authenticated")).toBeNull();
    expect(sessionStorage.getItem("user_role")).toBeNull();
    expect(sessionStorage.getItem("is_platform_admin")).toBeNull();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("wipes session state if /auth/login fails", async () => {
    vi.spyOn(apiClient, "post").mockRejectedValueOnce({
      response: { data: { detail: "Incorrect email or password" } },
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("admin@eduintel.ai"), {
      target: { value: "bad@eduintel.ai" },
    });
    fireEvent.change(screen.getByPlaceholderText("••••••••"), {
      target: { value: "WrongPassword123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign In to EduIntel/i }));

    await waitFor(() => {
      expect(screen.getByText("Incorrect email or password")).toBeTruthy();
    });

    expect(sessionStorage.getItem("is_authenticated")).toBeNull();
    expect(sessionStorage.getItem("user_role")).toBeNull();
    expect(sessionStorage.getItem("is_platform_admin")).toBeNull();
  });
});
