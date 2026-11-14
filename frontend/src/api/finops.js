import apiClient from "./client";

/**
 * Institution-Admin FinOps Endpoints (Tenant-Scoped)
 */

export const getFinOpsOverview = async () => {
  const response = await apiClient.get("/finops/overview");
  return response.data;
};

export const getFinOpsDaily = async (params = {}) => {
  const response = await apiClient.get("/finops/daily", { params });
  return response.data;
};

export const getFinOpsByCategory = async (params = {}) => {
  const response = await apiClient.get("/finops/by-category", { params });
  return response.data;
};

export const getFinOpsByProvider = async (params = {}) => {
  const response = await apiClient.get("/finops/by-provider", { params });
  return response.data;
};

export const getFinOpsReservations = async (params = {}) => {
  const response = await apiClient.get("/finops/reservations", { params });
  return response.data;
};

export const getFinOpsAdjustments = async (params = {}) => {
  const response = await apiClient.get("/finops/adjustments", { params });
  return response.data;
};

/**
 * Platform-Admin FinOps Endpoints (Privileged Cross-Tenant)
 */

export const getPlatformFinOpsOverview = async () => {
  const response = await apiClient.get("/platform-admin/finops/overview");
  return response.data;
};

export const getPlatformFinOpsInstitutions = async (params = {}) => {
  const response = await apiClient.get("/platform-admin/finops/institutions", { params });
  return response.data;
};

export const getPlatformFinOpsPlans = async (params = {}) => {
  const response = await apiClient.get("/platform-admin/finops/plans", { params });
  return response.data;
};

export const upsertQuotaPlan = async (planId, data) => {
  const response = await apiClient.post(`/platform-admin/finops/plans/${planId}`, data);
  return response.data;
};

export const provisionTenantPlan = async (institutionId, data) => {
  const response = await apiClient.post(
    `/platform-admin/finops/institutions/${institutionId}/provision`,
    data
  );
  return response.data;
};

export const suspendTenantQuota = async (institutionId, reason) => {
  const response = await apiClient.post(
    `/platform-admin/finops/institutions/${institutionId}/suspend`,
    { reason }
  );
  return response.data;
};

export const resumeTenantQuota = async (institutionId, reason) => {
  const response = await apiClient.post(
    `/platform-admin/finops/institutions/${institutionId}/resume`,
    { reason }
  );
  return response.data;
};

export const getReconciliationBacklog = async (params = {}) => {
  const response = await apiClient.get("/platform-admin/finops/reconciliation-backlog", { params });
  return response.data;
};

export const manualSettleReservation = async (data) => {
  const response = await apiClient.post("/platform-admin/finops/reconciliation/manual-settle", data);
  return response.data;
};

export const triggerReconciliationSweep = async (batchSize = 50) => {
  const response = await apiClient.post(
    "/platform-admin/finops/reconciliation/sweep",
    {},
    { params: { batch_size: batchSize } }
  );
  return response.data;
};

export const getPricingOverview = async () => {
  const response = await apiClient.get("/platform-admin/finops/pricing");
  return response.data;
};

