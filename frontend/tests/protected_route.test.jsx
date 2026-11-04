import { describe, it, expect, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import ProtectedRoute from "../src/components/ProtectedRoute";

describe("ProtectedRoute Security Guard", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("redirects unauthenticated user to /login", () => {
    sessionStorage.removeItem("is_authenticated");

    render(
      <MemoryRouter initialEntries={["/platform-admin/dashboard"]}>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route
            path="/platform-admin/dashboard"
            element={
              <ProtectedRoute requirePlatformAdmin={true}>
                <div>Admin Secret</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("Login Page")).toBeTruthy();
    expect(screen.queryByText("Admin Secret")).toBeNull();
  });

  it("redirects ordinary user attempting to access platform-admin route to their role dashboard", () => {
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "teacher");
    sessionStorage.setItem("is_platform_admin", "false");

    render(
      <MemoryRouter initialEntries={["/platform-admin/institutions"]}>
        <Routes>
          <Route path="/teacher/dashboard" element={<div>Teacher Dashboard</div>} />
          <Route
            path="/platform-admin/institutions"
            element={
              <ProtectedRoute requirePlatformAdmin={true}>
                <div>Institution Secret Management</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("Teacher Dashboard")).toBeTruthy();
    expect(screen.queryByText("Institution Secret Management")).toBeNull();
  });

  it("allows verified platform admin to access platform admin route", () => {
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "admin");
    sessionStorage.setItem("is_platform_admin", "true");

    render(
      <MemoryRouter initialEntries={["/platform-admin/dashboard"]}>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route
            path="/platform-admin/dashboard"
            element={
              <ProtectedRoute requirePlatformAdmin={true}>
                <div>Platform Admin Panel</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("Platform Admin Panel")).toBeTruthy();
  });

  it("allows standard authenticated user to access standard protected route", () => {
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "student");
    sessionStorage.setItem("is_platform_admin", "false");

    render(
      <MemoryRouter initialEntries={["/student/dashboard"]}>
        <Routes>
          <Route
            path="/student/dashboard"
            element={
              <ProtectedRoute requirePlatformAdmin={false}>
                <div>Student Home</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("Student Home")).toBeTruthy();
  });
});

