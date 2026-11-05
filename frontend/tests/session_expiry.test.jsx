import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import apiClient from "../src/api/client";

describe("Session Expiry & HTTP 401 Interceptor Guard", () => {
  const originalLocation = window.location;
  const errorHandler = apiClient.interceptors.response.handlers[0].rejected;

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();

    delete window.location;
    window.location = {
      pathname: "/student/dashboard",
      href: "http://localhost:5173/student/dashboard",
    };
  });

  afterEach(() => {
    window.location = originalLocation;
  });

  it("clears all authentication tokens and session keys on 401 and redirects to /login", async () => {
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "student");
    sessionStorage.setItem("is_platform_admin", "false");
    localStorage.setItem("access_token", "active-jwt-token");
    localStorage.setItem("demo_mode", "false");

    const error = {
      response: { status: 401, data: { detail: "Token expired or revoked" } },
      config: { url: "/student/dashboard" },
    };

    await expect(errorHandler(error)).rejects.toBe(error);

    // Verify storage was thoroughly purged
    expect(sessionStorage.getItem("is_authenticated")).toBeNull();
    expect(sessionStorage.getItem("user_role")).toBeNull();
    expect(sessionStorage.getItem("is_platform_admin")).toBeNull();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("demo_mode")).toBeNull();

    // Verify redirected to login
    expect(window.location.href).toBe("/login");
  });

  it("does not redirect window.location when 401 is from /auth/login endpoint", async () => {
    window.location.pathname = "/login";
    window.location.href = "http://localhost:5173/login";

    const error = {
      response: { status: 401, data: { detail: "Incorrect credentials" } },
      config: { url: "/auth/login" },
    };

    await expect(errorHandler(error)).rejects.toBe(error);

    // Should NOT re-redirect to avoid refresh loops
    expect(window.location.href).toBe("http://localhost:5173/login");
  });

  it("does not redirect if user is already on /login page", async () => {
    window.location.pathname = "/login";
    window.location.href = "http://localhost:5173/login";

    const error = {
      response: { status: 401, data: { detail: "Session absent" } },
      config: { url: "/users/me" },
    };

    await expect(errorHandler(error)).rejects.toBe(error);

    expect(window.location.href).toBe("http://localhost:5173/login");
  });
});
