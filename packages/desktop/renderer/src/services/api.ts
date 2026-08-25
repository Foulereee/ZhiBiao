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

export interface SSEController {
  cancel: () => void;
}

export interface SSEHandlers {
  onMessage: (data: Record<string, unknown>) => void;
  onError?: (err: Error) => void;
  onClose?: () => void;
}

export function streamSSE(url: string, handlers: SSEHandlers): SSEController {
  const token = localStorage.getItem('bidmaster_token');
  const controller = new AbortController();

  const start = async () => {
    try {
      const headers: Record<string, string> = { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const response = await fetch(url, { headers, signal: controller.signal });
      if (!response.ok || !response.body) {
        throw new Error(`SSE 连接失败 (${url}): HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (line.startsWith('data:')) {
            const data = line.slice(5).trim();
            if (!data || data === '[DONE]') continue;
            try {
              handlers.onMessage(JSON.parse(data));
            } catch {
              handlers.onMessage({ content: data });
            }
          }
        }
      }
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') {
        return;
      }
      handlers.onError?.(e instanceof Error ? e : new Error(String(e)));
    } finally {
      handlers.onClose?.();
    }
  };

  start();

  return {
    cancel: () => controller.abort(),
  };
}

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
  reviewer?: string;
  timestamp?: string;
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
  me: () => api.get<LoginUser>('/auth/me'),
  logout: () => api.post('/auth/logout', {}),
  changePassword: (newPassword: string) =>
    api.put('/auth/change-password', { new_password: newPassword }),
};

export const projectApi = {
  list: () => api.get<{ projects: Project[] }>('/projects/'),
  create: (name: string) => api.post(`/projects/?name=${encodeURIComponent(name)}`),
  get: (id: string) => api.get(`/projects/${id}`),
  updateStatus: (id: string, status: string) => api.patch(`/projects/${id}/status?status=${status}`),
  confirmGate: (id: string, stage: string) => api.post(`/projects/${id}/gate/${stage}`),
  resetGate: (id: string, stage: string) => api.delete(`/projects/${id}/gate/${stage}`),
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
  getOutline: (projectId: string) =>
    api.get(`/generate/${projectId}/outline`),
  generateOutline: (projectId: string, mode: string = 'aligned') =>
    api.post(`/generate/${projectId}/outline?mode=${mode}`),
  getTaskStatus: (taskId: string) =>
    api.get(`/generate/task/${taskId}`),
  generateChapter: (projectId: string, chapterId: string, mode: string = 'A') =>
    api.post(`/generate/${projectId}/content/${chapterId}?mode=${mode}`, {}, { timeout: 300000 }),
  streamChapter: (projectId: string, chapterId: string, mode: string = 'A', handlers?: SSEHandlers): SSEController | string => {
    const url = `/api/generate/${projectId}/content/stream/${chapterId}?mode=${mode}`;
    return handlers ? streamSSE(url, handlers) : url;
  },
  streamAllChapters: (projectId: string, mode: string = 'A', handlers?: SSEHandlers): SSEController | string => {
    const url = `/api/generate/${projectId}/content/stream-all?mode=${mode}`;
    return handlers ? streamSSE(url, handlers) : url;
  },
  listChapters: (projectId: string) =>
    api.get(`/generate/${projectId}/chapters`),
  getChapterContent: (projectId: string, chapterId: string) =>
    api.get(`/generate/${projectId}/chapters/${chapterId}`),
  updateChapterContent: (projectId: string, chapterId: string, content: string) =>
    api.put(`/generate/${projectId}/chapters/${chapterId}`, { content }),
  mandatoryExtract: (projectId: string) =>
    api.post(`/generate/${projectId}/mandatory-extract`),
  generateStructure: (projectId: string, structureType: string) =>
    api.post(`/generate/${projectId}/structure/${structureType}`),
  scoreCoverage: (projectId: string) =>
    api.post(`/generate/${projectId}/score-coverage`),
  exportDocx: (projectId: string, opts: { fmt?: 'docx' | 'doc' | 'pdf'; template?: string; applyFormat?: boolean } = {}) => {
    const fmt = opts.fmt ?? 'docx';
    const template = opts.template ?? 'default';
    const applyFormat = opts.applyFormat ?? true;
    return api.get(
      `/generate/${projectId}/export-docx?fmt=${fmt}&template=${template}&apply_format=${applyFormat}`,
      { responseType: 'blob' },
    );
  },
  getProjectStatus: (projectId: string) =>
    api.get(`/projects/${projectId}`),
    pollTask: async (taskId: string, onProgress?: (msg: string) => void, maxPolls: number = 120, interval: number = 5000): Promise<Record<string, unknown>> => {
    let consecutiveErrors = 0;
    for (let i = 0; i < maxPolls; i++) {
      await new Promise(r => setTimeout(r, interval));
      try {
        const res = await api.get(`/generate/task/${taskId}`);
        consecutiveErrors = 0;
        const task = res.data;
        if (task.status === 'completed') {
          return task.result || {};
        } else if (task.status === 'failed') {
          throw new Error(task.error || '任务执行失败');
        } else {
          const elapsed = task.elapsed_seconds ? `${Math.round(task.elapsed_seconds)}s` : '';
          onProgress?.(`任务执行中... ${elapsed}`);
        }
      } catch (e) {
        const isTaskFailure = e instanceof Error && e.message === '任务执行失败';
        if (isTaskFailure) {
          throw e;
        }
        consecutiveErrors++;
        if (consecutiveErrors > 5) {
          throw e;
        }
      }
    }
    throw new Error('任务超时，请重试');
  },
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
  submitCheck: (projectId: string, checkType: string) =>
    api.post(`/check/${projectId}/check-async`, { check_type: checkType }),
  listReports: (projectId: string) => api.get(`/check/${projectId}/reports`),
  getReportContent: (projectId: string, reportId: string, format: string = 'markdown') =>
    api.get(`/check/${projectId}/reports/${reportId}/content?format=${format}`),
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
  pollCheckTask: async (taskId: string, onProgress?: (msg: string) => void, maxPolls: number = 120, interval: number = 3000): Promise<Record<string, unknown>> => {
    let consecutiveErrors = 0;
    for (let i = 0; i < maxPolls; i++) {
      await new Promise(r => setTimeout(r, interval));
      try {
        const res = await api.get(`/check/task/${taskId}`);
        consecutiveErrors = 0;
        const task = res.data;
        if (task.status === 'completed') {
          return task.result || {};
        } else if (task.status === 'failed') {
          throw new Error(task.error || '任务执行失败');
        } else {
          const elapsed = task.elapsed_seconds ? `${Math.round(task.elapsed_seconds)}s` : '';
          onProgress?.(`检查执行中... ${elapsed}`);
        }
      } catch (e) {
        // Immediately throw if the task itself failed (not a transient network error)
        const isTaskFailure = e instanceof Error && e.message === '任务执行失败';
        if (isTaskFailure) {
          throw e;
        }
        consecutiveErrors++;
        if (consecutiveErrors > 5) {
          throw e;
        }
      }
    }
    throw new Error('检查任务超时，请稍后在报告列表中查看结果');
  },
};

export const formatApi = {
  formatFromProject: (projectId: string, template: string = 'default') =>
    api.post(`/format/from-project/${projectId}?template=${template}`),
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
  exportFormattedDocx: (file: File, template: string = 'default') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('template', template);
    return api.post('/format/export-formatted-docx', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      responseType: 'blob',
      timeout: 300000,
    });
  },
  exportDoc: (file: File, template: string = 'default', applyFormat: boolean = true) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('template', template);
    formData.append('apply_format', String(applyFormat));
    return api.post('/format/export-doc', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      responseType: 'blob',
      timeout: 300000,
    });
  },
  exportPdf: (file: File, template: string = 'default', applyFormat: boolean = true) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('template', template);
    formData.append('apply_format', String(applyFormat));
    return api.post('/format/export-pdf', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      responseType: 'blob',
      timeout: 300000,
    });
  },
  listTemplates: () => api.get('/format/templates'),
  getTemplate: (name: string) => api.get(`/format/templates/${name}`),
  saveTemplate: (name: string, config: Record<string, unknown>) => api.put(`/format/templates/${name}`, config),
  deleteTemplate: (name: string) => api.delete(`/format/templates/${name}`),
  downloadOutput: (path: string) => `/api/format/download?path=${encodeURIComponent(path)}`,
};

export interface MinerUConfig {
  mode: string;
  api_key_masked: string;
  endpoint: string;
  timeout: number;
  model_version: string;
  poll_interval: number;
  max_polls: number;
}

export const mineruApi = {
  getConfig: () => api.get<{ success?: boolean; mode: string; api_key_masked: string; endpoint: string; timeout: number; model_version: string; poll_interval: number; max_polls: number }>('/mineru/config'),
  updateConfig: (payload: {
    mode: string;
    endpoint: string;
    timeout: number;
    model_version: string;
    poll_interval: number;
    max_polls: number;
    api_key?: string;
  }) => api.put<{ success: boolean; config: MinerUConfig }>('/mineru/config', payload),
  testConnection: (payload: {
    mode: string;
    endpoint: string;
    timeout: number;
    model_version: string;
    poll_interval: number;
    max_polls: number;
    api_key?: string;
  }) => api.post<{ success: boolean; error?: string; message?: string }>('/mineru/test', payload),
  ocr: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<{ success: boolean; data?: { markdown: string; length: number; mode: string }; error?: string }>('/mineru/ocr', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    });
  },
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
  getDefaultModel: () => api.get('/llm/default-model'),
  listAgentModels: () => api.get('/llm/agent-models'),
  updateAgentModel: (name: string, config: Record<string, unknown>) => api.put(`/llm/agent-models/${name}`, config),
  resetAgentModels: () => api.post('/llm/agent-models/reset'),
  setDefaultModel: (config: Record<string, string>) => api.put('/llm/default-model', config),

  listConfigs: () => api.get('/llm/configs'),
  revealConfigKey: (configId: string) => api.get(`/llm/configs/${configId}/reveal`),
  createConfig: (payload: Record<string, unknown>) => api.post('/llm/configs', payload),
  updateConfig: (configId: string, payload: Record<string, unknown>) => api.put(`/llm/configs/${configId}`, payload),
  deleteConfig: (configId: string) => api.delete(`/llm/configs/${configId}`),
  setDefaultConfig: (configId: string) => api.post(`/llm/configs/${configId}/default`),
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

  // === Phase 1 新增端点 (数据源 + 行业 + 聚合 + 智能推荐) ===
  listIndustries: () => api.get<{ industries: Industry[] }>('/news/industries'),
  listSources: (params?: { industry?: string; enabled_only?: boolean }) =>
    api.get<{ sources: NewsSource[]; total: number }>('/news/sources', { params }),
  syncSources: () => api.post<{ success: boolean; synced: number; message: string }>('/news/sources/sync'),
  toggleSource: (code: string, enabled: boolean) =>
    api.patch<{ success: boolean; code: string; enabled: boolean }>(`/news/sources/${code}`, { enabled }),
  aggregate: (payload: {
    source_codes?: string[];
    industry_code?: string;
    company_profile?: Record<string, unknown>;
    is_hot_threshold?: number;
    persist?: boolean;
  }) => api.post<AggregateResponse>('/news/aggregate', payload),
  listHotspots: (params?: {
    industry_code?: string;
    region?: string;
    min_score?: number;
    is_hot?: boolean;
    keyword?: string;
    limit?: number;
    offset?: number;
  }) => api.get<HotspotListResponse>('/news/hotspots', { params }),
  getHotspotScore: (id: string) =>
    api.get<HotspotScoreDetail>(`/news/hotspots/${id}/score`),
  getHotspotDetail: (id: string) =>
    api.get<HotspotDetail>(`/news/hotspots/${id}`),
  convertHotspotToBid: (id: string, payload?: { project_name?: string; user_id?: string }) =>
    api.post<ConvertToBidResponse>(`/news/hotspots/${id}/convert-to-bid`, payload || {}),
};

// === News 相关类型 ===
export interface Industry {
  code: string;
  name: string;
  icon: string;
  weight: number;
  children: Array<{ code: string; name: string; weight: number }>;
}

export interface NewsSource {
  id: string;
  code: string;
  name: string;
  type: string;
  url: string;
  industry_code: string;
  weight: number;
  enabled: boolean;
  description: string;
  last_crawled_at: string | null;
  last_status: string;
}

export interface Hotspot {
  id: string;
  title: string;
  url: string;
  source: string;
  sources: string[];
  pub_date: string;
  industry_code: string;
  region: string;
  amount: number;
  bid_deadline: string;
  owner_org: string;
  project_code: string;
  score_total: number;
  is_hot: boolean;
  is_converted: boolean;
  converted_project_id: string;
  created_at: string;
}

export interface AggregateResponse {
  success: boolean;
  total: number;
  saved: number;
  items: Array<{
    title: string;
    url: string;
    source: string;
    industry_code: string;
    industry_name: string;
    score_total: number;
    is_hot: boolean;
  }>;
  errors?: Array<{ code: string; error: string }>;
  error?: string;
  message?: string;
}

export interface HotspotListResponse {
  total: number;
  limit: number;
  offset: number;
  items: Hotspot[];
}

export interface HotspotScoreDetail {
  id: string;
  title: string;
  url: string;
  industry_code: string;
  industry_name: string;
  industry_icon: string;
  region: string;
  amount: number;
  bid_deadline: string;
  owner_org: string;
  score: {
    total: number;
    urgency: number;
    match: number;
    amount: number;
    region: number;
    freshness: number;
  };
  is_hot: boolean;
  is_converted: boolean;
  converted_project_id: string;
}

export interface ConvertToBidResponse {
  success: boolean;
  project_id: string;
  project_name?: string;
  message: string;
}

export interface HotspotDetail extends HotspotScoreDetail {
  source: string;
  sources: string[];
  pub_date: string;
  project_code: string;
  /** 详情正文 (Markdown/纯文本) */
  content: string;
  content_length: number;
  extra: Record<string, unknown>;
  converted_project?: {
    id: string;
    name: string;
    status: string;
  } | null;
  created_at: string;
}

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
