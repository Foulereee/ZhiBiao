import { useState, useEffect, useCallback, useMemo } from 'react';
import { Settings, Loader2, CheckCircle2, XCircle, Bot, Save, RotateCcw, ChevronDown, ChevronRight, Cpu, Shield, Plus, Trash2, Users, UserPlus, X, ScanLine, Eye, EyeOff, Cloud, Server, Zap, Edit2 } from 'lucide-react';
import { llmApi, skillApi, rbacApi, mineruApi, type MinerUConfig } from '../services/api';

type SettingsTab = 'agents' | 'llm' | 'rbac' | 'skills' | 'mineru';

interface AgentModel {
  name: string;
  display_name: string;
  description: string;
  model: string;
  temperature: number;
  max_tokens: number;
  enabled: boolean;
}

interface RbacRole {
  id: string;
  name: string;
  display_name: string;
  description: string;
  permissions?: RbacPermission[];
  users?: RbacUser[];
}

interface RbacPermission {
  id: string;
  code: string;
  name: string;
  description: string;
  category: string;
}

interface RbacUser {
  id: string;
  name: string;
  email: string;
  roles?: Array<{ id: string; name: string; display_name: string }>;
}

interface LLMConfigItem {
  id: string;
  provider_id: string;
  display_name: string;
  api_key_masked: string;
  has_api_key: boolean;
  api_base: string;
  default_model: string;
  is_default: boolean;
  enabled: boolean;
  note: string;
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('agents');

  const [providers, setProviders] = useState<Array<{ id: string; name: string; models: string[] }>>([]);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [tokenUsage, setTokenUsage] = useState<Record<string, unknown> | null>(null);

  const [llmConfigs, setLlmConfigs] = useState<LLMConfigItem[]>([]);
  const [llmConfigsLoading, setLlmConfigsLoading] = useState(false);
  const [llmConfigDialog, setLlmConfigDialog] = useState<{ open: boolean; mode: 'create' | 'edit'; configId: string | null; providerId: string; displayName: string; apiKey: string; apiBase: string; defaultModel: string; enabled: boolean; note: string; showKey: boolean }>({
    open: false, mode: 'create', configId: null, providerId: 'deepseek', displayName: '', apiKey: '', apiBase: '', defaultModel: '', enabled: true, note: '', showKey: false,
  });
  const [llmConfigSaving, setLlmConfigSaving] = useState(false);
  const [llmConfigRevealed, setLlmConfigRevealed] = useState<{ [id: string]: string }>({});

  const [agents, setAgents] = useState<AgentModel[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [agentsSaving, setAgentsSaving] = useState<string>('');
  const [agentsMessage, setAgentsMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string>('');

  const [skills, setSkills] = useState<Array<Record<string, unknown>>>([]);

  const [rbacRoles, setRbacRoles] = useState<RbacRole[]>([]);
  const [rbacPermissions, setRbacPermissions] = useState<RbacPermission[]>([]);
  const [rbacUsers, setRbacUsers] = useState<RbacUser[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string>('');
  const [rbacLoading, setRbacLoading] = useState(false);
  const [rbacMessage, setRbacMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [showCreateRoleDialog, setShowCreateRoleDialog] = useState(false);
  const [newRoleName, setNewRoleName] = useState('');
  const [newRoleDisplayName, setNewRoleDisplayName] = useState('');
  const [newRoleDescription, setNewRoleDescription] = useState('');

  const [assignRoleDialog, setAssignRoleDialog] = useState<{ userId: string; userName: string; roleIds: string[] } | null>(null);
  const [showCreateUserDialog, setShowCreateUserDialog] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [editingUserId, setEditingUserId] = useState<string>('');
  const [editUserName, setEditUserName] = useState('');
  const [editUserEmail, setEditUserEmail] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<string>('');

  const [mineruConfig, setMineruConfig] = useState<{
    mode: string;
    api_key: string;
    api_key_masked: string;
    endpoint: string;
    timeout: number;
    model_version: string;
    poll_interval: number;
    max_polls: number;
  }>({
    mode: 'cloud',
    api_key: '',
    api_key_masked: '',
    endpoint: 'https://mineru.net/api/v4',
    timeout: 180,
    model_version: 'vlm',
    poll_interval: 5,
    max_polls: 60,
  });
  const [mineruLoading, setMineruLoading] = useState(false);
  const [mineruSaving, setMineruSaving] = useState(false);
  const [mineruTesting, setMineruTesting] = useState(false);
  const [mineruTestResult, setMineruTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [mineruMessage, setMineruMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [showMineruKey, setShowMineruKey] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [providersRes, skillsRes, usageRes, agentsRes, configsRes] = await Promise.allSettled([
        llmApi.listProviders(),
        skillApi.list(),
        llmApi.getUsage(),
        llmApi.listAgentModels(),
        llmApi.listConfigs(),
      ]);

      if (providersRes.status === 'fulfilled') {
        setProviders(providersRes.value.data.providers || []);
      }
      if (skillsRes.status === 'fulfilled') {
        setSkills(skillsRes.value.data.skills || []);
      }
      if (usageRes.status === 'fulfilled') {
        setTokenUsage(usageRes.value.data);
      }
      if (agentsRes.status === 'fulfilled') {
        setAgents(agentsRes.value.data.agents || []);
        if (agentsRes.value.data.agents?.length > 0 && !expandedAgent) {
          setExpandedAgent(agentsRes.value.data.agents[0].name);
        }
      }
      if (configsRes.status === 'fulfilled') {
        setLlmConfigs(configsRes.value.data.configs || []);
      }
    } catch (e) {
      console.error('加载配置失败', e);
    }
  }, [expandedAgent]);

  const loadLlmConfigs = useCallback(async () => {
    setLlmConfigsLoading(true);
    try {
      const res = await llmApi.listConfigs();
      setLlmConfigs(res.data.configs || []);
    } catch (e) {
      console.error('加载 LLM 配置列表失败', e);
    } finally {
      setLlmConfigsLoading(false);
    }
  }, []);

  const providerApiBases: Record<string, string> = {
    deepseek: 'https://api.deepseek.com',
    zhipu: 'https://open.bigmodel.cn/api/paas/v4',
    qianfan: 'https://aip.baidubce.com',
    dashscope: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    siliconflow: 'https://api.siliconflow.cn/v1',
    ollama: 'http://localhost:11434',
    openai: 'https://api.openai.com/v1',
  };

  const handleOpenCreateConfig = () => {
    const firstProvider = providers[0]?.id || 'deepseek';
    setLlmConfigDialog({
      open: true, mode: 'create', configId: null,
      providerId: firstProvider,
      displayName: '', apiKey: '', apiBase: providerApiBases[firstProvider] || '',
      defaultModel: '', enabled: true, note: '', showKey: true,
    });
    setLlmConfigRevealed({});
  };

  const handleOpenEditConfig = async (cfg: LLMConfigItem) => {
    setLlmConfigDialog({
      open: true, mode: 'edit', configId: cfg.id,
      providerId: cfg.provider_id, displayName: cfg.display_name || '',
      apiKey: '', apiBase: cfg.api_base || '', defaultModel: cfg.default_model || '',
      enabled: cfg.enabled, note: cfg.note || '', showKey: true,
    });
    setLlmConfigRevealed({});
    try {
      const res = await llmApi.revealConfigKey(cfg.id);
      setLlmConfigRevealed({ [cfg.id]: res.data.api_key || '' });
    } catch (e) {
      console.error('获取 Key 明文失败', e);
    }
  };

  const handleSaveConfig = async () => {
    if (!llmConfigDialog.providerId || !llmConfigDialog.apiKey) {
      setTestResult({ success: false, message: '请填写供应商和 API Key' });
      return;
    }
    setLlmConfigSaving(true);
    try {
      if (llmConfigDialog.mode === 'create') {
        await llmApi.createConfig({
          provider_id: llmConfigDialog.providerId,
          display_name: llmConfigDialog.displayName,
          api_key: llmConfigDialog.apiKey,
          api_base: llmConfigDialog.apiBase,
          default_model: llmConfigDialog.defaultModel,
          enabled: llmConfigDialog.enabled,
          note: llmConfigDialog.note,
        });
        setTestResult({ success: true, message: '配置已创建' });
      } else {
        await llmApi.updateConfig(llmConfigDialog.configId!, {
          display_name: llmConfigDialog.displayName,
          api_key: llmConfigDialog.apiKey,
          api_base: llmConfigDialog.apiBase,
          default_model: llmConfigDialog.defaultModel,
          enabled: llmConfigDialog.enabled,
          note: llmConfigDialog.note,
        });
        setTestResult({ success: true, message: '配置已更新' });
      }
      setLlmConfigDialog(prev => ({ ...prev, open: false }));
      await loadLlmConfigs();
      await loadData();
    } catch (e: unknown) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setLlmConfigSaving(false);
    }
  };

  const handleDeleteConfig = async (id: string) => {
    if (!confirm('确定删除该供应商配置？')) return;
    try {
      await llmApi.deleteConfig(id);
      setTestResult({ success: true, message: '配置已删除' });
      await loadLlmConfigs();
      await loadData();
    } catch (e: unknown) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : '删除失败' });
    }
  };

  const handleSetDefaultConfig = async (id: string) => {
    try {
      await llmApi.setDefaultConfig(id);
      setTestResult({ success: true, message: '已设为默认' });
      await loadLlmConfigs();
      await loadData();
    } catch (e: unknown) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : '设置默认失败' });
    }
  };

  const handleTestConfig = async (cfg: LLMConfigItem) => {
    try {
      const revealRes = await llmApi.revealConfigKey(cfg.id);
      const realKey = revealRes.data.api_key;
      const modelName = cfg.default_model || `${cfg.provider_id}/default`;
      const testPayload: Record<string, string> = {
        provider: cfg.provider_id,
        api_key: realKey,
        api_base: cfg.api_base || '',
        model: modelName,
      };
      setTestResult({ success: false, message: '正在测试...' });
      const res = await llmApi.testConnection(testPayload);
      if (res.data.success) {
        setTestResult({ success: true, message: `连接成功：${res.data.response?.slice(0, 50) || 'OK'}` });
      } else {
        setTestResult({ success: false, message: res.data.error || '连接失败' });
      }
    } catch (e: unknown) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : '测试失败' });
    }
  };

  const loadRbacData = useCallback(async () => {
    setRbacLoading(true);
    try {
      const [rolesRes, permsRes, usersRes] = await Promise.allSettled([
        rbacApi.listRoles(),
        rbacApi.listPermissions(),
        rbacApi.listUsers(),
      ]);
      if (rolesRes.status === 'fulfilled') {
        setRbacRoles(rolesRes.value.data.roles || rolesRes.value.data || []);
      }
      if (permsRes.status === 'fulfilled') {
        let perms = (permsRes.value.data.permissions || permsRes.value.data || []) as RbacPermission[];
        if (!Array.isArray(perms)) {
          const flatPerms: RbacPermission[] = [];
          for (const [cat, items] of Object.entries(perms)) {
            if (Array.isArray(items)) {
              for (const p of items) {
                flatPerms.push({ ...p, category: p.category || cat });
              }
            }
          }
          perms = flatPerms;
        }
        setRbacPermissions(perms);
        const categories = new Set<string>(perms.map((p) => p.category));
        setExpandedCategories(categories);
      }
      if (usersRes.status === 'fulfilled') {
        setRbacUsers(usersRes.value.data.users || usersRes.value.data || []);
      }
    } catch (e) {
      console.error('加载RBAC数据失败', e);
    } finally {
      setRbacLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (activeTab === 'rbac') {
      loadRbacData();
    }
  }, [activeTab, loadRbacData]);

  const loadMineruConfig = useCallback(async () => {
    setMineruLoading(true);
    setMineruMessage(null);
    try {
      const res = await mineruApi.getConfig();
      const data = res.data as MinerUConfig;
      setMineruConfig(prev => ({
        ...prev,
        mode: data.mode || 'cloud',
        api_key_masked: data.api_key_masked || '',
        endpoint: data.endpoint || 'https://mineru.net/api/v4',
        timeout: data.timeout || 180,
        model_version: data.model_version || 'vlm',
        poll_interval: data.poll_interval || 5,
        max_polls: data.max_polls || 60,
      }));
    } catch (e: unknown) {
      console.error('加载 MinerU 配置失败', e);
      setMineruMessage({ type: 'error', text: e instanceof Error ? e.message : '加载 MinerU 配置失败' });
    } finally {
      setMineruLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'mineru') {
      loadMineruConfig();
    }
  }, [activeTab, loadMineruConfig]);

  const handleSaveMineru = async () => {
    setMineruSaving(true);
    setMineruMessage(null);
    setMineruTestResult(null);
    try {
      const payload: {
        mode: string;
        endpoint: string;
        timeout: number;
        model_version: string;
        poll_interval: number;
        max_polls: number;
        api_key?: string;
      } = {
        mode: mineruConfig.mode,
        endpoint: mineruConfig.endpoint,
        timeout: mineruConfig.timeout,
        model_version: mineruConfig.model_version,
        poll_interval: mineruConfig.poll_interval,
        max_polls: mineruConfig.max_polls,
      };
      if (mineruConfig.api_key) {
        payload.api_key = mineruConfig.api_key;
      }
      const res = await mineruApi.updateConfig(payload);
      const saved = res.data.config;
      setMineruConfig(prev => ({
        ...prev,
        api_key_masked: saved.api_key_masked,
        api_key: '',
        mode: saved.mode,
        endpoint: saved.endpoint,
        timeout: saved.timeout,
        model_version: saved.model_version,
        poll_interval: saved.poll_interval,
        max_polls: saved.max_polls,
      }));
      setMineruMessage({ type: 'success', text: 'MinerU 配置已保存' });
    } catch (e: unknown) {
      setMineruMessage({ type: 'error', text: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setMineruSaving(false);
    }
  };

  const handleTestMineru = async () => {
    setMineruTesting(true);
    setMineruTestResult(null);
    setMineruMessage(null);
    try {
      const payload: {
        mode: string;
        endpoint: string;
        timeout: number;
        model_version: string;
        poll_interval: number;
        max_polls: number;
        api_key?: string;
      } = {
        mode: mineruConfig.mode,
        endpoint: mineruConfig.endpoint,
        timeout: mineruConfig.timeout,
        model_version: mineruConfig.model_version,
        poll_interval: mineruConfig.poll_interval,
        max_polls: mineruConfig.max_polls,
      };
      if (mineruConfig.api_key) {
        payload.api_key = mineruConfig.api_key;
      }
      const res = await mineruApi.testConnection(payload);
      setMineruTestResult({
        success: !!res.data.success,
        message: res.data.success ? (res.data.message || '连接成功') : (res.data.error || '连接失败'),
      });
    } catch (e: unknown) {
      setMineruTestResult({
        success: false,
        message: e instanceof Error ? e.message : '连接失败',
      });
    } finally {
      setMineruTesting(false);
    }
  };

  const handleAgentChange = (name: string, field: string, value: unknown) => {
    setAgents(prev => prev.map(a => a.name === name ? { ...a, [field]: value } : a));
  };

  const handleSaveAgent = async (agent: AgentModel) => {
    setAgentsSaving(agent.name);
    setAgentsMessage(null);
    try {
      await llmApi.updateAgentModel(agent.name, {
        name: agent.name,
        display_name: agent.display_name,
        description: agent.description,
        model: agent.model,
        temperature: agent.temperature,
        max_tokens: agent.max_tokens,
        enabled: agent.enabled,
      });
      setAgentsMessage({ type: 'success', text: `${agent.display_name} 配置已保存` });
    } catch (e: unknown) {
      setAgentsMessage({ type: 'error', text: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setAgentsSaving('');
    }
  };

  const handleResetAgents = async () => {
    setAgentsLoading(true);
    setAgentsMessage(null);
    try {
      await llmApi.resetAgentModels();
      const res = await llmApi.listAgentModels();
      setAgents(res.data.agents || []);
      setAgentsMessage({ type: 'success', text: '已重置所有Agent配置为默认值' });
    } catch (e: unknown) {
      setAgentsMessage({ type: 'error', text: e instanceof Error ? e.message : '重置失败' });
    } finally {
      setAgentsLoading(false);
    }
  };

  const providerNameMap = useMemo(() => {
    const m: Record<string, string> = {};
    for (const p of providers) m[p.id] = p.name;
    return m;
  }, [providers]);

  // 智能体可选模型：仅从用户已配置的 LLM 中生成
  const agentModelOptions = llmConfigs
    .filter(c => c.enabled && c.default_model)
    .map(c => {
      const providerName = providerNameMap[c.provider_id] || c.provider_id;
      const tag = c.display_name ? `${providerName} · ${c.display_name}` : providerName;
      return {
        configId: c.id,
        value: `${c.provider_id}/${c.default_model}`,
        label: `${tag} — ${c.default_model}${c.is_default ? '（默认）' : ''}`,
        isDefault: c.is_default,
      };
    });

  const defaultLlmConfig = llmConfigs.find(c => c.is_default && c.enabled) || null;
  const defaultLlmModelLabel = defaultLlmConfig
    ? `${defaultLlmConfig.display_name || providerNameMap[defaultLlmConfig.provider_id] || defaultLlmConfig.provider_id} — ${defaultLlmConfig.default_model}`
    : '';

  const handleCreateRole = async () => {
    if (!newRoleName || !newRoleDisplayName) return;
    try {
      await rbacApi.createRole({ name: newRoleName, display_name: newRoleDisplayName, description: newRoleDescription });
      setShowCreateRoleDialog(false);
      setNewRoleName('');
      setNewRoleDisplayName('');
      setNewRoleDescription('');
      setRbacMessage({ type: 'success', text: '角色创建成功' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '创建角色失败' });
    }
  };

  const handleUpdateRole = async (role: RbacRole) => {
    try {
      await rbacApi.updateRole(role.id, { display_name: role.display_name, description: role.description });
      setRbacMessage({ type: 'success', text: '角色更新成功' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '更新角色失败' });
    }
  };

  const handleDeleteRole = async (roleId: string) => {
    try {
      await rbacApi.deleteRole(roleId);
      setSelectedRoleId('');
      setRbacMessage({ type: 'success', text: '角色已删除' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '删除角色失败' });
    }
  };

  const handleTogglePermission = async (roleId: string, permissionId: string, currentlyAssigned: boolean) => {
    try {
      if (currentlyAssigned) {
        await rbacApi.removePermission(roleId, permissionId);
      } else {
        const role = rbacRoles.find(r => r.id === roleId);
        const currentPermIds = (role?.permissions || []).map(p => p.id);
        const newPermIds = currentlyAssigned
          ? currentPermIds.filter(id => id !== permissionId)
          : [...currentPermIds, permissionId];
        await rbacApi.assignPermissions(roleId, newPermIds);
      }
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '权限操作失败' });
    }
  };

  const handleCreateUser = async () => {
    if (!newUserEmail || !newUserName || !newUserPassword) return;
    try {
      await rbacApi.createUser({ email: newUserEmail, name: newUserName, password: newUserPassword });
      setShowCreateUserDialog(false);
      setNewUserName('');
      setNewUserEmail('');
      setNewUserPassword('');
      setRbacMessage({ type: 'success', text: '用户创建成功' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '创建用户失败' });
    }
  };

  const handleUpdateUser = async () => {
    if (!editingUserId) return;
    try {
      await rbacApi.updateUser(editingUserId, { name: editUserName, email: editUserEmail });
      setEditingUserId('');
      setRbacMessage({ type: 'success', text: '用户更新成功' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '更新用户失败' });
    }
  };

  const handleDeleteUser = async (userId: string) => {
    try {
      await rbacApi.deleteUser(userId);
      setDeleteConfirmId('');
      setRbacMessage({ type: 'success', text: '用户已删除' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '删除用户失败' });
    }
  };

  const handleRemoveRoleFromUser = async (userId: string, roleId: string) => {
    try {
      await rbacApi.removeRole(userId, roleId);
      setRbacMessage({ type: 'success', text: '已移除用户角色' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '移除角色失败' });
    }
  };

  const handleAssignRole = async () => {
    if (!assignRoleDialog || assignRoleDialog.roleIds.length === 0) return;
    const { userId, roleIds } = assignRoleDialog;
    const user = rbacUsers.find(u => u.id === userId);
    const alreadyAssigned = (user?.roles || []).filter(r => roleIds.includes(r.id)).map(r => r.display_name);
    if (alreadyAssigned.length > 0) {
      setRbacMessage({ type: 'error', text: `该用户已拥有角色：${alreadyAssigned.join('、')}` });
      return;
    }
    try {
      await rbacApi.assignRoles(userId, roleIds);
      setRbacMessage({ type: 'success', text: `成功分配 ${roleIds.length} 个角色` });
      setAssignRoleDialog(null);
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '分配角色失败' });
    }
  };

  const SYSTEM_SUPER_ADMIN_EMAIL = 'admin@bidmaster.pro';
  const isUserSystemAdmin = (userId: string): boolean => {
    const user = rbacUsers.find(u => u.id === userId);
    if (!user) return false;
    return user.email?.toLowerCase() === SYSTEM_SUPER_ADMIN_EMAIL.toLowerCase();
  };

  const handleInitRbac = async () => {
    try {
      await rbacApi.initRbac();
      setRbacMessage({ type: 'success', text: 'RBAC初始化成功' });
      loadRbacData();
    } catch (e: unknown) {
      setRbacMessage({ type: 'error', text: e instanceof Error ? e.message : '初始化失败' });
    }
  };

  const toggleCategory = (category: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const permissionsByCategory = rbacPermissions.reduce<Record<string, RbacPermission[]>>((acc, perm) => {
    if (!acc[perm.category]) acc[perm.category] = [];
    acc[perm.category].push(perm);
    return acc;
  }, {});

  const selectedRole = rbacRoles.find(r => r.id === selectedRoleId);
  const selectedRolePermissionIds = new Set((selectedRole?.permissions || []).map(p => p.id));

  const renderLLMTab = () => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Cpu size={16} color="var(--color-primary)" />
              我的 LLM 配置
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
              支持配置多个供应商 / 多个 Key，可设置一个为默认
            </p>
          </div>
          <button
            onClick={handleOpenCreateConfig}
            style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 500 }}
          >
            <Plus size={13} /> 新增配置
          </button>
        </div>

        {testResult && (
          <div style={{
            marginBottom: '12px',
            padding: '8px 12px',
            borderRadius: '6px',
            background: testResult.success ? '#ecfdf5' : '#fef2f2',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            {testResult.success ? <CheckCircle2 size={16} color="#059669" /> : <XCircle size={16} color="#dc2626" />}
            <span style={{ fontSize: '12px', color: testResult.success ? '#059669' : '#dc2626', flex: 1 }}>{testResult.message}</span>
            <button onClick={() => setTestResult(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px', color: '#94a3b8' }}>
              <X size={14} />
            </button>
          </div>
        )}

        {llmConfigsLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '40px', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> 加载配置中...
          </div>
        ) : llmConfigs.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
            <Cpu size={36} style={{ marginBottom: '8px', opacity: 0.3 }} />
            <div style={{ fontSize: '14px', marginBottom: '4px' }}>尚未配置任何 LLM</div>
            <div style={{ fontSize: '12px', color: '#94a3b8' }}>点击右上角"新增配置"添加您的第一个 LLM</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {llmConfigs.map(cfg => {
              const providerName = providers.find(p => p.id === cfg.provider_id)?.name || cfg.provider_id;
              const isRevealed = llmConfigRevealed[cfg.id] !== undefined;
              return (
                <div
                  key={cfg.id}
                  style={{
                    border: `1px solid ${cfg.is_default ? 'var(--color-primary)' : 'var(--color-border)'}`,
                    borderRadius: '10px',
                    background: cfg.is_default ? '#f0f7ff' : 'white',
                    padding: '14px 16px',
                    opacity: cfg.enabled ? 1 : 0.65,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--color-text)' }}>
                          {cfg.display_name || providerName}
                        </span>
                        <span style={{ fontSize: '11px', padding: '1px 6px', background: '#f1f5f9', color: '#475569', borderRadius: '4px' }}>
                          {providerName}
                        </span>
                        {cfg.is_default && (
                          <span style={{ fontSize: '10px', padding: '1px 6px', background: 'var(--color-primary)', color: 'white', borderRadius: '4px', fontWeight: 500 }}>
                            ★ 默认
                          </span>
                        )}
                        {!cfg.enabled && (
                          <span style={{ fontSize: '10px', padding: '1px 6px', background: '#fee2e2', color: '#b91c1c', borderRadius: '4px' }}>
                            已停用
                          </span>
                        )}
                      </div>
                      {cfg.display_name && (
                        <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{providerName}</div>
                      )}
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ color: 'var(--color-text-secondary)', minWidth: '72px' }}>API Key:</span>
                      <code style={{ background: '#f8fafc', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {isRevealed ? llmConfigRevealed[cfg.id] : cfg.api_key_masked || '未设置'}
                      </code>
                      <button
                        onClick={async () => {
                          if (isRevealed) {
                            setLlmConfigRevealed(prev => { const n = { ...prev }; delete n[cfg.id]; return n; });
                          } else {
                            try {
                              const res = await llmApi.revealConfigKey(cfg.id);
                              setLlmConfigRevealed(prev => ({ ...prev, [cfg.id]: res.data.api_key || '' }));
                            } catch (e) {
                              console.error('获取 Key 明文失败', e);
                            }
                          }
                        }}
                        style={{ background: 'none', border: '1px solid var(--color-border)', borderRadius: '4px', padding: '2px 6px', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                        title={isRevealed ? '隐藏 Key' : '显示 Key'}
                      >
                        {isRevealed ? <EyeOff size={12} /> : <Eye size={12} />}
                      </button>
                    </div>
                    {cfg.default_model && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ color: 'var(--color-text-secondary)', minWidth: '72px' }}>默认模型:</span>
                        <code style={{ background: '#f0f9ff', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', color: '#1a56db' }}>{cfg.default_model}</code>
                      </div>
                    )}
                    {cfg.api_base && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ color: 'var(--color-text-secondary)', minWidth: '72px' }}>API Base:</span>
                        <span style={{ fontSize: '11px', color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cfg.api_base}</span>
                      </div>
                    )}
                    {cfg.note && (
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                        <span style={{ color: 'var(--color-text-secondary)', minWidth: '72px' }}>备注:</span>
                        <span style={{ fontSize: '11px', color: '#64748b' }}>{cfg.note}</span>
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', gap: '6px', marginTop: '12px', paddingTop: '10px', borderTop: '1px dashed var(--color-border)' }}>
                    {!cfg.is_default && cfg.enabled && (
                      <button
                        onClick={() => handleSetDefaultConfig(cfg.id)}
                        style={{ padding: '4px 10px', background: '#eff6ff', color: '#1a56db', border: '1px solid #bfdbfe', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                        title="设为默认"
                      >
                        <CheckCircle2 size={11} /> 设为默认
                      </button>
                    )}
                    <button
                      onClick={() => handleTestConfig(cfg)}
                      style={{ padding: '4px 10px', background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                      title="测试连接"
                    >
                      <Zap size={11} /> 测试
                    </button>
                    <button
                      onClick={() => handleOpenEditConfig(cfg)}
                      style={{ padding: '4px 10px', background: '#f8fafc', color: '#475569', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                      title="编辑"
                    >
                      <Edit2 size={11} /> 编辑
                    </button>
                    <button
                      onClick={() => handleDeleteConfig(cfg.id)}
                      style={{ padding: '4px 10px', background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px', marginLeft: 'auto' }}
                      title="删除"
                    >
                      <Trash2 size={11} /> 删除
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>支持的供应商</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {providers.map(p => (
              <div
                key={p.id}
                style={{
                  padding: '10px 12px',
                  border: '1px solid var(--color-border)',
                  borderRadius: '8px',
                  background: 'white',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontSize: '10px', color: '#94a3b8', padding: '1px 6px', background: '#f1f5f9', borderRadius: '4px' }}>
                    {(llmConfigs.filter(c => c.provider_id === p.id).length) > 0 ? `${llmConfigs.filter(c => c.provider_id === p.id).length} 个配置` : '未配置'}
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                  {providerApiBases[p.id] || ''}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '6px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {p.models.map(m => (
                    <span key={m} style={{ padding: '1px 6px', background: '#f0f9ff', borderRadius: '4px', fontSize: '11px' }}>{m}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {tokenUsage && (
          <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--color-border)' }}>
            <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>Token 使用统计</h4>
            <pre style={{ fontSize: '11px', margin: 0, overflow: 'auto', maxHeight: '180px' }}>{JSON.stringify(tokenUsage, null, 2)}</pre>
          </div>
        )}
      </div>

      {llmConfigDialog.open && (
        <div
          onClick={() => setLlmConfigDialog(prev => ({ ...prev, open: false }))}
          style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: 'white', borderRadius: '12px', padding: '24px', width: '520px', maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600 }}>
                {llmConfigDialog.mode === 'create' ? '新增 LLM 配置' : '编辑 LLM 配置'}
              </h3>
              <button onClick={() => setLlmConfigDialog(prev => ({ ...prev, open: false }))} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}>
                <X size={18} color="#94a3b8" />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>供应商</label>
                <select
                  value={llmConfigDialog.providerId}
                  disabled={llmConfigDialog.mode === 'edit'}
                  onChange={(e) => {
                    const pid = e.target.value;
                    setLlmConfigDialog(prev => ({
                      ...prev,
                      providerId: pid,
                      apiBase: providerApiBases[pid] || prev.apiBase,
                    }));
                  }}
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', background: llmConfigDialog.mode === 'edit' ? '#f1f5f9' : 'white' }}
                >
                  {providers.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                {llmConfigDialog.mode === 'edit' && (
                  <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>编辑模式下不可修改供应商</div>
                )}
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  显示名称 <span style={{ color: '#94a3b8' }}>(选填)</span>
                </label>
                <input
                  type="text"
                  value={llmConfigDialog.displayName}
                  onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, displayName: e.target.value }))}
                  placeholder="如: 硅基流动-主账号"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  API Key <span style={{ color: '#dc2626' }}>*</span>
                </label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <input
                    type={llmConfigDialog.showKey ? 'text' : 'password'}
                    value={llmConfigDialog.apiKey}
                    onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, apiKey: e.target.value }))}
                    placeholder={llmConfigDialog.mode === 'edit' ? '留空保留原 Key' : '请输入 API Key'}
                    style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <button
                    type="button"
                    onClick={() => setLlmConfigDialog(prev => ({ ...prev, showKey: !prev.showKey }))}
                    style={{ padding: '8px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer' }}
                    title={llmConfigDialog.showKey ? '隐藏' : '显示'}
                  >
                    {llmConfigDialog.showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>API Base URL</label>
                <input
                  type="text"
                  value={llmConfigDialog.apiBase}
                  onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, apiBase: e.target.value }))}
                  placeholder="https://..."
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>默认模型</label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <input
                    type="text"
                    value={llmConfigDialog.defaultModel}
                    onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, defaultModel: e.target.value }))}
                    placeholder={llmConfigDialog.providerId === 'siliconflow' ? '如: deepseek-ai/DeepSeek-V3' : '如: deepseek-chat'}
                    style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) {
                        setLlmConfigDialog(prev => ({ ...prev, defaultModel: e.target.value }));
                      }
                    }}
                    style={{ padding: '8px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '12px', background: 'white', maxWidth: '150px' }}
                  >
                    <option value="">预设模型...</option>
                    {providers.find(p => p.id === llmConfigDialog.providerId)?.models.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>
                  备注 <span style={{ color: '#94a3b8' }}>(选填)</span>
                </label>
                <input
                  type="text"
                  value={llmConfigDialog.note}
                  onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, note: e.target.value }))}
                  placeholder="如: 备用账号 / 项目A专用"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box' }}
                />
              </div>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={llmConfigDialog.enabled}
                  onChange={(e) => setLlmConfigDialog(prev => ({ ...prev, enabled: e.target.checked }))}
                  style={{ width: '14px', height: '14px', cursor: 'pointer' }}
                />
                启用此配置
              </label>
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '20px' }}>
              <button
                onClick={() => setLlmConfigDialog(prev => ({ ...prev, open: false }))}
                style={{ padding: '6px 14px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
              >
                取消
              </button>
              <button
                onClick={handleSaveConfig}
                disabled={llmConfigSaving || (llmConfigDialog.mode === 'create' && !llmConfigDialog.apiKey)}
                style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: llmConfigSaving ? 'not-allowed' : 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px', opacity: llmConfigSaving ? 0.6 : 1 }}
              >
                {llmConfigSaving ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={13} />}
                {llmConfigSaving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderAgentsTab = () => (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>多智能体模型配置</h3>
          <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>为不同的Agent配置不同的模型，优化各环节效果</p>
        </div>
        <button
          onClick={handleResetAgents}
          disabled={agentsLoading}
          style={{ padding: '6px 14px', background: '#fffbeb', color: '#d97706', border: '1px solid #fde68a', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
        >
          <RotateCcw size={13} /> 重置全部
        </button>
      </div>

      {agentsMessage && (
        <div style={{
          marginBottom: '12px',
          padding: '8px 12px',
          borderRadius: '6px',
          fontSize: '13px',
          background: agentsMessage.type === 'success' ? '#ecfdf5' : '#fef2f2',
          color: agentsMessage.type === 'success' ? '#059669' : '#dc2626',
        }}>
          {agentsMessage.text}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '20px' }}>
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '16px', border: '1px solid var(--color-border)' }}>
          <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '10px', color: 'var(--color-text-secondary)' }}>Agent 列表</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {agents.map(agent => (
              <div
                key={agent.name}
                onClick={() => setExpandedAgent(agent.name)}
                style={{
                  padding: '8px 10px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: expandedAgent === agent.name ? '#eff6ff' : 'transparent',
                  borderLeft: expandedAgent === agent.name ? '3px solid var(--color-primary)' : '3px solid transparent',
                  opacity: agent.enabled ? 1 : 0.5,
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Bot size={13} color={agent.enabled ? 'var(--color-primary)' : '#9ca3af'} />
                  {agent.display_name}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px', paddingLeft: '19px' }}>
                  {agent.model || '使用默认模型'}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          {agents.filter(a => a.name === expandedAgent).map(agent => (
            <div key={agent.name}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                  <h3 style={{ fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Bot size={20} color="var(--color-primary)" />
                    {agent.display_name}
                  </h3>
                  <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>{agent.description}</p>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px' }}>
                    <input
                      type="checkbox"
                      checked={agent.enabled}
                      onChange={(e) => handleAgentChange(agent.name, 'enabled', e.target.checked)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                    启用
                  </label>
                  <button
                    onClick={() => handleSaveAgent(agent)}
                    disabled={agentsSaving === agent.name}
                    style={{
                      padding: '6px 14px',
                      background: agentsSaving === agent.name ? '#94a3b8' : '#059669',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: agentsSaving === agent.name ? 'not-allowed' : 'pointer',
                      fontSize: '13px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Save size={13} /> {agentsSaving === agent.name ? '保存中...' : '保存'}
                  </button>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>使用模型</label>
                    {defaultLlmConfig && (
                      <span style={{ fontSize: '10px', color: '#94a3b8' }}>
                        LLM 默认：{defaultLlmModelLabel}
                      </span>
                    )}
                  </div>

                  <select
                    value={agent.model}
                    onChange={(e) => handleAgentChange(agent.name, 'model', e.target.value)}
                    disabled={agentModelOptions.length === 0}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      border: '1px solid var(--color-border)',
                      borderRadius: '6px',
                      fontSize: '14px',
                      background: agentModelOptions.length === 0 ? '#f1f5f9' : 'white',
                      cursor: agentModelOptions.length === 0 ? 'not-allowed' : 'pointer',
                    }}
                  >
                    <option value="">-- 使用 LLM 供应商默认（{defaultLlmConfig ? defaultLlmConfig.default_model : '未配置'}）--</option>
                    {agentModelOptions.map(opt => (
                      <option key={opt.configId} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>

                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                    {agentModelOptions.length === 0 ? (
                      <span style={{ color: '#dc2626' }}>
                        暂无可用模型，请先到「LLM 供应商」配置并启用至少一个 LLM。
                      </span>
                    ) : (
                      <>
                        当前: <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>
                          {agent.model
                            ? agentModelOptions.find(o => o.value === agent.model)?.label || agent.model
                            : `使用 LLM 默认 · ${defaultLlmModelLabel || '未设置'}`}
                        </code>
                        {agent.model && (
                          <button
                            onClick={() => handleAgentChange(agent.name, 'model', '')}
                            style={{ marginLeft: '6px', fontSize: '11px', color: '#dc2626', background: 'none', border: 'none', cursor: 'pointer' }}
                          >
                            清除
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>Temperature</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={agent.temperature}
                      onChange={(e) => handleAgentChange(agent.name, 'temperature', parseFloat(e.target.value))}
                      style={{ flex: 1 }}
                    />
                    <span style={{ fontSize: '14px', fontWeight: 600, minWidth: '32px', textAlign: 'center' }}>{agent.temperature}</span>
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                    低值=精确稳定，高值=创意多样
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>最大Token数</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <select
                      value={[1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072].includes(agent.max_tokens) ? agent.max_tokens : 'custom'}
                      onChange={(e) => {
                        if (e.target.value !== 'custom') {
                          handleAgentChange(agent.name, 'max_tokens', parseInt(e.target.value));
                        }
                      }}
                      style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}
                    >
                      <option value={1024}>1,024</option>
                      <option value={2048}>2,048</option>
                      <option value={4096}>4,096</option>
                      <option value={8192}>8,192</option>
                      <option value={16384}>16,384</option>
                      <option value={32768}>32,768</option>
                      <option value={65536}>65,536</option>
                      <option value={131072}>131,072</option>
                      <option value="custom">自定义...</option>
                    </select>
                    {![1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072].includes(agent.max_tokens) && (
                      <input
                        type="number"
                        value={agent.max_tokens}
                        onChange={(e) => handleAgentChange(agent.name, 'max_tokens', parseInt(e.target.value) || 4096)}
                        min={256}
                        max={200000}
                        style={{ width: '100px', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
                      />
                    )}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                    不同模型支持的最大值不同，超出会被自动截断
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>Agent名称</label>
                  <input
                    type="text"
                    value={agent.display_name}
                    onChange={(e) => handleAgentChange(agent.name, 'display_name', e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                </div>
              </div>

              <div style={{ marginTop: '20px', padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                <h4 style={{ fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: 'var(--color-text-secondary)' }}>配置建议</h4>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', lineHeight: '1.8' }}>
                  {agent.name === 'interpret' && '招标解读需要精确提取信息，建议使用强推理模型(如deepseek-reasoner)，Temperature设为0.1-0.3'}
                  {agent.name === 'outline' && '大纲生成需要结构化思维，建议使用中等Temperature，模型可选qwen-max或glm-4-plus'}
                  {agent.name === 'content' && '内容生成需要创意和丰富度，建议使用高Temperature(0.6-0.8)，模型可选deepseek-chat或qwen-max'}
                  {agent.name === 'check' && '质量检查需要精确判断，建议使用低Temperature(0.1-0.2)，模型可选deepseek-chat或gpt-4o'}
                  {agent.name === 'format' && '格式排版为规则性任务，建议使用最低Temperature，模型可选任意稳定模型'}
                  {agent.name === 'final_check' && '终审需要全面严谨，建议使用强推理模型，Temperature设为0.1'}
                  {agent.name === 'export' && '导出为确定性任务，Temperature设为0即可，模型可选任意稳定模型'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const renderRbacTab = () => (
    <div>
      {rbacLoading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
          <Loader2 size={14} className="animate-spin" /> 加载中...
        </div>
      )}

      {rbacMessage && (
        <div style={{
          marginBottom: '12px',
          padding: '8px 12px',
          borderRadius: '6px',
          fontSize: '13px',
          background: rbacMessage.type === 'success' ? '#ecfdf5' : '#fef2f2',
          color: rbacMessage.type === 'success' ? '#059669' : '#dc2626',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>{rbacMessage.text}</span>
          <button onClick={() => setRbacMessage(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}>
            <X size={14} />
          </button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '20px', marginBottom: '24px' }}>
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '16px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-secondary)' }}>角色列表</h4>
            <button
              onClick={() => setShowCreateRoleDialog(true)}
              style={{ padding: '4px 10px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Plus size={12} /> 新建角色
            </button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {rbacRoles.map(role => (
              <div
                key={role.id}
                onClick={() => setSelectedRoleId(role.id)}
                style={{
                  padding: '8px 10px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: selectedRoleId === role.id ? '#eff6ff' : 'transparent',
                  borderLeft: selectedRoleId === role.id ? '3px solid var(--color-primary)' : '3px solid transparent',
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Shield size={13} color={selectedRoleId === role.id ? 'var(--color-primary)' : '#64748b'} />
                  {role.display_name}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px', paddingLeft: '19px' }}>
                  {role.description || '无描述'} · {(role.permissions || []).length}项权限
                </div>
              </div>
            ))}
            {rbacRoles.length === 0 && (
              <div style={{ textAlign: 'center', padding: '20px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                暂无角色
                <button
                  onClick={handleInitRbac}
                  style={{ display: 'block', margin: '8px auto 0', padding: '4px 12px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  初始化默认角色
                </button>
              </div>
            )}
          </div>
        </div>

        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          {selectedRole ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>角色名称</label>
                    <input
                      type="text"
                      value={selectedRole.display_name}
                      onChange={(e) => {
                        setRbacRoles(prev => prev.map(r => r.id === selectedRole.id ? { ...r, display_name: e.target.value } : r));
                      }}
                      style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>角色描述</label>
                    <input
                      type="text"
                      value={selectedRole.description}
                      onChange={(e) => {
                        setRbacRoles(prev => prev.map(r => r.id === selectedRole.id ? { ...r, description: e.target.value } : r));
                      }}
                      style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', marginLeft: '12px', flexShrink: 0 }}>
                  <button
                    onClick={() => handleUpdateRole(selectedRole)}
                    style={{ padding: '6px 14px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <Save size={13} /> 保存
                  </button>
                  <button
                    onClick={() => handleDeleteRole(selectedRole.id)}
                    style={{ padding: '6px 14px', background: '#dc2626', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <Trash2 size={13} /> 删除
                  </button>
                </div>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px' }}>权限配置</h4>
                <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', overflow: 'hidden' }}>
                  {Object.entries(permissionsByCategory).map(([category, perms]) => (
                    <div key={category}>
                      <div
                        onClick={() => toggleCategory(category)}
                        style={{
                          padding: '10px 12px',
                          background: '#f8fafc',
                          borderBottom: '1px solid var(--color-border)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          fontSize: '13px',
                          fontWeight: 600,
                        }}
                      >
                        {expandedCategories.has(category) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        {category}
                        <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', fontWeight: 400 }}>
                          ({perms.filter(p => selectedRolePermissionIds.has(p.id)).length}/{perms.length})
                        </span>
                      </div>
                      {expandedCategories.has(category) && (
                        <div style={{ padding: '8px 12px 8px 32px', borderBottom: '1px solid var(--color-border)' }}>
                          {perms.map(perm => (
                            <label
                              key={perm.id}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                padding: '4px 0',
                                cursor: 'pointer',
                                fontSize: '13px',
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={selectedRolePermissionIds.has(perm.id)}
                                onChange={() => handleTogglePermission(selectedRole.id, perm.id, selectedRolePermissionIds.has(perm.id))}
                                style={{ width: '15px', height: '15px', cursor: 'pointer' }}
                              />
                              <span>{perm.name}</span>
                              <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>- {perm.description}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {Object.keys(permissionsByCategory).length === 0 && (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                      暂无权限数据
                    </div>
                  )}
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px' }}>
                  <Users size={14} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                  拥有此角色的用户 ({(selectedRole.users || []).length})
                </h4>
                {(selectedRole.users || []).length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {(selectedRole.users || []).map(user => (
                      <div
                        key={user.id}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          padding: '8px 12px',
                          border: '1px solid var(--color-border)',
                          borderRadius: '6px',
                          fontSize: '13px',
                        }}
                      >
                        <div>
                          <span style={{ fontWeight: 500 }}>{user.name}</span>
                          <span style={{ color: 'var(--color-text-secondary)', marginLeft: '8px', fontSize: '12px' }}>{user.email}</span>
                        </div>
                        <button
                          onClick={() => handleRemoveRoleFromUser(user.id, selectedRole.id)}
                          style={{ background: 'none', border: '1px solid #fca5a5', color: '#dc2626', borderRadius: '4px', cursor: 'pointer', padding: '2px 8px', fontSize: '12px' }}
                        >
                          移除
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', padding: '16px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                    暂无用户拥有此角色
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '60px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              <Shield size={40} style={{ marginBottom: '12px', opacity: 0.3 }} />
              <div>请从左侧选择一个角色查看详情</div>
            </div>
          )}
        </div>
      </div>

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Users size={18} /> 用户管理
          </h3>
          <button
            onClick={() => setShowCreateUserDialog(true)}
            style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <UserPlus size={14} /> 新建用户
          </button>
        </div>

        {rbacUsers.length > 0 ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 600, color: 'var(--color-text-secondary)', fontSize: '12px' }}>姓名</th>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 600, color: 'var(--color-text-secondary)', fontSize: '12px' }}>邮箱</th>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 600, color: 'var(--color-text-secondary)', fontSize: '12px' }}>角色</th>
                <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 600, color: 'var(--color-text-secondary)', fontSize: '12px' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {rbacUsers.map(user => (
                <tr key={user.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 500 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {isUserSystemAdmin(user.id) && (
                        <span
                          title="系统初始化生成的超级管理员，自带所有权限，不可修改"
                          style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', padding: '1px 6px', background: '#fef3c7', color: '#b45309', borderRadius: '6px', fontSize: '10px', fontWeight: 600 }}
                        >
                          <Shield size={10} /> 超管
                        </span>
                      )}
                      {user.name}
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px', color: 'var(--color-text-secondary)' }}>{user.email}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      {(user.roles || []).map(role => (
                        <span key={role.id} style={{ padding: '2px 8px', background: '#eff6ff', color: '#1a56db', borderRadius: '10px', fontSize: '11px' }}>
                          {role.display_name}
                        </span>
                      ))}
                      {(user.roles || []).length === 0 && (
                        <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>无角色</span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                    <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                      <button
                        onClick={() => {
                          setAssignRoleDialog({ userId: user.id, userName: user.name, roleIds: [] });
                        }}
                        disabled={isUserSystemAdmin(user.id)}
                        style={{
                          padding: '4px 10px',
                          background: isUserSystemAdmin(user.id) ? '#f1f5f9' : '#eff6ff',
                          color: isUserSystemAdmin(user.id) ? '#94a3b8' : '#1a56db',
                          border: '1px solid',
                          borderColor: isUserSystemAdmin(user.id) ? '#e2e8f0' : '#bfdbfe',
                          borderRadius: '4px',
                          cursor: isUserSystemAdmin(user.id) ? 'not-allowed' : 'pointer',
                          fontSize: '12px',
                          display: 'inline-flex', alignItems: 'center', gap: '3px',
                          opacity: isUserSystemAdmin(user.id) ? 0.6 : 1,
                        }}
                        title={isUserSystemAdmin(user.id) ? '系统默认管理员已具备所有权限，无需分配角色' : '为该用户分配角色'}
                      >
                        <UserPlus size={11} /> 分配角色
                      </button>
                      <button
                        onClick={() => {
                          setEditingUserId(user.id);
                          setEditUserName(user.name);
                          setEditUserEmail(user.email);
                        }}
                        style={{ padding: '4px 10px', background: '#f0f9ff', color: '#1a56db', border: '1px solid #bfdbfe', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                      >
                        编辑
                      </button>
                      {deleteConfirmId === user.id ? (
                        <div style={{ display: 'flex', gap: '4px' }}>
                          <button
                            onClick={() => handleDeleteUser(user.id)}
                            style={{ padding: '4px 10px', background: '#dc2626', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                          >
                            确认
                          </button>
                          <button
                            onClick={() => setDeleteConfirmId('')}
                            style={{ padding: '4px 10px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                          >
                            取消
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => {
                            if (isUserSystemAdmin(user.id)) {
                              setRbacMessage({ type: 'error', text: '系统默认管理员不可删除' });
                              return;
                            }
                            setDeleteConfirmId(user.id);
                          }}
                          disabled={isUserSystemAdmin(user.id)}
                          style={{
                            padding: '4px 10px',
                            background: isUserSystemAdmin(user.id) ? '#f1f5f9' : '#fef2f2',
                            color: isUserSystemAdmin(user.id) ? '#94a3b8' : '#dc2626',
                            border: '1px solid',
                            borderColor: isUserSystemAdmin(user.id) ? '#e2e8f0' : '#fecaca',
                            borderRadius: '4px',
                            cursor: isUserSystemAdmin(user.id) ? 'not-allowed' : 'pointer',
                            fontSize: '12px',
                            opacity: isUserSystemAdmin(user.id) ? 0.6 : 1,
                          }}
                          title={isUserSystemAdmin(user.id) ? '系统默认管理员不可删除' : '删除用户'}
                        >
                          删除
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
            暂无用户数据
          </div>
        )}
      </div>

      {showCreateRoleDialog && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: 'white', borderRadius: '12px', padding: '24px', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>新建角色</h3>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>角色标识 (name)</label>
              <input
                type="text"
                value={newRoleName}
                onChange={(e) => setNewRoleName(e.target.value)}
                placeholder="如: editor"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>显示名称</label>
              <input
                type="text"
                value={newRoleDisplayName}
                onChange={(e) => setNewRoleDisplayName(e.target.value)}
                placeholder="如: 编辑者"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>描述</label>
              <input
                type="text"
                value={newRoleDescription}
                onChange={(e) => setNewRoleDescription(e.target.value)}
                placeholder="角色描述"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setShowCreateRoleDialog(false); setNewRoleName(''); setNewRoleDisplayName(''); setNewRoleDescription(''); }}
                style={{ padding: '6px 14px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
              >
                取消
              </button>
              <button
                onClick={handleCreateRole}
                disabled={!newRoleName || !newRoleDisplayName}
                style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: !newRoleName || !newRoleDisplayName ? 'not-allowed' : 'pointer', fontSize: '13px' }}
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {showCreateUserDialog && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: 'white', borderRadius: '12px', padding: '24px', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>新建用户</h3>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>姓名</label>
              <input
                type="text"
                value={newUserName}
                onChange={(e) => setNewUserName(e.target.value)}
                placeholder="用户姓名"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>邮箱</label>
              <input
                type="email"
                value={newUserEmail}
                onChange={(e) => setNewUserEmail(e.target.value)}
                placeholder="user@example.com"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>密码</label>
              <input
                type="password"
                value={newUserPassword}
                onChange={(e) => setNewUserPassword(e.target.value)}
                placeholder="设置密码"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setShowCreateUserDialog(false); setNewUserName(''); setNewUserEmail(''); setNewUserPassword(''); }}
                style={{ padding: '6px 14px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
              >
                取消
              </button>
              <button
                onClick={handleCreateUser}
                disabled={!newUserName || !newUserEmail || !newUserPassword}
                style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: !newUserName || !newUserEmail || !newUserPassword ? 'not-allowed' : 'pointer', fontSize: '13px' }}
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {assignRoleDialog && (() => {
        const user = rbacUsers.find(u => u.id === assignRoleDialog.userId);
        const assignedRoleIds = new Set((user?.roles || []).map(r => r.id));
        const availableRoles = rbacRoles.filter(r => !assignedRoleIds.has(r.id));
        return (
          <div
            onClick={() => setAssignRoleDialog(null)}
            style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{ background: 'white', borderRadius: '12px', padding: '24px', width: '480px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}
            >
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '4px' }}>为「{assignRoleDialog.userName}」分配角色</h3>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '16px' }}>
                {user?.email}
              </p>

              {(user?.roles || []).length > 0 && (
                <div style={{ marginBottom: '16px' }}>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '6px' }}>已分配角色：</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {(user?.roles || []).map(r => (
                      <span key={r.id} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 8px', background: '#eff6ff', color: '#1a56db', borderRadius: '10px', fontSize: '11px' }}>
                        {r.display_name}
                        <button
                          onClick={async () => {
                            await handleRemoveRoleFromUser(user!.id, r.id);
                          }}
                          style={{ background: 'none', border: 'none', color: '#1a56db', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center' }}
                          title="移除该角色"
                        >
                          <X size={11} />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '6px' }}>选择要分配的角色（可多选）：</div>
              {availableRoles.length === 0 ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--color-text-secondary)', fontSize: '12px', background: '#f8fafc', borderRadius: '6px', marginBottom: '12px' }}>
                  没有可分配的角色（已分配所有角色或系统中尚无角色）。请先到「角色管理」创建角色。
                </div>
              ) : (
                <div style={{ maxHeight: '280px', overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: '6px', marginBottom: '12px' }}>
                  {availableRoles.map(role => {
                    const checked = assignRoleDialog.roleIds.includes(role.id);
                    return (
                      <label
                        key={role.id}
                        style={{
                          display: 'flex', alignItems: 'flex-start', gap: '8px', padding: '10px 12px',
                          cursor: 'pointer', borderBottom: '1px solid #f1f5f9',
                          background: checked ? '#eff6ff' : 'white',
                        }}
                        onMouseEnter={(e) => { if (!checked) (e.currentTarget as HTMLLabelElement).style.background = '#f8fafc'; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLLabelElement).style.background = checked ? '#eff6ff' : 'white'; }}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => {
                            const next = checked
                              ? assignRoleDialog.roleIds.filter(id => id !== role.id)
                              : [...assignRoleDialog.roleIds, role.id];
                            setAssignRoleDialog({ ...assignRoleDialog, roleIds: next });
                          }}
                          style={{ marginTop: '2px' }}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '13px', fontWeight: 500 }}>{role.display_name}</div>
                          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                            {role.description || role.name}
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px' }}>
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                  已选 {assignRoleDialog.roleIds.length} 个角色
                </span>
                <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => setAssignRoleDialog(null)}
                  style={{ padding: '6px 14px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
                >
                  取消
                </button>
                <button
                  onClick={handleAssignRole}
                  disabled={assignRoleDialog.roleIds.length === 0 || availableRoles.length === 0}
                  style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: assignRoleDialog.roleIds.length === 0 || availableRoles.length === 0 ? 'not-allowed' : 'pointer', fontSize: '13px', opacity: assignRoleDialog.roleIds.length === 0 || availableRoles.length === 0 ? 0.5 : 1 }}
                >
                  分配 {assignRoleDialog.roleIds.length > 0 && `(${assignRoleDialog.roleIds.length})`}
                </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {editingUserId && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: 'white', borderRadius: '12px', padding: '24px', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>编辑用户</h3>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>姓名</label>
              <input
                type="text"
                value={editUserName}
                onChange={(e) => setEditUserName(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>邮箱</label>
              <input
                type="email"
                value={editUserEmail}
                onChange={(e) => setEditUserEmail(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setEditingUserId('')}
                style={{ padding: '6px 14px', background: '#f1f5f9', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
              >
                取消
              </button>
              <button
                onClick={handleUpdateUser}
                style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderSkillsTab = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
      <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>已注册 Skill ({skills.length})</h3>
      {skills.length === 0 ? (
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '13px' }}>暂无注册的 Skill</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          {skills.map((skill, i) => (
            <div
              key={i}
              style={{
                padding: '10px 12px',
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600 }}>{(skill as Record<string, unknown>).name as string || '-'}</div>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>{(skill as Record<string, unknown>).description as string || '-'}</div>
              </div>
              <span style={{
                fontSize: '11px',
                padding: '2px 8px',
                borderRadius: '10px',
                background: '#eff6ff',
                color: '#1a56db',
              }}>
                {(skill as Record<string, unknown>).category as string || '-'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderMineruTab = () => {
    const isCloud = mineruConfig.mode === 'cloud';
    return (
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <ScanLine size={18} color="var(--color-primary)" />
            <h3 style={{ fontSize: '16px', fontWeight: 600 }}>MinerU OCR 配置</h3>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '16px', lineHeight: 1.6 }}>
            MinerU 用于从扫描件 PDF、扫描图片、复杂版面文档中抽取结构化文字与表格。配置后可被解读、生成、检查等流程调用。
          </p>

          {mineruLoading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
              <Loader2 size={14} className="animate-spin" /> 加载中...
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>接入方式</label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <div
                    onClick={() => setMineruConfig(prev => ({ ...prev, mode: 'cloud', endpoint: 'https://mineru.net/api/v4' }))}
                    style={{
                      padding: '10px 12px',
                      border: `2px solid ${isCloud ? 'var(--color-primary)' : 'var(--color-border)'}`,
                      borderRadius: '8px',
                      cursor: 'pointer',
                      background: isCloud ? '#eff6ff' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <Cloud size={14} color={isCloud ? 'var(--color-primary)' : '#94a3b8'} />
                    <span style={{ fontSize: '13px', fontWeight: 500 }}>云端 SaaS</span>
                  </div>
                  <div
                    onClick={() => setMineruConfig(prev => ({ ...prev, mode: 'self_hosted' }))}
                    style={{
                      padding: '10px 12px',
                      border: `2px solid ${!isCloud ? 'var(--color-primary)' : 'var(--color-border)'}`,
                      borderRadius: '8px',
                      cursor: 'pointer',
                      background: !isCloud ? '#eff6ff' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <Server size={14} color={!isCloud ? 'var(--color-primary)' : '#94a3b8'} />
                    <span style={{ fontSize: '13px', fontWeight: 500 }}>自部署 (OpenAPI)</span>
                  </div>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>
                  {isCloud ? 'API Key' : 'API Key (可选)'}
                  {mineruConfig.api_key_masked && !mineruConfig.api_key && (
                    <span style={{ marginLeft: '8px', fontSize: '11px', color: '#94a3b8' }}>已配置: {mineruConfig.api_key_masked}</span>
                  )}
                </label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    type={showMineruKey ? 'text' : 'password'}
                    value={mineruConfig.api_key}
                    onChange={(e) => setMineruConfig(prev => ({ ...prev, api_key: e.target.value }))}
                    placeholder={isCloud ? 'MinerU 云端 API Key (eyJ...)' : 'Bearer Token (如启用鉴权)'}
                    style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <button
                    onClick={() => setShowMineruKey(!showMineruKey)}
                    type="button"
                    style={{ padding: '8px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer' }}
                    title={showMineruKey ? '隐藏' : '显示'}
                  >
                    {showMineruKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                  {isCloud ? '在 mineru.net 控制台 → API Token 获取' : '如自部署服务无需鉴权，可留空'}
                </div>
              </div>

              <div>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>
                  Endpoint
                </label>
                <input
                  type="text"
                  value={mineruConfig.endpoint}
                  onChange={(e) => setMineruConfig(prev => ({ ...prev, endpoint: e.target.value }))}
                  placeholder="https://mineru.net/api/v4"
                  style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                />
                <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                  {isCloud ? '云端官方 endpoint，可保持默认' : '自部署服务的根地址，如 http://10.0.0.5:8080'}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>模型版本</label>
                  <select
                    value={mineruConfig.model_version}
                    onChange={(e) => setMineruConfig(prev => ({ ...prev, model_version: e.target.value }))}
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}
                  >
                    <option value="vlm">vlm (推荐)</option>
                    <option value="pipeline">pipeline (旧版)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>超时 (秒)</label>
                  <input
                    type="number"
                    value={mineruConfig.timeout}
                    onChange={(e) => setMineruConfig(prev => ({ ...prev, timeout: Math.max(10, Math.min(1800, parseInt(e.target.value) || 180)) }))}
                    min={10}
                    max={1800}
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>轮询间隔 (秒)</label>
                  <input
                    type="number"
                    value={mineruConfig.poll_interval}
                    onChange={(e) => setMineruConfig(prev => ({ ...prev, poll_interval: Math.max(1, Math.min(60, parseInt(e.target.value) || 5)) }))}
                    min={1}
                    max={60}
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>最大轮询次数</label>
                  <input
                    type="number"
                    value={mineruConfig.max_polls}
                    onChange={(e) => setMineruConfig(prev => ({ ...prev, max_polls: Math.max(5, Math.min(600, parseInt(e.target.value) || 60)) }))}
                    min={5}
                    max={600}
                    style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={handleTestMineru}
                  disabled={mineruTesting}
                  style={{ flex: 1, padding: '10px 12px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: mineruTesting ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                >
                  {mineruTesting ? <Loader2 size={14} className="animate-spin" /> : null}
                  {mineruTesting ? '测试中...' : '测试连接'}
                </button>
                <button
                  onClick={handleSaveMineru}
                  disabled={mineruSaving}
                  style={{ flex: 1, padding: '10px 12px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: mineruSaving ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                >
                  {mineruSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {mineruSaving ? '保存中...' : '保存配置'}
                </button>
              </div>

              {mineruTestResult && (
                <div style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  background: mineruTestResult.success ? '#ecfdf5' : '#fef2f2',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}>
                  {mineruTestResult.success ? <CheckCircle2 size={16} color="#059669" /> : <XCircle size={16} color="#dc2626" />}
                  <span style={{ fontSize: '13px', color: mineruTestResult.success ? '#059669' : '#dc2626' }}>{mineruTestResult.message}</span>
                </div>
              )}

              {mineruMessage && (
                <div style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '13px',
                  background: mineruMessage.type === 'success' ? '#ecfdf5' : '#fef2f2',
                  color: mineruMessage.type === 'success' ? '#059669' : '#dc2626',
                }}>
                  {mineruMessage.text}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>使用说明</h3>
          <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', lineHeight: 1.8 }}>
            <p style={{ marginBottom: '10px' }}>
              <strong>云端模式:</strong> 适用于个人/团队轻量使用。MinerU 官方 SaaS 提供开箱即用的 PDF/图片抽取能力，按页计费。
            </p>
            <p style={{ marginBottom: '10px' }}>
              <strong>自部署模式:</strong> 适用于内网合规、敏感数据、大批量场景。需自行部署 MinerU 服务（OpenAPI 兼容），
              提交到 <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>POST {'{endpoint}/predict'}</code>，
              通过 <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>GET {'{endpoint}/tasks/{id}'}</code> 轮询。
            </p>
            <p style={{ marginBottom: '10px' }}>
              <strong>调用方式:</strong> 解读/检查流程可自动触发 OCR 抽取扫描件。当前为 skill 层注册，
              可通过 <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>POST /api/mineru/ocr</code> 上传文件直接调用。
            </p>
            <p>
              <strong>排版与导出:</strong> 在"文档输出"页面，新增 docx / doc / pdf 三种输出格式，docx 为唯一中间格式，
              doc/pdf 由 LibreOffice 实时转换导出。
            </p>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div>
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '24px', fontWeight: 700 }}>平台设置</h2>
        <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          多智能体模型配置、LLM供应商管理、权限管理、Skill管理、MinerU OCR配置
        </p>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
        {([
          { key: 'agents' as SettingsTab, label: '智能体模型配置', icon: <Bot size={14} /> },
          { key: 'llm' as SettingsTab, label: 'LLM供应商', icon: <Cpu size={14} /> },
          { key: 'mineru' as SettingsTab, label: 'MinerU OCR', icon: <ScanLine size={14} /> },
          { key: 'rbac' as SettingsTab, label: '权限管理', icon: <Shield size={14} /> },
          { key: 'skills' as SettingsTab, label: 'Skill管理', icon: <Settings size={14} /> },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px',
              background: activeTab === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
              color: activeTab === tab.key ? 'white' : 'var(--color-text)',
              border: `1px solid ${activeTab === tab.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'llm' && renderLLMTab()}
      {activeTab === 'agents' && renderAgentsTab()}
      {activeTab === 'mineru' && renderMineruTab()}
      {activeTab === 'rbac' && renderRbacTab()}
      {activeTab === 'skills' && renderSkillsTab()}
    </div>
  );
}
