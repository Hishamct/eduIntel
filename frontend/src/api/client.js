import axios from "axios";

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      sessionStorage.removeItem("is_authenticated");
      sessionStorage.removeItem("user_role");
      localStorage.removeItem("access_token");
      localStorage.removeItem("demo_mode");

      const currentPath = window.location.pathname;
      const requestUrl = error.config?.url || "";
      if (currentPath !== "/login" && !requestUrl.includes("/auth/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;