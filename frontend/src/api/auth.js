import apiClient from "./client";

export async function logout(navigate) {
  try {
    await apiClient.post("/auth/logout");
  } catch {
    // Proceed with client cleanup even if network call fails
  }
  localStorage.removeItem("access_token");
  localStorage.removeItem("demo_mode");
  sessionStorage.removeItem("is_authenticated");
  sessionStorage.removeItem("user_role");
  navigate("/login", { replace: true });
}