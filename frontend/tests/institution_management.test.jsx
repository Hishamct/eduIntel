import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import InstitutionManagement from "../src/pages/platform-admin/InstitutionManagement";
import apiClient from "../src/api/client";

const mockInstitutions = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    name: "Springfield Academy",
    slug: "springfield",
    contact_email: "contact@springfield.edu",
    is_active: true,
    student_count: 120,
    teacher_count: 15,
    admin_count: 2,
    total_memberships: 137,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    name: "Shelbyville High",
    slug: "shelbyville",
    contact_email: "contact@shelbyville.edu",
    is_active: false,
    student_count: 80,
    teacher_count: 10,
    admin_count: 1,
    total_memberships: 91,
    created_at: "2026-01-02T00:00:00Z",
  },
];

describe("Institution Management UI & Lifecycle (SEC-04, SEC-05)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem("is_authenticated", "true");
    sessionStorage.setItem("user_role", "admin");
    sessionStorage.setItem("is_platform_admin", "true");
    vi.restoreAllMocks();
  });

  it("renders institutions list and computes counts accurately", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: mockInstitutions });

    render(
      <MemoryRouter>
        <InstitutionManagement />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Springfield Academy")).toBeTruthy();
      expect(screen.getByText("Shelbyville High")).toBeTruthy();
    });

    // Verify Active / Suspended badges
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Suspended")).toBeTruthy();
  });

  it("opens suspension confirmation modal before status modification", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: mockInstitutions });
    const patchSpy = vi.spyOn(apiClient, "patch").mockResolvedValueOnce({
      data: { ...mockInstitutions[0], is_active: false },
    });

    render(
      <MemoryRouter>
        <InstitutionManagement />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Springfield Academy")).toBeTruthy();
    });

    // Click Suspend action button on first active institution
    const suspendButtons = screen.getAllByRole("button", { name: /Suspend/i });
    fireEvent.click(suspendButtons[0]);

    // Modal title appears
    await waitFor(() => {
      expect(screen.getByText("Suspend Institution")).toBeTruthy();
    });

    // Click confirm in modal
    const confirmBtn = screen.getByRole("button", { name: /Confirm Suspension/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith(
        "/institutions/11111111-1111-1111-1111-111111111111/status",
        { is_active: false }
      );
    });
  });

  it("provisions institution and presents one-time activation token with copy action", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: mockInstitutions });
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        institution_id: "33333333-3333-3333-3333-333333333333",
        name: "Capital City College",
        slug: "capital-city",
        admin_name: "Principal Seymour",
        admin_email: "principal@capital.edu",
        activation_token: "secret-one-time-token-xyz-123",
        expires_at: "2026-11-06T12:00:00Z",
        invitation_sent: true,
        invitation_status: "sent",
      },
    });

    // Mock clipboard API
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });

    render(
      <MemoryRouter>
        <InstitutionManagement />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Springfield Academy")).toBeTruthy();
    });

    // Open Onboard Modal
    fireEvent.click(screen.getByRole("button", { name: /Onboard Institution/i }));

    expect(screen.getByText("Onboard New Institution")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("e.g. Apex International Academy"), { target: { value: "Capital City College" } });
    fireEvent.change(screen.getByPlaceholderText("Dr. Alex Rivera"), { target: { value: "Principal Seymour" } });
    fireEvent.change(screen.getByPlaceholderText("alex@apex.edu"), { target: { value: "principal@capital.edu" } });

    // Submit provisioning
    fireEvent.click(screen.getByRole("button", { name: /Provision Tenant/i }));

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalled();
      expect(screen.getByText("Tenant Provisioned Successfully")).toBeTruthy();
    });

    // Verify token is displayed
    expect(screen.getByText("secret-one-time-token-xyz-123")).toBeTruthy();
    expect(screen.getByText("Dispatched via SMTP")).toBeTruthy();

    // Click Copy Activation Link
    const copyBtn = screen.getByRole("button", { name: /Copy Full Activation Link/i });
    fireEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining("secret-one-time-token-xyz-123")
    );
  });
});
