import { useState, useEffect, useRef, useCallback } from 'react';
import { PenTool, Loader2, ListTree, FileText, AlertTriangle, Shield, Play, Download, ChevronRight, ChevronDown, GripVertical, Plus, Trash2, Edit3, Check, X, ImageIcon } from 'lucide-react';
import { generateApi, projectApi, aiImageApi, type Project, type OutlineNode, type GateInfo } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';

const STRUCTURE_TEMPLATES = [
  { key: 'bid_letter', label: '投标函', desc: '投标函+授权书+承诺书' },
  { key: 'qualification', label: '资格审查', desc: '营业执照+资质+业绩+人员' },
  { key: 'technical', label: '技术标', desc: '方案+实施+质量+安全+售后' },
  { key: 'commercial', label: '商务标', desc: '报价+预算+成本分析' },
  { key: 'service', label: '售后服务', desc: '服务承诺+培训+应急+质保' },
];

export default function GeneratePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [outlineResult, setOutlineResult] = useState<Record<string, unknown> | null>(null);
  const [mandatoryResult, setMandatoryResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string>('');
  const [outlineMode, setOutlineMode] = useState<string>('aligned');
  const [outlineNodes, setOutlineNodes] = useState<OutlineNode[]>([]);
  const [editingNode, setEditingNode] = useState<string | null>(null);
  const [editText, setEditText] = useState<string>('');
  const [gates, setGates] = useState<GateInfo[]>([]);
  const [streamContent, setStreamContent] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [scoreCoverage, setScoreCoverage] = useState<Record<string, unknown> | null>(null);
  const [activeSection, setActiveSection] = useState<'outline' | 'generate' | 'gate' | 'structure' | 'coverage' | 'aiimage'>('outline');
  const streamRef = useRef<EventSource | null>(null);

  const [aiImagePrompt, setAiImagePrompt] = useState('');
  const [aiImageProvider, setAiImageProvider] = useState('default');
  const [aiImageSize, setAiImageSize] = useState('landscape_16_9');
  const [aiImageLoading, setAiImageLoading] = useState(false);
  const [aiImageResult, setAiImageResult] = useState<string>('');
  const [aiImageHistory, setAiImageHistory] = useState<Array<{ prompt: string; url: string; timestamp: number }>>([]);
  const [enableIllustration, setEnableIllustration] = useState(true);
  const [removeWatermark, setRemoveWatermark] = useState(true);

  const { currentProjectId } = useAppStore();

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (currentProjectId && !selectedProjectId) {
      setSelectedProjectId(currentProjectId);
    }
  }, [currentProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      loadGates();
    }
  }, [selectedProjectId]);

  const loadProjects = async () => {
    try {
      const res = await projectApi.list();
      setProjects(res.data.projects || []);
    } catch (e) {
      console.error('加载项目列表失败', e);
    }
  };

  const loadGates = async () => {
    try {
      const res = await projectApi.listGates(selectedProjectId);
      setGates(res.data.gates || []);
    } catch (e) {
      console.error('加载闸门信息失败', e);
    }
  };

  const handleGenerateOutline = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await generateApi.generateOutline(selectedProjectId, outlineMode);
      setOutlineResult(res.data);
      const outline = res.data?.outline || res.data;
      if (Array.isArray(outline)) {
        setOutlineNodes(outline as OutlineNode[]);
      } else if (outline && typeof outline === 'object') {
        const nodes = (outline as Record<string, unknown>).chapters || (outline as Record<string, unknown>).sections || [];
        setOutlineNodes(nodes as OutlineNode[]);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '大纲生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleExtractMandatory = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await generateApi.mandatoryExtract(selectedProjectId);
      setMandatoryResult(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '提取失败');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateStructure = async (structureType: string) => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await generateApi.generateStructure(selectedProjectId, structureType);
      setOutlineResult(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '结构模板生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleScoreCoverage = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await generateApi.scoreCoverage(selectedProjectId);
      setScoreCoverage(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '覆盖率计算失败');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmGate = async (stage: string) => {
    if (!selectedProjectId) return;
    try {
      await projectApi.confirmGate(selectedProjectId, stage);
      await loadGates();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '闸门确认失败');
    }
  };

  const handleStreamGenerate = useCallback((chapterId: string, mode: string = 'A') => {
    if (!selectedProjectId) return;
    setIsStreaming(true);
    setStreamContent('');

    const url = generateApi.streamChapter(selectedProjectId, chapterId, mode);
    const eventSource = new EventSource(url);
    streamRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.content) {
          setStreamContent(prev => prev + data.content);
        }
        if (data.done) {
          eventSource.close();
          setIsStreaming(false);
          streamRef.current = null;
        }
      } catch {
        setStreamContent(prev => prev + event.data);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setIsStreaming(false);
      streamRef.current = null;
    };
  }, [selectedProjectId]);

  const handleStopStream = () => {
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
    setIsStreaming(false);
  };

  const updateNodeTitle = (nodes: OutlineNode[], nodeId: string, newTitle: string): OutlineNode[] => {
    return nodes.map(node => {
      if (node.id === nodeId) {
        return { ...node, title: newTitle };
      }
      if (node.children) {
        return { ...node, children: updateNodeTitle(node.children, nodeId, newTitle) };
      }
      return node;
    });
  };

  const removeNode = (nodes: OutlineNode[], nodeId: string): OutlineNode[] => {
    return nodes
      .filter(node => node.id !== nodeId)
      .map(node => ({
        ...node,
        children: node.children ? removeNode(node.children, nodeId) : [],
      }));
  };

  const addChildNode = (nodes: OutlineNode[], parentId: string, child: OutlineNode): OutlineNode[] => {
    return nodes.map(node => {
      if (node.id === parentId) {
        return { ...node, children: [...(node.children || []), child] };
      }
      if (node.children) {
        return { ...node, children: addChildNode(node.children, parentId, child) };
      }
      return node;
    });
  };

  const handleSaveEdit = (nodeId: string) => {
    setOutlineNodes(prev => updateNodeTitle(prev, nodeId, editText));
    setEditingNode(null);
    setEditText('');
  };

  const handleCancelEdit = () => {
    setEditingNode(null);
    setEditText('');
  };

  const renderOutlineNode = (node: OutlineNode, depth: number = 0) => {
    const isEditing = editingNode === node.id;
    const indent = depth * 24;

    return (
      <div key={node.id}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 8px',
            marginLeft: `${indent}px`,
            borderRadius: '6px',
            background: isEditing ? '#eff6ff' : 'transparent',
            border: '1px solid transparent',
            fontSize: '13px',
          }}
          onMouseEnter={(e) => {
            if (!isEditing) (e.currentTarget as HTMLDivElement).style.background = '#f8fafc';
          }}
          onMouseLeave={(e) => {
            if (!isEditing) (e.currentTarget as HTMLDivElement).style.background = 'transparent';
          }}
        >
          <GripVertical size={14} color="#94a3b8" style={{ cursor: 'grab', flexShrink: 0 }} />

          {node.children && node.children.length > 0 ? (
            <ChevronDown size={14} color="#64748b" style={{ flexShrink: 0 }} />
          ) : (
            <ChevronRight size={14} color="#cbd5e1" style={{ flexShrink: 0 }} />
          )}

          {isEditing ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flex: 1 }}>
              <input
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveEdit(node.id);
                  if (e.key === 'Escape') handleCancelEdit();
                }}
                style={{
                  flex: 1,
                  padding: '4px 8px',
                  border: '1px solid var(--color-primary)',
                  borderRadius: '4px',
                  fontSize: '13px',
                  outline: 'none',
                }}
                autoFocus
              />
              <button onClick={() => handleSaveEdit(node.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}>
                <Check size={14} color="#059669" />
              </button>
              <button onClick={handleCancelEdit} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}>
                <X size={14} color="#dc2626" />
              </button>
            </div>
          ) : (
            <>
              <span style={{ flex: 1, fontWeight: depth < 2 ? 600 : 400 }}>
                {node.title}
              </span>
              {node.score_mapping && node.score_mapping.length > 0 && (
                <span style={{ fontSize: '11px', color: '#059669', background: '#ecfdf5', padding: '2px 6px', borderRadius: '4px' }}>
                  {node.score_mapping.length}项评分
                </span>
              )}
              {node.page_target && (
                <span style={{ fontSize: '11px', color: '#475569', background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>
                  ~{node.page_target}页
                </span>
              )}
              <button
                onClick={() => { setEditingNode(node.id); setEditText(node.title); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', opacity: 0.5 }}
                title="编辑"
              >
                <Edit3 size={12} />
              </button>
              <button
                onClick={() => setOutlineNodes(prev => removeNode(prev, node.id))}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', opacity: 0.5, color: '#dc2626' }}
                title="删除"
              >
                <Trash2 size={12} />
              </button>
              <button
                onClick={() => {
                  const child: OutlineNode = {
                    id: `new_${Date.now()}`,
                    title: '新章节',
                    level: node.level + 1,
                    children: [],
                    status: 'pending',
                  };
                  setOutlineNodes(prev => addChildNode(prev, node.id, child));
                }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', opacity: 0.5, color: '#059669' }}
                title="添加子章节"
              >
                <Plus size={12} />
              </button>
            </>
          )}
        </div>
        {node.children && node.children.map(child => renderOutlineNode(child, depth + 1))}
      </div>
    );
  };

  const sectionTabs = [
    { key: 'outline', label: '大纲编辑', icon: <ListTree size={16} /> },
    { key: 'generate', label: '正文生成', icon: <PenTool size={16} /> },
    { key: 'gate', label: '闸门审核', icon: <Shield size={16} /> },
    { key: 'structure', label: '结构模板', icon: <FileText size={16} /> },
    { key: 'coverage', label: '评分覆盖', icon: <AlertTriangle size={16} /> },
  ];

  const handleGenerateAiImage = async () => {
    if (!aiImagePrompt.trim()) return;
    setAiImageLoading(true);
    setAiImageResult('');
    setError('');
    try {
      const res = await aiImageApi.generate(aiImagePrompt, aiImageProvider, aiImageSize);
      const imageUrl = res.data?.image_url || res.data?.url || '';
      setAiImageResult(imageUrl);
      if (imageUrl) {
        setAiImageHistory(prev => [{ prompt: aiImagePrompt, url: imageUrl, timestamp: Date.now() }, ...prev].slice(0, 5));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'AI配图生成失败');
    } finally {
      setAiImageLoading(false);
    }
  };

  return (
    <div className="page-fade-in">
      <StepHeader
        step={2}
        title="投标生成"
        subtitle="大纲编辑→配图设置→AI生成正文→闸门审核，全流程AI辅助"
        color="#059669"
        nextPath="/check"
        nextLabel="下一步：投标检查"
      />

      <div style={{ marginBottom: '20px' }}>
        <select
          value={selectedProjectId}
          onChange={(e) => setSelectedProjectId(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            fontSize: '14px',
            background: 'var(--color-surface)',
          }}
        >
          <option value="">请选择项目</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name} ({p.status})</option>
          ))}
        </select>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {sectionTabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveSection(tab.key as typeof activeSection)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              background: activeSection === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
              color: activeSection === tab.key ? 'white' : 'var(--color-text)',
              border: `1px solid ${activeSection === tab.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
            }}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {activeSection === 'outline' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600 }}>大纲编辑器</h3>
            <div style={{ display: 'flex', gap: '8px' }}>
              <select
                value={outlineMode}
                onChange={(e) => setOutlineMode(e.target.value)}
                style={{ padding: '6px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px' }}
              >
                <option value="aligned">对齐评分项模式</option>
                <option value="free">自由模式</option>
              </select>
              <button
                onClick={handleGenerateOutline}
                disabled={loading || !selectedProjectId}
                style={{
                  padding: '6px 14px',
                  background: 'var(--color-primary)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer',
                  fontSize: '13px',
                }}
              >
                {loading ? '生成中...' : '生成大纲'}
              </button>
              <button
                onClick={() => {
                  const newNode: OutlineNode = {
                    id: `new_${Date.now()}`,
                    title: '新章节',
                    level: 1,
                    children: [],
                    status: 'pending',
                  };
                  setOutlineNodes(prev => [...prev, newNode]);
                }}
                style={{
                  padding: '6px 14px',
                  background: '#059669',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <Plus size={14} /> 添加章节
              </button>
            </div>
          </div>

          {outlineNodes.length > 0 ? (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', padding: '12px', maxHeight: '500px', overflow: 'auto' }}>
              {outlineNodes.map(node => renderOutlineNode(node))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              {outlineResult ? '大纲数据格式不匹配，请查看原始结果' : '点击"生成大纲"开始'}
            </div>
          )}

          {outlineResult && (
            <details style={{ marginTop: '12px' }}>
              <summary style={{ fontSize: '12px', color: 'var(--color-text-secondary)', cursor: 'pointer' }}>查看原始JSON结果</summary>
              <pre style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', fontSize: '11px', overflow: 'auto', maxHeight: '200px', marginTop: '8px' }}>
                {JSON.stringify(outlineResult, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {activeSection === 'generate' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>正文生成（流式输出）</h3>

          <div style={{ padding: '16px', background: '#f0f9ff', borderRadius: '10px', border: '1px solid #bfdbfe', marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ImageIcon size={18} color="#2563eb" />
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e40af' }}>配图设置（正文生成前配置）</span>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={enableIllustration}
                  onChange={(e) => setEnableIllustration(e.target.checked)}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                启用AI配图
              </label>
            </div>

            {enableIllustration && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#1e40af', display: 'block', marginBottom: '4px' }}>配图供应商</label>
                  <select
                    value={aiImageProvider}
                    onChange={(e) => setAiImageProvider(e.target.value)}
                    style={{ width: '100%', padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }}
                  >
                    <option value="default">默认(内置)</option>
                    <option value="volcengine">火山方舟</option>
                    <option value="google">Google AI Studio</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#1e40af', display: 'block', marginBottom: '4px' }}>配图尺寸</label>
                  <select
                    value={aiImageSize}
                    onChange={(e) => setAiImageSize(e.target.value)}
                    style={{ width: '100%', padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }}
                  >
                    <option value="landscape_16_9">横版 16:9（推荐）</option>
                    <option value="landscape_4_3">横版 4:3</option>
                    <option value="portrait_4_3">竖版 4:3</option>
                    <option value="portrait_16_9">竖版 16:9</option>
                    <option value="square_hd">方形 高清</option>
                    <option value="square">方形</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#1e40af', display: 'block', marginBottom: '4px' }}>去水印</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 0' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px' }}>
                      <input
                        type="checkbox"
                        checked={removeWatermark}
                        onChange={(e) => setRemoveWatermark(e.target.checked)}
                        style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                      />
                      自动去水印
                    </label>
                    <span style={{ fontSize: '11px', color: '#6b7280' }}>
                      {removeWatermark ? '✓ 将自动检测并移除水印' : '保留原始图片'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {enableIllustration && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input
                  type="text"
                  value={aiImagePrompt}
                  onChange={(e) => setAiImagePrompt(e.target.value)}
                  placeholder="自定义配图描述（留空则根据章节标题自动生成）"
                  style={{ flex: 1, padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }}
                />
                <button
                  onClick={handleGenerateAiImage}
                  disabled={aiImageLoading || !aiImagePrompt.trim()}
                  style={{
                    padding: '6px 14px',
                    background: aiImageLoading || !aiImagePrompt.trim() ? '#94a3b8' : '#2563eb',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: aiImageLoading || !aiImagePrompt.trim() ? 'not-allowed' : 'pointer',
                    fontSize: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {aiImageLoading ? <Loader2 size={12} /> : <ImageIcon size={12} />}
                  {aiImageLoading ? '生成中...' : '预览配图'}
                </button>
              </div>
            )}

            {aiImageResult && enableIllustration && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                <img
                  src={aiImageResult}
                  alt="AI配图预览"
                  style={{ width: '200px', height: '120px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #bfdbfe' }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12px', color: '#059669', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    {removeWatermark ? '✓ 已启用去水印' : '○ 未启用去水印'}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>
                    此配图将在正文生成时自动插入到对应章节中
                  </div>
                  {aiImageHistory.length > 0 && (
                    <div style={{ marginTop: '8px', display: 'flex', gap: '6px' }}>
                      {aiImageHistory.slice(0, 4).map((item, idx) => (
                        <img
                          key={idx}
                          src={item.url}
                          alt={item.prompt}
                          onClick={() => setAiImageResult(item.url)}
                          style={{ width: '48px', height: '36px', objectFit: 'cover', borderRadius: '4px', cursor: 'pointer', border: '1px solid #bfdbfe' }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>章节ID</label>
              <input
                id="chapter-id-input"
                placeholder="输入章节ID，如 ch1"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>生成模式</label>
              <select
                id="gen-mode-select"
                style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
              >
                <option value="A">A模式(知识库+大纲)</option>
                <option value="B">B模式(纯知识库)</option>
                <option value="C">C模式(纯大纲)</option>
                <option value="D">D模式(自由生成)</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <button
              onClick={() => {
                const chapterId = (document.getElementById('chapter-id-input') as HTMLInputElement)?.value || 'ch1';
                const mode = (document.getElementById('gen-mode-select') as HTMLSelectElement)?.value || 'A';
                handleStreamGenerate(chapterId, mode);
              }}
              disabled={isStreaming || !selectedProjectId}
              style={{
                padding: '8px 16px',
                background: 'var(--color-primary)',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: isStreaming || !selectedProjectId ? 'not-allowed' : 'pointer',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <Play size={14} /> {isStreaming ? '生成中...' : '流式生成'}
            </button>
            {isStreaming && (
              <button
                onClick={handleStopStream}
                style={{
                  padding: '8px 16px',
                  background: '#dc2626',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                停止
              </button>
            )}
            <button
              onClick={handleExtractMandatory}
              disabled={loading || !selectedProjectId}
              style={{
                padding: '8px 16px',
                background: '#d97706',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer',
                fontSize: '13px',
              }}
            >
              提取实质性要求
            </button>
          </div>

          {(streamContent || isStreaming) && (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', padding: '16px', background: '#f8fafc', maxHeight: '400px', overflow: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                  {isStreaming ? '正在生成...' : '生成完成'}
                </span>
                {isStreaming && <Loader2 size={14} className="animate-spin" />}
              </div>
              <div style={{ fontSize: '14px', lineHeight: '1.8', whiteSpace: 'pre-wrap' }}>
                {streamContent}
                {isStreaming && <span style={{ animation: 'blink 1s infinite' }}>▊</span>}
              </div>
            </div>
          )}

          {mandatoryResult && (
            <div style={{ marginTop: '16px' }}>
              <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>实质性要求提取结果</h4>
              <pre style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', fontSize: '12px', overflow: 'auto', maxHeight: '300px' }}>
                {JSON.stringify(mandatoryResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {activeSection === 'gate' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>闸门审核确认</h3>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '16px' }}>
            每个阶段完成后需确认审核，通过后才能进入下一阶段
          </p>

          {gates.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {gates.map((gate, idx) => (
                <div
                  key={gate.stage}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '16px',
                    border: '1px solid var(--color-border)',
                    borderRadius: '8px',
                    background: gate.status === 'confirmed' ? '#ecfdf5' : gate.status === 'blocked' ? '#fef2f2' : '#f8fafc',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: gate.status === 'confirmed' ? '#059669' : gate.status === 'blocked' ? '#dc2626' : '#94a3b8',
                      color: 'white',
                      fontSize: '14px',
                      fontWeight: 600,
                    }}>
                      {idx + 1}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '14px' }}>{gate.label}</div>
                      {gate.items && gate.items.length > 0 && (
                        <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                          检查项: {gate.items.join('、')}
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      fontSize: '12px',
                      padding: '4px 10px',
                      borderRadius: '12px',
                      background: gate.status === 'confirmed' ? '#d1fae5' : gate.status === 'blocked' ? '#fee2e2' : '#e2e8f0',
                      color: gate.status === 'confirmed' ? '#059669' : gate.status === 'blocked' ? '#dc2626' : '#64748b',
                    }}>
                      {gate.status === 'confirmed' ? '已确认' : gate.status === 'blocked' ? '已阻断' : '待确认'}
                    </span>
                    {gate.status === 'pending' && (
                      <button
                        onClick={() => handleConfirmGate(gate.stage)}
                        style={{
                          padding: '6px 14px',
                          background: '#059669',
                          color: 'white',
                          border: 'none',
                          borderRadius: '6px',
                          cursor: 'pointer',
                          fontSize: '12px',
                        }}
                      >
                        确认通过
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              暂无闸门信息，请先生成大纲
            </div>
          )}
        </div>
      )}

      {activeSection === 'structure' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>标书5大结构模板</h3>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '16px' }}>
            自动生成标书标准结构章节，确保不遗漏任何必要部分
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
            {STRUCTURE_TEMPLATES.map(tpl => (
              <div
                key={tpl.key}
                style={{
                  padding: '16px',
                  border: '1px solid var(--color-border)',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onClick={() => handleGenerateStructure(tpl.key)}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-primary)';
                  (e.currentTarget as HTMLDivElement).style.background = '#eff6ff';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--color-border)';
                  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px' }}>{tpl.label}</div>
                <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>{tpl.desc}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeSection === 'coverage' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600 }}>评分矩阵覆盖率</h3>
            <button
              onClick={handleScoreCoverage}
              disabled={loading || !selectedProjectId}
              style={{
                padding: '6px 14px',
                background: 'var(--color-primary)',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer',
                fontSize: '13px',
              }}
            >
              {loading ? '计算中...' : '计算覆盖率'}
            </button>
          </div>

          {scoreCoverage ? (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                <div style={{ padding: '16px', background: '#ecfdf5', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: 700, color: '#059669' }}>
                    {String((scoreCoverage as Record<string, unknown>).coverage_rate || '0')}%
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>覆盖率</div>
                </div>
                <div style={{ padding: '16px', background: '#eff6ff', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: 700, color: '#2563eb' }}>
                    {String((scoreCoverage as Record<string, unknown>).covered_items || '0')}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>已覆盖评分项</div>
                </div>
                <div style={{ padding: '16px', background: '#fef2f2', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '24px', fontWeight: 700, color: '#dc2626' }}>
                    {String((scoreCoverage as Record<string, unknown>).uncovered_items || '0')}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>未覆盖评分项</div>
                </div>
              </div>
              <pre style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', fontSize: '12px', overflow: 'auto', maxHeight: '300px' }}>
                {JSON.stringify(scoreCoverage, null, 2)}
              </pre>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              点击"计算覆盖率"查看评分项覆盖情况
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px' }}>
          {error}
        </div>
      )}

      <style>{`
        @keyframes blink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
