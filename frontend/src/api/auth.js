export function logout(navigate) {
  localStorage.removeItem("access_token");
  navigate("/login", { replace: true });
}