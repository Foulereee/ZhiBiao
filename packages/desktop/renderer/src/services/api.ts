import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('bidmaster_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const storeData = localStorage.getItem('bidmaster-app-store');
      if (storeData) {
        try {
          const parsed = JSON.parse(storeData);
          if (parsed?.state?.token) {
            localStorage.removeItem('bidmaster_token');
            localStorage.removeItem('bidmaster_user');
            const cleanState = { ...parsed, state: { ...parsed.state, token: null, user: null } };
            localStorage.setItem('bidmaster-app-store', JSON.stringify(cleanState));
          }
        } catch { /* ignore */ }
      }
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export interface Project {
  id: string;
  name: string;
  status: string;
  created_at: string;
}

export interface InterpretResult {
  success: boolean;
  data?: Record<string, unknown>;
  error?: string;
  warnings?: string[];
}

export interface CheckReport {
  id: string;
  type: string;
  risk_level: string;
  summary: Record<string, unknown>;
  created_at: string;
}

export interface OutlineNode {
  id: string;
  title: string;
  level: number;
  children: OutlineNode[];
  score_mapping?: string[];
  page_target?: number;
  status?: 'pending' | 'generating' | 'done';
}

export interface GateInfo {
  stage: string;
  label: string;
  status: 'pending' | 'confirmed' | 'blocked';
  items?: string[];
}

export interface LoginUser {
  id: string;
  email: string;
  name: string;
  role: string;
  avatar: string | null;
  roles: Array<{ id: string; name: string; display_name: string }>;
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ token: string; user: LoginUser }>('/auth/login', { email, password }),
  me: () => {
    const token = localStorage.getItem('bidmaster_token');
    return api.get<LoginUser>(`/auth/me?token=${token}`);
  },
  logout: () => {
    const token = localStorage.getItem('bidmaster_token');
    return api.post(`/auth/logout?token=${token}`);
  },
  changePassword: (oldPassword: string, newPassword: string) => {
    const token = localStorage.getItem('bidmaster_token');
    return api.put('/auth/change-password', { token, old_password: oldPassword, new_password: newPassword });
  },
};

export const projectApi = {
  list: () => api.get<{ projects: Project[] }>('/projects/'),
  create: (name: string) => api.post(`/projects/?name=${encodeURIComponent(name)}`),
  get: (id: string) => api.get(`/projects/${id}`),
  updateStatus: (id: string, status: string) => api.patch(`/projects/${id}/status?status=${status}`),
  confirmGate: (id: string, stage: string) => api.post(`/projects/${id}/gate/${stage}`),
  listGates: (id: string) => api.get(`/projects/${id}/gate`),
};

export const interpretApi = {
  upload: (projectId: string, files: File[]) => {
    const formData = new FormData();
    for (const f of files) {
      formData.append('files', f);
    }
    return api.post(`/interpret/upload/${projectId}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  listDocuments: (projectId: string) => api.get(`/interpret/documents/${projectId}`),
  getDocument: (documentId: string) => api.get(`/interpret/document/${documentId}`),
  getAnalysis: (projectId: string) => api.get<{
    has_documents: boolean;
    has_parsed: boolean;
    has_analysis: boolean;
    analysis: {
      dimensions: Record<string, unknown> | null;
      scoring_matrix: Record<string, unknown> | null;
      risk_flags: Record<string, unknown> | null;
      sections: unknown[] | null;
    } | null;
    parse_info: {
      text_length: number;
      doc_metadata: Record<string, unknown> | null;
    } | null;
  }>(`/interpret/analysis/${projectId}`),
  parse: (projectId: string) => api.post(`/interpret/parse/${projectId}`),
  interpret: (projectId: string) => api.post(`/interpret/interpret/${projectId}`),
  scoringMatrix: (projectId: string) => api.post(`/interpret/scoring-matrix/${projectId}`),
  riskAlert: (projectId: string) => api.post(`/interpret/risk-alert/${projectId}`),
  exportReport: (projectId: string, format: string = 'markdown') =>
    api.post(`/interpret/export/${projectId}?format=${format}`, null, { responseType: 'blob' }),
};

export const generateApi = {
  generateOutline: (projectId: string, mode: string = 'aligned') =>
    api.post(`/generate/${projectId}/outline?mode=${mode}`),
  getTaskStatus: (taskId: string) =>
    api.get(`/generate/task/${taskId}`),
  generateChapter: (projectId: string, chapterId: string, mode: string = 'A') =>
    api.post(`/generate/${projectId}/content/${chapterId}?mode=${mode}`, {}, { timeout: 300000 }),
  streamChapter: (projectId: string, chapterId: string, mode: string = 'A') =>
    `/api/generate/${projectId}/content/stream/${chapterId}?mode=${mode}`,
  mandatoryExtract: (projectId: string) =>
    api.post(`/generate/${projectId}/mandatory-extract`),
  generateStructure: (projectId: string, structureType: string) =>
    api.post(`/generate/${projectId}/structure/${structureType}`),
  scoreCoverage: (projectId: string) =>
    api.get(`/generate/${projectId}/score-coverage`),
};

export const checkApi = {
  compliance: (projectId: string) => api.post(`/check/${projectId}/compliance`),
  disqualification: (projectId: string) => api.post(`/check/${projectId}/disqualification`),
  qualification: (projectId: string) => api.post(`/check/${projectId}/qualification`),
  pricing: (projectId: string) => api.post(`/check/${projectId}/pricing`),
  fitScore: (projectId: string) => api.post(`/check/${projectId}/fit-score`),
  selfcheck: (projectId: string) => api.post(`/check/${projectId}/selfcheck`),
  fullCheck: (projectId: string) => api.post(`/check/${projectId}/full-check`),
  deposit: (projectId: string) => api.post(`/check/${projectId}/deposit`),
  signature: (projectId: string) => api.post(`/check/${projectId}/signature`),
  validity: (projectId: string) => api.post(`/check/${projectId}/validity`),
  consistency: (projectId: string) => api.post(`/check/${projectId}/consistency`),
  duplicate: (projectId: string) => api.post(`/check/${projectId}/duplicate`),
  mandatoryReq: (projectId: string) => api.post(`/check/${projectId}/mandatory-req`),
  docIntegrity: (projectId: string) => api.post(`/check/${projectId}/doc-integrity`),
  aiTextCheck: (projectId: string) => api.post(`/check/${projectId}/ai-text-check`),
  riskScore: (projectId: string) => api.post(`/check/${projectId}/risk-score`),
  crossCheck: (projectId: string) => api.post(`/check/${projectId}/cross-check`),
  sampleReport: (projectId: string) => api.post(`/check/${projectId}/sample-report`),
  jointBid: (projectId: string) => api.post(`/check/${projectId}/joint-bid`),
  ebidSubmit: (projectId: string) => api.post(`/check/${projectId}/ebid-submit`),
  pricingLogic: (projectId: string) => api.post(`/check/${projectId}/pricing-logic`),
  listReports: (projectId: string) => api.get(`/check/${projectId}/reports`),
  exportReport: (projectId: string, reportId: string, format: string = 'markdown') =>
    api.get(`/check/${projectId}/reports/${reportId}/export?format=${format}`, { responseType: 'blob' }),
  uploadCheck: (bidFile: File, tenderFile: File | null, checkType: string = 'fullCheck') => {
    const formData = new FormData();
    formData.append('bid_file', bidFile);
    if (tenderFile) {
      formData.append('tender_file', tenderFile);
    }
    formData.append('check_type', checkType);
    return api.post('/check/upload-check', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    });
  },
};

export const formatApi = {
  format: (file: File, template: string = 'default', mode: string = 'format') => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/format/format?template=${template}&mode=${mode}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  checkFormat: (file: File, template: string = 'default') => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/format/check-format?template=${template}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  diffFormat: (file: File, template: string = 'default') => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/format/diff-format?template=${template}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  beautify: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/format/beautify', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  listTemplates: () => api.get('/format/templates'),
  getTemplate: (name: string) => api.get(`/format/templates/${name}`),
  saveTemplate: (name: string, config: Record<string, unknown>) => api.put(`/format/templates/${name}`, config),
  deleteTemplate: (name: string) => api.delete(`/format/templates/${name}`),
};

export const skillApi = {
  list: () => api.get('/skills/'),
  get: (name: string) => api.get(`/skills/${name}`),
  execute: (name: string, parameters: Record<string, unknown>, projectId: string = '') =>
    api.post(`/skills/${name}/execute?project_id=${projectId}`, { parameters }),
};

export const llmApi = {
  listProviders: () => api.get('/llm/providers'),
  testConnection: (config: Record<string, string>) => api.post('/llm/test', config),
  getUsage: () => api.get('/llm/usage'),
  listAgentModels: () => api.get('/llm/agent-models'),
  updateAgentModel: (name: string, config: Record<string, unknown>) => api.put(`/llm/agent-models/${name}`, config),
  resetAgentModels: () => api.post('/llm/agent-models/reset'),
  setDefaultModel: (config: Record<string, string>) => api.put('/llm/default-model', config),
};

export const newsApi = {
  listTasks: () => api.get('/news/tasks'),
  createTask: (data: { name: string; keywords: string; sites?: string[]; interval_minutes?: number }) =>
    api.post('/news/tasks', data),
  updateTask: (id: string, data: { enabled?: boolean; name?: string; keywords?: string }) =>
    api.patch(`/news/tasks/${id}`, data),
  deleteTask: (id: string) => api.delete(`/news/tasks/${id}`),
  runTask: (id: string) => api.post(`/news/tasks/${id}/run`),
  semanticFilter: (taskId: string, companyProfile: string = '', threshold: number = 0.6) =>
    api.post(`/news/tasks/${taskId}/semantic-filter?company_profile=${encodeURIComponent(companyProfile)}&threshold=${threshold}`),
  listResults: (taskId: string) => api.get(`/news/tasks/${taskId}/results`),
  todayHot: (category: string = 'all', limit: number = 50) =>
    api.get(`/news/today-hot?category=${category}&limit=${limit}`),
  refreshHot: () => api.post('/news/refresh-hot'),
};

export const knowledgeApi = {
  list: () => api.get('/knowledge/'),
  create: (data: { name: string; embedding_model?: string }) => api.post('/knowledge/', data),
  delete: (id: string) => api.delete(`/knowledge/${id}`),
  upload: (id: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/knowledge/${id}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  search: (id: string, query: string, topK: number = 5) =>
    api.post(`/knowledge/${id}/search?query=${encodeURIComponent(query)}&top_k=${topK}`),
};

export const rbacApi = {
  listRoles: () => api.get('/rbac/roles'),
  createRole: (data: { name: string; display_name: string; description?: string }) => api.post('/rbac/roles', data),
  updateRole: (id: string, data: { display_name?: string; description?: string }) => api.put(`/rbac/roles/${id}`, data),
  deleteRole: (id: string) => api.delete(`/rbac/roles/${id}`),
  listPermissions: () => api.get('/rbac/permissions'),
  assignPermissions: (roleId: string, permissionIds: string[]) => api.post(`/rbac/roles/${roleId}/permissions`, { permission_ids: permissionIds }),
  removePermission: (roleId: string, permissionId: string) => api.delete(`/rbac/roles/${roleId}/permissions/${permissionId}`),
  listUsers: () => api.get('/rbac/users'),
  createUser: (data: { email: string; name: string; password: string }) => api.post('/rbac/users', data),
  updateUser: (id: string, data: { name?: string; email?: string }) => api.put(`/rbac/users/${id}`, data),
  deleteUser: (id: string) => api.delete(`/rbac/users/${id}`),
  assignRoles: (userId: string, roleIds: string[]) => api.post(`/rbac/users/${userId}/roles`, { role_ids: roleIds }),
  removeRole: (userId: string, roleId: string) => api.delete(`/rbac/users/${userId}/roles/${roleId}`),
  checkPermission: (userId: string, permissionCode: string) => api.post('/rbac/check-permission', { user_id: userId, permission_code: permissionCode }),
  initRbac: () => api.post('/rbac/init'),
};

export const aiImageApi = {
  generate: (prompt: string, provider: string = 'default', imageSize: string = 'landscape_16_9') =>
    api.post('/ai-image/generate', { prompt, provider, image_size: imageSize }, { timeout: 120000 }),
  listProviders: () => api.get('/ai-image/providers'),
  saveConfig: (provider: string, apiKey: string) => api.put('/ai-image/config', { provider, api_key: apiKey }),
};

export default api;
