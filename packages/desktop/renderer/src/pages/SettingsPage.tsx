import { useState, useEffect, useCallback } from 'react';
import { Settings, Loader2, CheckCircle2, XCircle, Bot, Save, RotateCcw, ChevronDown, ChevronRight, Cpu, Shield, Plus, Trash2, Users, UserPlus, X } from 'lucide-react';
import { llmApi, skillApi, rbacApi } from '../services/api';

type SettingsTab = 'agents' | 'llm' | 'rbac' | 'skills';

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

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('agents');

  const [apiKey, setApiKey] = useState('');
  const [apiBase, setApiBase] = useState('https://api.deepseek.com');
  const [model, setModel] = useState('deepseek/deepseek-chat');
  const [providers, setProviders] = useState<Array<{ id: string; name: string; models: string[] }>>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [tokenUsage, setTokenUsage] = useState<Record<string, unknown> | null>(null);
  const [savingDefault, setSavingDefault] = useState(false);

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
  const [showCreateUserDialog, setShowCreateUserDialog] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [editingUserId, setEditingUserId] = useState<string>('');
  const [editUserName, setEditUserName] = useState('');
  const [editUserEmail, setEditUserEmail] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<string>('');

  const loadData = useCallback(async () => {
    try {
      const [providersRes, skillsRes, usageRes, agentsRes] = await Promise.allSettled([
        llmApi.listProviders(),
        skillApi.list(),
        llmApi.getUsage(),
        llmApi.listAgentModels(),
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
    } catch (e) {
      console.error('加载配置失败', e);
    }
  }, [expandedAgent]);

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

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await llmApi.testConnection({
        provider: model.split('/')[0],
        api_key: apiKey,
        api_base: apiBase,
        model: model,
      });
      setTestResult({
        success: res.data.success,
        message: res.data.success ? '连接成功！' : (res.data.error || '连接失败'),
      });
    } catch (e: unknown) {
      setTestResult({
        success: false,
        message: e instanceof Error ? e.message : '连接失败',
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveDefaultModel = async () => {
    setSavingDefault(true);
    try {
      await llmApi.setDefaultModel({ model, api_key: apiKey, api_base: apiBase });
      setTestResult({ success: true, message: '默认模型配置已保存' });
    } catch (e: unknown) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setSavingDefault(false);
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

  const [selectedProviderId, setSelectedProviderId] = useState('deepseek');
  const [customModel, setCustomModel] = useState('');
  const [useCustomModel, setUseCustomModel] = useState(false);

  const [agentCustomModel, setAgentCustomModel] = useState('');
  const [agentUseCustom, setAgentUseCustom] = useState<string>('');

  const allModelOptions = providers.flatMap(p =>
    p.models.map(m => ({ value: `${p.id}/${m}`, label: `${p.name} - ${m}`, providerId: p.id }))
  );

  const providerApiBases: Record<string, string> = {
    deepseek: 'https://api.deepseek.com',
    zhipu: 'https://open.bigmodel.cn/api/paas/v4',
    qianfan: 'https://aip.baidubce.com',
    dashscope: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    siliconflow: 'https://api.siliconflow.cn/v1',
    ollama: 'http://localhost:11434',
    openai: 'https://api.openai.com/v1',
  };

  const handleProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    setApiBase(providerApiBases[providerId] || '');
    setUseCustomModel(false);
    setCustomModel('');
    const provider = providers.find(p => p.id === providerId);
    if (provider && provider.models.length > 0) {
      setModel(`${providerId}/${provider.models[0]}`);
    }
  };

  const handlePresetModelChange = (modelValue: string) => {
    setModel(modelValue);
    setUseCustomModel(false);
  };

  const handleCustomModelConfirm = () => {
    if (customModel.trim()) {
      const prefix = selectedProviderId;
      const fullModel = customModel.includes('/') ? customModel : `${prefix}/${customModel.trim()}`;
      setModel(fullModel);
    }
  };

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
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>默认LLM供应商配置</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>选择供应商</label>
            <select
              value={selectedProviderId}
              onChange={(e) => handleProviderChange(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}
            >
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>API Base URL</label>
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>模型选择</label>
              <button
                onClick={() => setUseCustomModel(!useCustomModel)}
                style={{ fontSize: '12px', color: 'var(--color-primary)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
              >
                {useCustomModel ? '选择预设模型' : '自定义模型'}
              </button>
            </div>

            {useCustomModel ? (
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="text"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCustomModelConfirm()}
                  placeholder={selectedProviderId === 'siliconflow' ? '如: deepseek-ai/DeepSeek-V3' : '输入模型名称'}
                  style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                />
                <button
                  onClick={handleCustomModelConfirm}
                  style={{ padding: '8px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
                >
                  确认
                </button>
              </div>
            ) : (
              <select
                value={model}
                onChange={(e) => handlePresetModelChange(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}
              >
                {providers.filter(p => p.id === selectedProviderId).flatMap(p =>
                  p.models.map(m => (
                    <option key={`${p.id}/${m}`} value={`${p.id}/${m}`}>
                      {m}
                    </option>
                  ))
                )}
              </select>
            )}

            <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
              当前模型: <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>{model}</code>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleTestConnection}
              disabled={testing}
              style={{ flex: 1, padding: '10px 12px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: testing ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
            >
              {testing ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : null}
              {testing ? '测试中...' : '测试连接'}
            </button>
            <button
              onClick={handleSaveDefaultModel}
              disabled={savingDefault}
              style={{ flex: 1, padding: '10px 12px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: savingDefault ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
            >
              {savingDefault ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
              {savingDefault ? '保存中...' : '保存为默认'}
            </button>
          </div>
        </div>

        {testResult && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            borderRadius: '8px',
            background: testResult.success ? '#ecfdf5' : '#fef2f2',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            {testResult.success ? <CheckCircle2 size={18} color="#059669" /> : <XCircle size={18} color="#dc2626" />}
            <span style={{ fontSize: '13px', color: testResult.success ? '#059669' : '#dc2626' }}>{testResult.message}</span>
          </div>
        )}

        {tokenUsage && (
          <div style={{ marginTop: '16px', padding: '12px', background: '#f8fafc', borderRadius: '8px' }}>
            <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>Token 使用统计</h4>
            <pre style={{ fontSize: '12px', margin: 0, overflow: 'auto' }}>{JSON.stringify(tokenUsage, null, 2)}</pre>
          </div>
        )}
      </div>

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>支持的供应商</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {providers.map(p => (
            <div
              key={p.id}
              onClick={() => handleProviderChange(p.id)}
              style={{
                padding: '12px',
                border: `1px solid ${p.id === selectedProviderId ? 'var(--color-primary)' : 'var(--color-border)'}`,
                borderRadius: '8px',
                background: p.id === selectedProviderId ? '#eff6ff' : 'white',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '13px', fontWeight: 600 }}>{p.name}</span>
                {p.id === selectedProviderId && (
                  <span style={{ fontSize: '11px', color: 'var(--color-primary)', background: '#dbeafe', padding: '1px 8px', borderRadius: '10px' }}>当前</span>
                )}
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
                    <button
                      onClick={() => {
                        if (agentUseCustom === agent.name) {
                          setAgentUseCustom('');
                        } else {
                          setAgentUseCustom(agent.name);
                          setAgentCustomModel(agent.model || '');
                        }
                      }}
                      style={{ fontSize: '12px', color: 'var(--color-primary)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    >
                      {agentUseCustom === agent.name ? '选择预设' : '自定义模型'}
                    </button>
                  </div>

                  {agentUseCustom === agent.name ? (
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        value={agentCustomModel}
                        onChange={(e) => setAgentCustomModel(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && agentCustomModel.trim()) {
                            handleAgentChange(agent.name, 'model', agentCustomModel.trim());
                          }
                        }}
                        placeholder="如: siliconflow/deepseek-ai/DeepSeek-V3"
                        style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }}
                      />
                      <button
                        onClick={() => {
                          if (agentCustomModel.trim()) {
                            handleAgentChange(agent.name, 'model', agentCustomModel.trim());
                          }
                        }}
                        style={{ padding: '8px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
                      >
                        确认
                      </button>
                    </div>
                  ) : (
                    <select
                      value={agent.model}
                      onChange={(e) => handleAgentChange(agent.name, 'model', e.target.value)}
                      style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}
                    >
                      <option value="">-- 使用默认模型 --</option>
                      {allModelOptions.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  )}

                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                    当前: <code style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: '3px' }}>{agent.model || '默认'}</code>
                    {agent.model && (
                      <button
                        onClick={() => handleAgentChange(agent.name, 'model', '')}
                        style={{ marginLeft: '6px', fontSize: '11px', color: '#dc2626', background: 'none', border: 'none', cursor: 'pointer' }}
                      >
                        清除
                      </button>
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
                  <td style={{ padding: '10px 12px', fontWeight: 500 }}>{user.name}</td>
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
                          onClick={() => setDeleteConfirmId(user.id)}
                          style={{ padding: '4px 10px', background: '#fef2f2', color: '#dc2626', border: '1px solid #fecaca', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
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

  return (
    <div>
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '24px', fontWeight: 700 }}>平台设置</h2>
        <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          多智能体模型配置、LLM供应商管理、权限管理、Skill管理
        </p>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {([
          { key: 'agents' as SettingsTab, label: '智能体模型配置', icon: <Bot size={14} /> },
          { key: 'llm' as SettingsTab, label: 'LLM供应商', icon: <Cpu size={14} /> },
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
      {activeTab === 'rbac' && renderRbacTab()}
      {activeTab === 'skills' && renderSkillsTab()}
    </div>
  );
}
