import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { PenTool, Loader2, ListTree, FileText, AlertTriangle, Shield, Play, Download, ChevronRight, ChevronDown, GripVertical, Plus, Trash2, Edit3, Check, X, ImageIcon, Copy, CheckCircle2, Info, Eye, BookOpen, Edit, ArrowRight } from 'lucide-react';
import { generateApi, projectApi, interpretApi, aiImageApi, type Project, type OutlineNode, type GateInfo, type SSEController } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';
import MarkdownRenderer from '../components/common/MarkdownRenderer';

const STRUCTURE_TEMPLATES = [
  {
    key: 'bid_letter', label: '投标函', desc: '投标函+授权书+承诺书',
    sections: [
      { title: '投标函', pages: 2, hint: '致招标人，明确投标意向、投标总价、工期承诺、质量承诺' },
      { title: '投标函附录', pages: 1, hint: '关键承诺事项汇总表' },
      { title: '法定代表人身份证明', pages: 1, hint: '法定代表人姓名、职务、身份证号' },
      { title: '授权委托书', pages: 1, hint: '委托代理人信息、授权范围、授权期限' },
      { title: '投标保证金交纳凭证', pages: 1, hint: '保证金金额、缴纳形式、到账时间' },
      { title: '承诺书', pages: 1, hint: '无行贿犯罪承诺、无重大违法承诺、履约承诺' },
    ],
  },
  {
    key: 'qualification', label: '资格审查', desc: '营业执照+资质+业绩+人员',
    sections: [
      { title: '营业执照', pages: 1, hint: '三证合一/五证合一营业执照扫描件' },
      { title: '资质证书', pages: 2, hint: '行业资质等级证书、安全生产许可证等' },
      { title: '财务状况', pages: 3, hint: '近三年审计报告、资产负债表、利润表、现金流量表' },
      { title: '类似业绩', pages: 5, hint: '近三年类似项目合同、验收证明、业主评价' },
      { title: '项目团队', pages: 3, hint: '项目经理资质、技术负责人、关键岗位人员证书' },
      { title: '企业信誉', pages: 1, hint: '信用中国截图、无不良记录证明' },
      { title: '社保及纳税证明', pages: 2, hint: '近半年社保缴纳凭证、纳税证明' },
    ],
  },
  {
    key: 'technical', label: '技术标', desc: '方案+实施+质量+安全+售后',
    sections: [
      { title: '项目理解与背景分析', pages: 5, hint: '项目背景理解、需求分析、痛点识别', children: ['项目背景', '需求分析', '痛点与挑战'] },
      { title: '总体技术方案', pages: 8, hint: '技术路线、架构设计、关键技术', children: ['技术路线', '系统架构设计', '关键技术方案'] },
      { title: '实施方案', pages: 6, hint: '实施计划、里程碑、资源配置', children: ['实施计划与里程碑', '团队组织与职责', '资源配置方案'] },
      { title: '质量保障方案', pages: 4, hint: '质量管理体系、质量控制措施、测试方案' },
      { title: '安全管理方案', pages: 3, hint: '安全管理体系、安全措施、应急预案' },
      { title: '进度保障方案', pages: 3, hint: '进度控制措施、风险应对、赶工预案' },
      { title: '售后服务方案', pages: 4, hint: '服务承诺、响应时间、培训计划' },
    ],
  },
  {
    key: 'commercial', label: '商务标', desc: '报价+预算+成本分析',
    sections: [
      { title: '投标报价汇总表', pages: 2, hint: '总报价、分项报价汇总' },
      { title: '分项报价明细表', pages: 5, hint: '人工费、材料费、机械费、管理费、利润、税金' },
      { title: '报价编制说明', pages: 2, hint: '编制依据、取费标准、价格来源' },
      { title: '成本分析', pages: 3, hint: '直接成本、间接成本、风险成本分析' },
      { title: '价格优惠与让利', pages: 1, hint: '优惠条件、让利幅度' },
    ],
  },
  {
    key: 'service', label: '售后服务', desc: '服务承诺+培训+应急+质保',
    sections: [
      { title: '售后服务承诺', pages: 2, hint: '服务期限、服务范围、响应时间承诺' },
      { title: '服务团队', pages: 2, hint: '售后服务人员配置、资质、联系方式' },
      { title: '培训方案', pages: 3, hint: '培训计划、培训内容、培训方式' },
      { title: '应急预案', pages: 2, hint: '故障等级划分、响应流程、备用方案' },
      { title: '质保方案', pages: 2, hint: '质保期、质保范围、质保金' },
      { title: '备品备件方案', pages: 1, hint: '备件清单、库存策略、供应周期' },
    ],
  },
];

function CopyableJson({ data, maxheight = '200px' }: { data: unknown; maxheight?: string }) {
  const [copied, setCopied] = useState(false);
  const jsonStr = JSON.stringify(data, null, 2);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonStr);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = jsonStr;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };
  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={handleCopy}
        style={{
          position: 'absolute', top: '8px', right: '8px', zIndex: 1,
          padding: '4px 8px', background: copied ? '#ecfdf5' : 'white',
          border: `1px solid ${copied ? '#a7f3d0' : 'var(--color-border)'}`,
          borderRadius: '4px', cursor: 'pointer', fontSize: '11px',
          display: 'flex', alignItems: 'center', gap: '4px',
          color: copied ? '#059669' : '#64748b',
        }}
      >
        {copied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
        {copied ? '已复制' : '复制'}
      </button>
      <pre style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', fontSize: '11px', overflow: 'auto', maxHeight: maxheight, marginTop: '8px', paddingRight: '60px' }}>
        {jsonStr}
      </pre>
    </div>
  );
}

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
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const [gates, setGates] = useState<GateInfo[]>([]);
  const [streamContent, setStreamContent] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number; currentTitle: string; completed: Array<{ id: string; title: string; wordCount: number }>; failed: Array<{ id: string; title: string; error: string }>; consistencyCheck?: Record<string, unknown> | null; scoringCoverage?: Record<string, unknown> | null } | null>(null);
  const [isBatchStreaming, setIsBatchStreaming] = useState(false);
  const [generatedChapters, setGeneratedChapters] = useState<Array<{ id: string; title: string; content: string; word_count: number; status: string }>>([]);
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null);
  const [selectedChapterContent, setSelectedChapterContent] = useState<string>('');
  const [contentViewMode, setContentViewMode] = useState<'preview' | 'source' | 'edit'>('preview');
  const [editingContent, setEditingContent] = useState<string>('');
  const [savingContent, setSavingContent] = useState(false);
  const [scoreCoverage, setScoreCoverage] = useState<Record<string, unknown> | null>(null);
  const [activeSection, setActiveSection] = useState<'structure' | 'coverage' | 'outline' | 'generate'>('structure');
  const [initialSectionResolved, setInitialSectionResolved] = useState(false);
  const dataReadyRef = useRef({ gatesLoaded: false, outlineLoaded: false, chaptersLoaded: false });
  const [outlineBasis, setOutlineBasis] = useState<{ mode: string; scoringItems: Array<{ category: string; item: string; score: unknown }>; docLength: number; matchedCount: number; totalItems: number } | null>(null);
  const streamRef = useRef<SSEController | null>(null);
  const batchStreamRef = useRef<SSEController | null>(null);

  const [aiImagePrompt, setAiImagePrompt] = useState('');
  const [aiImageProvider, setAiImageProvider] = useState('default');
  const [aiImageSize, setAiImageSize] = useState('landscape_16_9');
  const [aiImageLoading, setAiImageLoading] = useState(false);
  const [aiImageResult, setAiImageResult] = useState<string>('');
  const [aiImageHistory, setAiImageHistory] = useState<Array<{ prompt: string; url: string; timestamp: number }>>([]);
  const [enableIllustration, setEnableIllustration] = useState(true);
  const [removeWatermark, setRemoveWatermark] = useState(true);

  const [outlineReviewConfirmed, setOutlineReviewConfirmed] = useState(false);
  const [generateReviewConfirmed, setGenerateReviewConfirmed] = useState(false);
  const [selectedStructureTemplates, setSelectedStructureTemplates] = useState<Set<string>>(new Set());
  const [structureResult, setStructureResult] = useState<Record<string, unknown> | null>(null);
  const [structureToast, setStructureToast] = useState<string>('');
  const [structureApplying, setStructureApplying] = useState(false);
  const [previewingTemplate, setPreviewingTemplate] = useState<string | null>(null);
  const [gateConfirmDialog, setGateConfirmDialog] = useState<{ stage: string; label: string; contentSummary: string } | null>(null);
  const [gateSuccessMsg, setGateSuccessMsg] = useState<string>('');
  const [cascadeWarning, setCascadeWarning] = useState<string>('');
  const [hasScoringMatrix, setHasScoringMatrix] = useState<boolean>(false);
  const [generatingMatrix, setGeneratingMatrix] = useState(false);
  const [scoringMatrixData, setScoringMatrixData] = useState<Record<string, unknown> | null>(null);
  const [showScoringMatrix, setShowScoringMatrix] = useState(false);

  const { currentProjectId } = useAppStore();
  const navigate = useNavigate();

  const outlineCompleted = outlineNodes.length > 0;
  const generateCompleted = generatedChapters.length > 0;
  const outlineGatePassed = outlineCompleted && outlineReviewConfirmed;
  const generateGatePassed = generateCompleted && generateReviewConfirmed;

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (currentProjectId && !selectedProjectId) {
      setSelectedProjectId(currentProjectId);
    } else {
      try {
        const focusId = localStorage.getItem('bidmaster_focus_project');
        if (focusId && !selectedProjectId) {
          setSelectedProjectId(focusId);
          localStorage.removeItem('bidmaster_focus_project');
        }
      } catch { /* ignore */ }
    }
  }, [currentProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      dataReadyRef.current = { gatesLoaded: false, outlineLoaded: false, chaptersLoaded: false };
      setInitialSectionResolved(false);
      loadGates();
      loadProjectConfig();
      checkScoringMatrix();
      loadSavedOutline();
      loadGeneratedChapters();
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (initialSectionResolved) return;
    if (!selectedProjectId) return;
    const { gatesLoaded, outlineLoaded, chaptersLoaded } = dataReadyRef.current;
    if (!gatesLoaded || !outlineLoaded || !chaptersLoaded) return;

    const hasOutline = outlineNodes.length > 0;
    const hasChapters = generatedChapters.length > 0;

    if (!hasOutline && !hasChapters) {
      setActiveSection('structure');
      setInitialSectionResolved(true);
      return;
    }

    if (hasChapters && !generateReviewConfirmed) {
      setActiveSection('generate');
    } else if (hasOutline && !outlineReviewConfirmed) {
      setActiveSection('outline');
    } else if (outlineGatePassed && !hasChapters) {
      setActiveSection('generate');
    } else if (outlineGatePassed && generateGatePassed) {
      setActiveSection('generate');
    } else if (hasOutline) {
      setActiveSection('outline');
    } else {
      setActiveSection('structure');
    }
    setInitialSectionResolved(true);
  }, [outlineNodes, generatedChapters, outlineReviewConfirmed, generateReviewConfirmed, selectedProjectId, initialSectionResolved]);

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
      const gatesList = res.data.gates || [];
      setGates(gatesList);
      const outlineGate = gatesList.find((g: GateInfo) => g.stage === 'outline');
      const generateGate = gatesList.find((g: GateInfo) => g.stage === 'generate');
      if (outlineGate && outlineGate.status === 'confirmed') {
        setOutlineReviewConfirmed(true);
      }
      if (generateGate && generateGate.status === 'confirmed') {
        setGenerateReviewConfirmed(true);
      }
    } catch (e) {
      console.error('加载闸门信息失败', e);
    } finally {
      dataReadyRef.current.gatesLoaded = true;
    }
  };

  const loadProjectConfig = async () => {
    try {
      const res = await generateApi.getProjectStatus(selectedProjectId);
      const config = res.data?.config || res.data?.project?.config;
      if (!config || typeof config !== 'object') return;
      const cfg = config as Record<string, unknown>;
      const savedTemplate = cfg.structure_template as Record<string, unknown> | undefined;
      if (savedTemplate && typeof savedTemplate === 'object') {
        setStructureResult({ structures: savedTemplate, success: true });
        const selectedType = cfg.selected_structure_type as string;
        if (selectedType) {
          if (selectedType === 'all') {
            setSelectedStructureTemplates(new Set(STRUCTURE_TEMPLATES.map(t => t.key)));
          } else if (selectedType.includes(',')) {
            setSelectedStructureTemplates(new Set(selectedType.split(',').map(s => s.trim())));
          } else {
            setSelectedStructureTemplates(new Set([selectedType]));
          }
        }
      }
    } catch (e) {
      console.error('加载项目配置失败', e);
    }
  };

  const checkScoringMatrix = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await interpretApi.getAnalysis(selectedProjectId);
      const analysis = res.data?.analysis;
      const matrix = analysis?.scoring_matrix;
      const hasMatrix = Boolean(matrix && Object.keys(matrix as object).length > 0);
      setHasScoringMatrix(hasMatrix);
      if (hasMatrix) {
        setScoringMatrixData(matrix as Record<string, unknown>);
      }
    } catch {
      setHasScoringMatrix(false);
    }
  };

  const handleGenerateScoringMatrix = async () => {
    if (!selectedProjectId) return;
    setGeneratingMatrix(true);
    setError('');
    try {
      const res = await interpretApi.scoringMatrix(selectedProjectId);
      if (res.data?.success) {
        setHasScoringMatrix(true);
        setScoringMatrixData(res.data?.data || null);
        setGateSuccessMsg('评分矩阵已生成');
        setTimeout(() => setGateSuccessMsg(''), 3000);
      } else {
        setError(res.data?.error || '评分矩阵生成失败');
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '评分矩阵生成失败';
      setError(msg);
    } finally {
      setGeneratingMatrix(false);
    }
  };

  const loadSavedOutline = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await generateApi.getOutline(selectedProjectId);
      const data = res.data;
      if (data && data.success && data.outline) {
        _processOutlineResult({
          outline: data.outline,
          mode: data.mode,
        }, false);
      }
    } catch (e) {
      console.error('加载已保存大纲失败', e);
    } finally {
      dataReadyRef.current.outlineLoaded = true;
    }
  };

  const [generatingProgress, setGeneratingProgress] = useState<string>('');

  const toggleCollapse = (nodeId: string) => {
    setCollapsedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const expandAll = () => {
    setCollapsedNodes(new Set());
  };

  const collapseAll = () => {
    const allIds = new Set<string>();
    const collectIds = (nodes: OutlineNode[]) => {
      for (const node of nodes) {
        if (node.children && node.children.length > 0) {
          allIds.add(node.id);
          collectIds(node.children);
        }
      }
    };
    collectIds(outlineNodes);
    setCollapsedNodes(allIds);
  };

  const handleGenerateOutline = async () => {
    if (!selectedProjectId) return;

    if (generatedChapters.length > 0) {
      setCascadeWarning('重新生成大纲后，已有正文内容可能需要重新生成。评分覆盖率也将失效。');
    } else if (scoreCoverage) {
      setCascadeWarning('重新生成大纲后，评分覆盖率将失效，需要重新计算。');
    }

    setOutlineNodes([]);
    setOutlineResult(null);
    setOutlineBasis(null);
    setError('');
    setCollapsedNodes(new Set());
    setOutlineReviewConfirmed(false);
    setScoreCoverage(null);

    try {
      await projectApi.resetGate(selectedProjectId, 'outline');
      await projectApi.resetGate(selectedProjectId, 'generate');
    } catch { /* ignore */ }

    setLoading(true);
    setGeneratingProgress('提交生成任务...');

    try {
      const submitRes = await generateApi.generateOutline(selectedProjectId, outlineMode);
      const taskId = submitRes.data?.task_id;
      if (!taskId) {
        _processOutlineResult(submitRes.data);
        return;
      }

      setGeneratingProgress('大纲生成中，请耐心等待（可能需要3-10分钟）...');
      const maxPolls = 240;
      const pollInterval = 5000;
      let consecutiveErrors = 0;

      for (let i = 0; i < maxPolls; i++) {
        await new Promise(r => setTimeout(r, pollInterval));
        try {
          const statusRes = await generateApi.getTaskStatus(taskId);
          consecutiveErrors = 0;
          const task = statusRes.data;

          if (task.status === 'completed') {
            setGeneratingProgress('');
            const result = task.result;
            if (result && result.success === false) {
              setError(result.error || '大纲生成结果为空，请重试');
              setLoading(false);
              return;
            }
            _processOutlineResult(result);
            return;
          } else if (task.status === 'failed') {
            setGeneratingProgress('');
            setError(task.error || '大纲生成失败');
            setLoading(false);
            return;
          } else {
            const elapsed = task.elapsed_seconds ? `${Math.round(task.elapsed_seconds)}s` : '';
            setGeneratingProgress(`大纲生成中... ${elapsed}`);
          }
        } catch (pollErr) {
          consecutiveErrors++;
          if (consecutiveErrors >= 5) {
            setGeneratingProgress('');
            setError('轮询任务状态连续失败，请检查网络后重试');
            setLoading(false);
            return;
          }
        }
      }

      setGeneratingProgress('');
      setError('大纲生成超时（超过20分钟），请重试');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '大纲生成失败');
    } finally {
      setLoading(false);
    }
  };

  const _processOutlineResult = (data: Record<string, unknown> | null, resetReview: boolean = true) => {
    setOutlineResult(data);
    const outline = data?.outline || data;
    const resultMode = (data?.mode as string) || outlineMode;

    let scoringItems: Array<{ category: string; item: string; score: unknown }> = [];
    let matchedCount = 0;
    if (outline && typeof outline === 'object') {
      const outlineObj = outline as Record<string, unknown>;
      const scoreMapping = outlineObj.score_mapping as Record<string, string> | undefined;
      if (scoreMapping && typeof scoreMapping === 'object' && !Array.isArray(scoreMapping)) {
        scoringItems = Object.entries(scoreMapping).map(([name, chapterId]) => ({
          category: '', item: name, score: `→ 章节 ${chapterId}`,
        }));
        matchedCount = Object.keys(scoreMapping).length;
      }
    }

    setOutlineBasis({
      mode: resultMode,
      scoringItems,
      docLength: 0,
      matchedCount,
      totalItems: scoringItems.length,
    });

    if (Array.isArray(outline)) {
      setOutlineNodes(outline as OutlineNode[]);
    } else if (outline && typeof outline === 'object') {
      const outlineObj = outline as Record<string, unknown>;
      const nodes = (outlineObj.chapters || outlineObj.sections || []) as OutlineNode[];
      const scoreMapping = outlineObj.score_mapping as Record<string, string> | undefined;
      if (scoreMapping && typeof scoreMapping === 'object' && !Array.isArray(scoreMapping)) {
        const nodeScoreMap: Record<string, string[]> = {};
        for (const [scoreKey, chapterId] of Object.entries(scoreMapping)) {
          const cid = String(chapterId);
          if (!nodeScoreMap[cid]) nodeScoreMap[cid] = [];
          nodeScoreMap[cid].push(scoreKey);
        }
        const assignScoreMapping = (nodeList: OutlineNode[]): OutlineNode[] => {
          return nodeList.map(node => ({
            ...node,
            score_mapping: nodeScoreMap[node.id] || node.score_mapping || undefined,
            children: node.children ? assignScoreMapping(node.children) : [],
          }));
        };
        setOutlineNodes(assignScoreMapping(nodes));
      } else {
        setOutlineNodes(nodes);
      }
    }
    setLoading(false);
    if (resetReview) {
      setOutlineReviewConfirmed(false);
    }
  };

  const handleExtractMandatory = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setGeneratingProgress('提交强制性要求提取任务...');
    setError('');
    try {
      const submitRes = await generateApi.mandatoryExtract(selectedProjectId);
      const taskId = submitRes.data?.task_id;
      if (!taskId) {
        setMandatoryResult(submitRes.data);
        return;
      }
      setGeneratingProgress('强制性要求提取中...');
      const result = await generateApi.pollTask(taskId, (msg) => setGeneratingProgress(msg));
      setMandatoryResult((result.data || result) as Record<string, unknown> | null);
      setGeneratingProgress('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '提取失败');
      setGeneratingProgress('');
    } finally {
      setLoading(false);
    }
  };

  const handleScoreCoverage = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setGeneratingProgress('提交评分覆盖率计算任务...');
    setError('');
    try {
      const submitRes = await generateApi.scoreCoverage(selectedProjectId);
      const taskId = submitRes.data?.task_id;
      if (!taskId) {
        setScoreCoverage(submitRes.data);
        return;
      }
      setGeneratingProgress('评分覆盖率计算中...');
      const result = await generateApi.pollTask(taskId, (msg) => setGeneratingProgress(msg));
      if (result.success === false) {
        setError((result as Record<string, unknown>).error as string || '覆盖率计算失败');
      } else {
        setScoreCoverage((result.data || result) as Record<string, unknown> | null);
      }
      setGeneratingProgress('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '覆盖率计算失败');
      setGeneratingProgress('');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmOutlineReview = async () => {
    if (!selectedProjectId) return;
    try {
      await projectApi.confirmGate(selectedProjectId, 'outline');
      await loadGates();
      setOutlineReviewConfirmed(true);
      setGateSuccessMsg('大纲审核已通过');
      setTimeout(() => setGateSuccessMsg(''), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '大纲审核确认失败');
    }
  };

  const handleConfirmGenerateReview = async () => {
    if (!selectedProjectId) return;
    try {
      await projectApi.confirmGate(selectedProjectId, 'generate');
      await loadGates();
      setGenerateReviewConfirmed(true);
      setGateSuccessMsg('正文审核已通过');
      setTimeout(() => setGateSuccessMsg(''), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '正文审核确认失败');
    }
  };

  const handleStreamGenerate = useCallback((chapterId: string, mode: string = 'A') => {
    if (!selectedProjectId) return;
    setIsStreaming(true);
    setStreamContent('');
    setError('');

    const controller = generateApi.streamChapter(selectedProjectId, chapterId, mode, {
      onMessage: (data) => {
        if (data.error) {
          setError(String(data.error));
          streamRef.current?.cancel();
          return;
        }
        if (typeof data.content === 'string') {
          setStreamContent(prev => prev + data.content);
        }
        if (data.done) {
          streamRef.current?.cancel();
        }
      },
      onError: (err) => setError(err.message || '流式生成失败'),
      onClose: () => {
        setIsStreaming(false);
        streamRef.current = null;
      },
    });
    streamRef.current = controller as SSEController;
  }, [selectedProjectId]);

  const handleStopStream = () => {
    if (streamRef.current) {
      streamRef.current.cancel();
      streamRef.current = null;
    }
    setIsStreaming(false);
  };

  const handleBatchGenerateAll = useCallback((mode: string = 'A') => {
    if (!selectedProjectId) return;
    setIsBatchStreaming(true);
    setBatchProgress({ current: 0, total: 0, currentTitle: '', completed: [], failed: [] });
    setStreamContent('');
    setError('');
    setGenerateReviewConfirmed(false);

    const controller = generateApi.streamAllChapters(selectedProjectId, mode, {
      onMessage: (data) => {
        const type = data.type as string | undefined;
        if (type === 'start') {
          setBatchProgress(prev => prev ? { ...prev, total: data.total as number } : { current: 0, total: data.total as number, currentTitle: '', completed: [], failed: [] });
        } else if (type === 'progress') {
          setBatchProgress(prev => prev ? { ...prev, current: data.current as number, currentTitle: data.chapter_title as string } : null);
        } else if (type === 'chapter_done') {
          setBatchProgress(prev => prev ? {
            ...prev,
            completed: [...prev.completed, { id: data.chapter_id as string, title: data.chapter_title as string, wordCount: data.word_count as number }],
          } : null);
        } else if (type === 'chapter_error') {
          setBatchProgress(prev => prev ? {
            ...prev,
            failed: [...prev.failed, { id: data.chapter_id as string, title: data.chapter_title as string, error: data.error as string }],
          } : null);
        } else if (type === 'consistency_check') {
          setBatchProgress(prev => prev ? { ...prev, consistencyCheck: (data.data as Record<string, unknown> | null) ?? null } : null);
        } else if (type === 'scoring_coverage') {
          setBatchProgress(prev => prev ? { ...prev, scoringCoverage: (data.data as Record<string, unknown> | null) ?? null } : null);
        } else if (type === 'done') {
          batchStreamRef.current?.cancel();
          loadGeneratedChapters();
          setGenerateReviewConfirmed(false);
        }
      },
      onError: (err) => setError(err.message || '批量生成失败'),
      onClose: () => {
        setIsBatchStreaming(false);
        batchStreamRef.current = null;
      },
    });
    batchStreamRef.current = controller as SSEController;
  }, [selectedProjectId]);

  const handleStopBatchStream = () => {
    if (batchStreamRef.current) {
      batchStreamRef.current.cancel();
      batchStreamRef.current = null;
    }
    setIsBatchStreaming(false);
  };

  const loadGeneratedChapters = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await generateApi.listChapters(selectedProjectId);
      const data = res.data;
      if (data && data.success && data.chapters) {
        setGeneratedChapters(data.chapters);
      }
    } catch (e) {
      console.error('加载已生成章节失败', e);
    } finally {
      dataReadyRef.current.chaptersLoaded = true;
    }
  };

  const handleViewChapter = async (chapterId: string) => {
    if (!selectedProjectId) return;
    setSelectedChapterId(chapterId);
    const cached = generatedChapters.find(c => c.id === chapterId);
    if (cached && cached.content) {
      setSelectedChapterContent(cached.content);
      return;
    }
    try {
      const res = await generateApi.getChapterContent(selectedProjectId, chapterId);
      const data = res.data;
      if (data && data.success && data.chapter) {
        setSelectedChapterContent(data.chapter.content || '');
      }
    } catch (e) {
      console.error('加载章节内容失败', e);
      setSelectedChapterContent('');
    }
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
    const hasChildren = node.children && node.children.length > 0;
    const isCollapsed = collapsedNodes.has(node.id);

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

          <span
            onClick={() => hasChildren && toggleCollapse(node.id)}
            style={{
              cursor: hasChildren ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              flexShrink: 0,
              padding: '2px',
              borderRadius: '4px',
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => { if (hasChildren) (e.currentTarget as HTMLSpanElement).style.background = '#e2e8f0'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLSpanElement).style.background = 'transparent'; }}
          >
            {hasChildren ? (
              isCollapsed ? <ChevronRight size={14} color="#64748b" /> : <ChevronDown size={14} color="#64748b" />
            ) : (
              <span style={{ width: 14, height: 14, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#cbd5e1', display: 'block' }} />
              </span>
            )}
          </span>

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
              {hasChildren && (
                <span style={{ fontSize: '10px', color: '#94a3b8', marginRight: '4px' }}>
                  ({node.children.length})
                </span>
              )}
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
        {hasChildren && !isCollapsed && node.children.map(child => renderOutlineNode(child, depth + 1))}
      </div>
    );
  };

  const sectionTabs = [
    { key: 'structure', label: '结构模板', icon: <FileText size={16} />, step: 1, requires: [] },
    { key: 'outline', label: '大纲编辑', icon: <ListTree size={16} />, step: 2, requires: [] },
    { key: 'coverage', label: '评分覆盖', icon: <AlertTriangle size={16} />, step: 3, requires: ['outline'] },
    { key: 'generate', label: '正文生成', icon: <PenTool size={16} />, step: 4, requires: ['outline'] },
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
        subtitle="结构模板→评分覆盖→大纲编辑→正文生成，每步审核确认后进入下一步"
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
        {sectionTabs.map(tab => {
          const isCompleted = tab.key === 'outline' ? outlineGatePassed : tab.key === 'generate' ? generateGatePassed : tab.key === 'structure' ? selectedStructureTemplates.size > 0 && Boolean(structureResult) : Boolean(scoreCoverage);
          const isLocked = tab.requires.includes('outline') && !outlineGatePassed;
          return (
            <button
              key={tab.key}
              onClick={() => !isLocked && setActiveSection(tab.key as typeof activeSection)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                background: activeSection === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
                color: activeSection === tab.key ? 'white' : isLocked ? '#94a3b8' : 'var(--color-text)',
                border: `1px solid ${activeSection === tab.key ? 'var(--color-primary)' : isLocked ? '#e2e8f0' : 'var(--color-border)'}`,
                borderRadius: '8px',
                cursor: isLocked ? 'not-allowed' : 'pointer',
                fontSize: '13px',
                fontWeight: 500,
                opacity: isLocked ? 0.6 : 1,
                position: 'relative',
              }}
            >
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                fontSize: '11px',
                fontWeight: 700,
                background: isCompleted ? '#059669' : activeSection === tab.key ? 'rgba(255,255,255,0.25)' : '#e2e8f0',
                color: isCompleted ? 'white' : activeSection === tab.key ? 'white' : '#64748b',
              }}>
                {isCompleted ? '✓' : tab.step}
              </span>
              {tab.label}
              {isLocked && <span style={{ fontSize: '11px', color: '#94a3b8' }}>🔒</span>}
            </button>
          );
        })}
      </div>

      {activeSection === 'structure' && structureResult && outlineNodes.length > 0 && (
        <div style={{ padding: '10px 14px', background: '#eff6ff', borderRadius: '8px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#1e40af' }}>
          <Info size={14} />
          <span>结构模板已应用到大纲。如需更新模板，建议重新生成大纲以保持一致。</span>
        </div>
      )}

      {activeSection === 'coverage' && !outlineGatePassed && (
        <div style={{ padding: '10px 14px', background: '#fef3c7', borderRadius: '8px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#92400e' }}>
          <AlertTriangle size={14} />
          <span>依赖：需要先完成大纲生成并审核通过</span>
        </div>
      )}

      {gateSuccessMsg && (
        <div style={{
          padding: '10px 16px',
          background: '#ecfdf5',
          border: '1px solid #a7f3d0',
          borderRadius: '8px',
          color: '#059669',
          fontSize: '13px',
          fontWeight: 500,
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '16px',
        }}>
          <CheckCircle2 size={16} /> {gateSuccessMsg}
        </div>
      )}

      {activeSection === 'structure' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 600 }}>标书5大结构模板</h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                选择结构模板后生成标准章节，确保不遗漏任何必要部分
              </p>
            </div>
          </div>
          {structureToast && (
            <div style={{
              padding: '10px 16px',
              background: '#eff6ff',
              border: '1px solid #bfdbfe',
              borderRadius: '8px',
              color: '#2563eb',
              fontSize: '13px',
              fontWeight: 500,
              marginBottom: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}>
              <CheckCircle2 size={16} /> {structureToast}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>
              已选择 {selectedStructureTemplates.size} / {STRUCTURE_TEMPLATES.length} 个模板
            </div>
            <button
              onClick={() => {
                if (selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length) {
                  setSelectedStructureTemplates(new Set());
                } else {
                  setSelectedStructureTemplates(new Set(STRUCTURE_TEMPLATES.map(t => t.key)));
                }
                setStructureToast('');
              }}
              style={{ padding: '4px 12px', fontSize: '12px', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', background: selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length ? '#eff6ff' : 'white', color: selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length ? 'var(--color-primary)' : 'var(--color-text)', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              {selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length ? <Check size={12} /> : null}
              {selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length ? '取消全选' : '全选'}
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
            {STRUCTURE_TEMPLATES.map(tpl => {
              const isSelected = selectedStructureTemplates.has(tpl.key);
              const isPreviewing = previewingTemplate === tpl.key;
              const totalPages = tpl.sections.reduce((s, sec) => s + sec.pages, 0);
              return (
                <div
                  key={tpl.key}
                  style={{
                    border: isSelected ? '2px solid var(--color-primary)' : '1px solid var(--color-border)',
                    borderRadius: '8px',
                    transition: 'all 0.2s',
                    background: isSelected ? '#eff6ff' : 'transparent',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{ padding: '16px', cursor: 'pointer' }}
                    onClick={() => {
                      setSelectedStructureTemplates(prev => {
                        const next = new Set(prev);
                        if (next.has(tpl.key)) {
                          next.delete(tpl.key);
                        } else {
                          next.add(tpl.key);
                        }
                        return next;
                      });
                      setStructureToast('');
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) {
                        (e.currentTarget as HTMLDivElement).style.background = '#f8fafc';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) {
                        (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                      }
                    }}
                  >
                    {isSelected && (
                      <div style={{
                        position: 'absolute',
                        top: '8px',
                        right: '8px',
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        background: 'var(--color-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}>
                        <Check size={12} color="white" />
                      </div>
                    )}
                    <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px' }}>{tpl.label}</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '6px' }}>{tpl.desc}</div>
                    <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: '#64748b' }}>
                      <span>{tpl.sections.length} 章节</span>
                      <span>·</span>
                      <span>约 {totalPages} 页</span>
                    </div>
                  </div>
                  <div
                    onClick={(e) => { e.stopPropagation(); setPreviewingTemplate(isPreviewing ? null : tpl.key); }}
                    style={{
                      padding: '6px 16px',
                      borderTop: '1px solid var(--color-border)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '4px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      color: 'var(--color-primary)',
                      background: isPreviewing ? '#f0fdf4' : '#f8fafc',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#f0fdf4'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = isPreviewing ? '#f0fdf4' : '#f8fafc'; }}
                  >
                    <Eye size={12} />
                    {isPreviewing ? '收起预览' : '预览模板'}
                    {isPreviewing ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </div>
                  {isPreviewing && (
                    <div style={{ padding: '12px 16px', background: '#fafbfc', borderTop: '1px solid #f1f5f9' }}>
                      {tpl.sections.map((sec, idx) => (
                        <div key={idx} style={{ padding: '6px 0', borderBottom: idx < tpl.sections.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '12px', fontWeight: 500 }}>{sec.title}</span>
                            <span style={{ fontSize: '10px', color: '#94a3b8', background: '#f1f5f9', padding: '1px 6px', borderRadius: '3px' }}>~{sec.pages}页</span>
                          </div>
                          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>{sec.hint}</div>
                          {'children' in sec && (sec as { children?: string[] }).children && (
                            <div style={{ display: 'flex', gap: '4px', marginTop: '4px', flexWrap: 'wrap' }}>
                              {(sec as { children?: string[] }).children!.map((child, ci) => (
                                <span key={ci} style={{ fontSize: '10px', color: '#059669', background: '#ecfdf5', padding: '1px 6px', borderRadius: '3px' }}>{child}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {selectedStructureTemplates.size > 0 && (
            <div style={{ marginTop: '16px' }}>
              {outlineNodes.length > 0 && (
                <div style={{ padding: '10px 14px', background: '#fef3c7', borderRadius: '8px', marginBottom: '10px', display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '12px', color: '#92400e' }}>
                  <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span>已有大纲数据，重新应用结构模板后建议重新生成大纲以匹配新模板结构</span>
                </div>
              )}
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button
                onClick={async () => {
                  if (!selectedProjectId || selectedStructureTemplates.size === 0) return;
                  setStructureApplying(true);
                  setGeneratingProgress('提交结构模板生成任务...');
                  setError('');
                  try {
                    const structureType = selectedStructureTemplates.size === STRUCTURE_TEMPLATES.length
                      ? 'all'
                      : Array.from(selectedStructureTemplates).join(',');
                    const submitRes = await generateApi.generateStructure(selectedProjectId, structureType);
                    const taskId = submitRes.data?.task_id;
                    if (!taskId) {
                      setStructureResult(submitRes.data);
                      return;
                    }
                    setGeneratingProgress('结构模板生成中...');
                    const result = await generateApi.pollTask(taskId, (msg) => setGeneratingProgress(msg));
                    setStructureResult(result);
                    setGeneratingProgress('');
                  } catch (e: unknown) {
                    setError(e instanceof Error ? e.message : '结构模板生成失败');
                    setGeneratingProgress('');
                  } finally {
                    setStructureApplying(false);
                  }
                }}
                disabled={structureApplying || !selectedProjectId}
                style={{
                  padding: '8px 20px',
                  background: structureApplying || !selectedProjectId ? '#94a3b8' : 'var(--color-primary)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: structureApplying || !selectedProjectId ? 'not-allowed' : 'pointer',
                  fontSize: '13px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 500,
                }}
              >
                {structureApplying ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {structureApplying ? '应用中...' : `应用 ${selectedStructureTemplates.size} 个结构模板`}
              </button>
              {!selectedProjectId && (
                <span style={{ fontSize: '12px', color: '#d97706' }}>请先选择项目</span>
              )}
              </div>
            </div>
          )}
          {structureResult && (() => {
            const data = structureResult as Record<string, unknown>;
            const structures = (data.structures || (data.data && typeof data.data === 'object' ? (data.data as Record<string, unknown>).structures : null)) as Record<string, { name: string; sections: Array<{ id: string; title: string; level: number; page_target: number; content_hint?: string }>; total_pages: number; total_sections: number }> | null;
            const actualStructures = structures || ((data.data as Record<string, unknown>)?.structures as Record<string, { name: string; sections: Array<{ id: string; title: string; level: number; page_target: number; content_hint?: string }>; total_pages: number; total_sections: number }> | null);
            if (!actualStructures) return null;
            const templateNames = Object.values(actualStructures).map(s => s.name).join('、');
            const totalPages = Object.values(actualStructures).reduce((s, v) => s + v.total_pages, 0);
            const totalSections = Object.values(actualStructures).reduce((s, v) => s + v.total_sections, 0);
            return (
              <div style={{ marginTop: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 600 }}>
                      ✅ 结构模板已生成
                    </div>
                    <div style={{ fontSize: '12px', color: '#059669', marginTop: '2px' }}>
                      已应用：{templateNames}（{totalSections} 章节，约 {totalPages} 页）
                    </div>
                  </div>
                  <div style={{ fontSize: '12px', color: '#059669', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ArrowRight size={12} /> 生成大纲时将自动应用此模板
                  </div>
                </div>
                {Object.entries(actualStructures).map(([key, struct]) => (
                  <div key={key} style={{ marginBottom: '12px', border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
                    <div style={{ padding: '10px 14px', background: '#f8fafc', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e2e8f0' }}>
                      <span style={{ fontWeight: 600, fontSize: '13px' }}>{struct.name}</span>
                      <span style={{ fontSize: '11px', color: '#64748b' }}>{struct.total_sections} 章节 · 约 {struct.total_pages} 页</span>
                    </div>
                    <div style={{ padding: '8px 0' }}>
                      {struct.sections.map((sec, idx) => (
                        <div key={sec.id || idx} style={{ padding: '6px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: sec.level === 2 ? '#fafbfc' : 'white', borderBottom: idx < struct.sections.length - 1 ? '1px solid #f1f5f9' : 'none' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ width: sec.level === 1 ? '6px' : '0px', height: '6px', borderRadius: '50%', background: 'var(--color-primary)', flexShrink: 0 }} />
                            <span style={{ fontSize: sec.level === 1 ? '13px' : '12px', fontWeight: sec.level === 1 ? 500 : 400, color: sec.level === 1 ? 'var(--color-text)' : '#64748b', paddingLeft: sec.level === 2 ? '14px' : '0' }}>{sec.title}</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {sec.content_hint && <span style={{ fontSize: '10px', color: '#94a3b8', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec.content_hint}</span>}
                            <span style={{ fontSize: '10px', color: '#94a3b8', background: '#f1f5f9', padding: '1px 6px', borderRadius: '3px' }}>~{sec.page_target}页</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}
        </div>
      )}

      {activeSection === 'coverage' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 600 }}>评分矩阵覆盖率</h3>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                检查评分项在大纲章节中的覆盖情况，确保目录能完整覆盖所有评分要求
              </p>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {hasScoringMatrix && (
                <button
                  onClick={() => setShowScoringMatrix(!showScoringMatrix)}
                  style={{
                    padding: '6px 14px',
                    background: showScoringMatrix ? '#1e40af' : '#eff6ff',
                    color: showScoringMatrix ? 'white' : '#2563eb',
                    border: `1px solid ${showScoringMatrix ? '#1e40af' : '#bfdbfe'}`,
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '13px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <Eye size={12} />
                  {showScoringMatrix ? '收起矩阵' : '预览矩阵'}
                </button>
              )}
              {!hasScoringMatrix && outlineGatePassed && (
                <button
                  onClick={handleGenerateScoringMatrix}
                  disabled={generatingMatrix || !selectedProjectId}
                  style={{
                    padding: '6px 14px',
                    background: '#d97706',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: generatingMatrix ? 'not-allowed' : 'pointer',
                    fontSize: '13px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  {generatingMatrix ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                  {generatingMatrix ? '生成中...' : '生成评分矩阵'}
                </button>
              )}
              <button
                onClick={handleScoreCoverage}
                disabled={loading || !selectedProjectId || !outlineGatePassed || !hasScoringMatrix}
                style={{
                  padding: '6px 14px',
                  background: (!loading && selectedProjectId && outlineGatePassed && hasScoringMatrix) ? 'var(--color-primary)' : '#94a3b8',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: (!loading && selectedProjectId && outlineGatePassed && hasScoringMatrix) ? 'pointer' : 'not-allowed',
                  fontSize: '13px',
                }}
              >
                {loading ? (generatingProgress || '计算中...') : '计算覆盖率'}
              </button>
            </div>
          </div>

          {!outlineGatePassed && (
            <div style={{ padding: '16px', background: '#fef3c7', borderRadius: '8px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={16} color="#d97706" />
              <span style={{ fontSize: '13px', color: '#92400e' }}>请先完成大纲生成并审核确认后，才能计算评分覆盖率</span>
            </div>
          )}

          {outlineGatePassed && !hasScoringMatrix && (
            <div style={{ padding: '16px', background: '#fef2f2', borderRadius: '8px', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: '10px' }}>
                <AlertTriangle size={16} color="#dc2626" style={{ flexShrink: 0, marginTop: '1px' }} />
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#991b1b', marginBottom: '4px' }}>尚未生成评分矩阵</div>
                  <div style={{ fontSize: '12px', color: '#7f1d1d' }}>
                    评分矩阵来自招标解读阶段。请点击上方"生成评分矩阵"按钮，或前往
                    <span onClick={() => navigate('/interpret')} style={{ color: 'var(--color-primary)', cursor: 'pointer', fontWeight: 500, textDecoration: 'underline' }}>招标解读</span>
                    页面完成AI解读后自动生成。
                  </div>
                </div>
              </div>
            </div>
          )}

          {showScoringMatrix && scoringMatrixData && (() => {
            const rows = (scoringMatrixData.rows || []) as Array<Record<string, unknown>>;
            const totalScore = (scoringMatrixData.total_score || 0) as number;
            const categoryScores = (scoringMatrixData.category_scores || {}) as Record<string, number>;
            const categories = Object.keys(categoryScores);
            return (
              <div style={{ marginBottom: '16px', border: '1px solid #bfdbfe', borderRadius: '8px', overflow: 'hidden' }}>
                <div style={{ padding: '10px 14px', background: '#eff6ff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #bfdbfe' }}>
                  <span style={{ fontWeight: 600, fontSize: '13px', color: '#1e40af' }}>评分矩阵预览</span>
                  <div style={{ display: 'flex', gap: '12px', fontSize: '11px', color: '#64748b' }}>
                    <span>{rows.length} 项</span>
                    <span>总分 {totalScore}</span>
                  </div>
                </div>
                {categories.length > 0 && (
                  <div style={{ padding: '8px 14px', background: '#f8fafc', display: 'flex', gap: '12px', borderBottom: '1px solid #e2e8f0' }}>
                    {categories.map(cat => (
                      <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ fontSize: '11px', padding: '1px 6px', borderRadius: '3px', background: cat === '价格' ? '#fef3c7' : cat === '技术' ? '#dbeafe' : '#dcfce7', color: cat === '价格' ? '#92400e' : cat === '技术' ? '#1e40af' : '#166534' }}>{cat}</span>
                        <span style={{ fontSize: '11px', color: '#64748b' }}>{categoryScores[cat]}分</span>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                        <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#64748b', width: '32px' }}>#</th>
                        <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#64748b', width: '50px' }}>类别</th>
                        <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#64748b' }}>评分项</th>
                        <th style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 600, color: '#64748b', width: '40px' }}>分值</th>
                        <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#64748b' }}>评分标准</th>
                        <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#64748b', width: '100px' }}>应答章节</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, idx) => {
                        const cat = String(row.category || '');
                        const catColor = cat === '价格' ? '#92400e' : cat === '技术' ? '#1e40af' : '#166534';
                        const catBg = cat === '价格' ? '#fef3c7' : cat === '技术' ? '#dbeafe' : '#dcfce7';
                        return (
                          <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                            <td style={{ padding: '6px 10px', color: '#94a3b8' }}>{String(row.seq ?? idx + 1)}</td>
                            <td style={{ padding: '6px 10px' }}><span style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '3px', background: catBg, color: catColor }}>{cat}</span></td>
                            <td style={{ padding: '6px 10px', fontWeight: 500 }}>{String(row.item || '')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 600, color: '#059669' }}>{String(row.score ?? 0)}</td>
                            <td style={{ padding: '6px 10px', color: '#64748b', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(row.criteria || '')}>{String(row.criteria || '')}</td>
                            <td style={{ padding: '6px 10px', color: '#64748b', fontSize: '11px' }}>{String(row.response_section || '')}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })()}

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
              {(() => {
                const detail = (scoreCoverage as Record<string, unknown>).uncovered_detail;
                if (!detail || !Array.isArray(detail) || detail.length === 0) return null;
                return (
                  <div style={{ marginTop: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px', color: '#dc2626' }}>⚠ 未覆盖的评分项</div>
                    {(detail as Array<Record<string, unknown>>).map((item, idx) => (
                      <div key={idx} style={{ padding: '8px 12px', background: '#fef2f2', borderRadius: '6px', marginBottom: '6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px' }}>{String(item.score_item || item.name || '')}</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontSize: '11px', color: '#dc2626' }}>{String(item.score || 0)}分</span>
                          <span style={{ fontSize: '11px', color: '#64748b' }}>{String(item.suggestion || '')}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              {outlineGatePassed && hasScoringMatrix ? '点击"计算覆盖率"查看评分项覆盖情况' : !outlineGatePassed ? '完成大纲审核后即可计算覆盖率' : '请先生成评分矩阵'}
            </div>
          )}
        </div>
      )}

      {activeSection === 'outline' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          {cascadeWarning && (
            <div style={{ padding: '10px 14px', background: '#fef3c7', borderRadius: '8px', marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#92400e' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <AlertTriangle size={14} style={{ flexShrink: 0 }} />
                <span>{cascadeWarning}</span>
              </div>
              <button onClick={() => setCascadeWarning('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#92400e', padding: '2px' }}>
                <X size={12} />
              </button>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600 }}>大纲编辑器</h3>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
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
                  opacity: loading || !selectedProjectId ? 0.7 : 1,
                }}
              >
                {loading ? (generatingProgress || '生成中...') : outlineNodes.length > 0 ? '重新生成大纲' : '生成大纲'}
              </button>
              {outlineNodes.length > 0 && (
                <>
                  <button onClick={expandAll} style={{ padding: '6px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', color: 'var(--color-text)' }} title="展开全部">展开全部</button>
                  <button onClick={collapseAll} style={{ padding: '6px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', color: 'var(--color-text)' }} title="收起全部">收起全部</button>
                </>
              )}
              <button
                onClick={() => {
                  const newNode: OutlineNode = { id: `new_${Date.now()}`, title: '新章节', level: 1, children: [], status: 'pending' };
                  setOutlineNodes(prev => [...prev, newNode]);
                }}
                style={{ padding: '6px 14px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <Plus size={14} /> 添加章节
              </button>
            </div>
          </div>

          {loading && (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', padding: '20px', minHeight: '300px', position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'relative', zIndex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }}>
                  <div className="skeleton-circle" style={{ width: '36px', height: '36px', borderRadius: '50%', background: 'linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%)', backgroundSize: '200% 100%' }} />
                  <div style={{ flex: 1 }}>
                    <div className="skeleton-bar" style={{ width: '45%', height: '14px', borderRadius: '7px', background: 'linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%)', backgroundSize: '200% 100%', marginBottom: '8px' }} />
                    <div className="skeleton-bar" style={{ width: '30%', height: '10px', borderRadius: '5px', background: 'linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%)', backgroundSize: '200% 100%' }} />
                  </div>
                </div>
                {[1, 2, 3, 4, 5].map(i => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px', paddingLeft: `${(i % 3) * 24}px` }}>
                    <div className="skeleton-bar" style={{ width: '12px', height: '12px', borderRadius: '3px', background: 'linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%)', backgroundSize: '200% 100%', flexShrink: 0 }} />
                    <div className="skeleton-bar" style={{ width: `${50 + Math.random() * 35}%`, height: `${i <= 2 ? '14px' : '11px'}`, borderRadius: '7px', background: 'linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%)', backgroundSize: '200% 100%' }} />
                  </div>
                ))}
              </div>
              <div style={{ position: 'absolute', bottom: '16px', left: 0, right: 0, textAlign: 'center', zIndex: 2 }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', padding: '8px 20px', background: 'rgba(255,255,255,0.9)', borderRadius: '20px', boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
                  <div className="outline-loading-dots"><span /><span /><span /></div>
                  <span style={{ fontSize: '13px', color: '#64748b', fontWeight: 500 }}>{generatingProgress || '正在生成大纲'}</span>
                </div>
              </div>
            </div>
          )}

          {!loading && outlineNodes.length > 0 ? (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', padding: '12px', maxHeight: '500px', overflow: 'auto' }}>
              {outlineNodes.map(node => renderOutlineNode(node))}
            </div>
          ) : !loading && (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
              {outlineResult ? '大纲数据格式不匹配，请查看原始结果' : '点击"生成大纲"开始'}
            </div>
          )}

          {outlineResult && (
            <details style={{ marginTop: '12px' }}>
              <summary style={{ fontSize: '12px', color: 'var(--color-text-secondary)', cursor: 'pointer' }}>查看原始JSON结果</summary>
              <CopyableJson data={outlineResult} maxheight="200px" />
            </details>
          )}

          {outlineBasis && (
            <div style={{ marginTop: '16px', padding: '14px', background: '#f0f9ff', borderRadius: '8px', border: '1px solid #bfdbfe' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                <Info size={16} color="#2563eb" />
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e40af' }}>生成依据</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: outlineBasis.scoringItems.length > 0 ? '12px' : '0' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#1e40af' }}>{outlineBasis.mode === 'aligned' ? '对齐评分项模式' : '自由模式'}</div>
                  <div style={{ fontSize: '11px', color: '#64748b' }}>生成模式</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#059669' }}>{outlineBasis.matchedCount} / {outlineBasis.totalItems}</div>
                  <div style={{ fontSize: '11px', color: '#64748b' }}>评分项匹配</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#64748b' }}>{outlineNodes.length} 章</div>
                  <div style={{ fontSize: '11px', color: '#64748b' }}>大纲章节数</div>
                </div>
              </div>
              {outlineBasis.scoringItems.length > 0 && (
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: '#475569', marginBottom: '6px' }}>评分项→章节映射</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {outlineBasis.scoringItems.map((item, idx) => (
                      <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', padding: '4px 8px', background: 'white', borderRadius: '4px', border: '1px solid #e2e8f0' }}>
                        <span style={{ color: '#059669', fontWeight: 500, minWidth: '120px' }}>{item.item}</span>
                        <span style={{ color: '#94a3b8' }}>→</span>
                        <span style={{ color: '#1e40af' }}>{String(item.score)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {outlineBasis.mode === 'free' && (
                <div style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>
                  自由模式：大纲仅基于招标文件内容生成，未对齐评分项。如需对齐，请选择"对齐评分项模式"。
                </div>
              )}
            </div>
          )}

          {outlineCompleted && (
            <div style={{
              marginTop: '16px',
              padding: '16px',
              background: outlineReviewConfirmed ? '#ecfdf5' : '#fffbeb',
              border: `1px solid ${outlineReviewConfirmed ? '#a7f3d0' : '#fbbf24'}`,
              borderRadius: '10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '36px', height: '36px', borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: outlineReviewConfirmed ? '#059669' : '#d97706',
                  color: 'white',
                }}>
                  <Shield size={18} />
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>
                    {outlineReviewConfirmed ? '大纲审核已通过' : '大纲审核确认'}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>
                    {outlineReviewConfirmed
                      ? `${outlineNodes.length} 个一级章节 · ${outlineNodes.reduce((sum, n) => sum + 1 + (n.children?.length || 0), 0)} 个总章节`
                      : '确认大纲结构完整、评分项覆盖对齐后，才能进入正文生成'}
                  </div>
                </div>
              </div>
              {outlineReviewConfirmed ? (
                <button
                  onClick={async () => {
                    setOutlineReviewConfirmed(false);
                    try { await projectApi.resetGate(selectedProjectId, 'outline'); } catch { /* ignore */ }
                  }}
                  style={{ padding: '6px 14px', background: 'white', color: '#d97706', border: '1px solid #fbbf24', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  撤回确认
                </button>
              ) : (
                <button
                  onClick={handleConfirmOutlineReview}
                  style={{ padding: '8px 20px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
                >
                  确认大纲审核通过
                </button>
              )}
            </div>
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
                <input type="checkbox" checked={enableIllustration} onChange={(e) => setEnableIllustration(e.target.checked)} style={{ width: '16px', height: '16px', cursor: 'pointer' }} />
                启用AI配图
              </label>
            </div>

            {enableIllustration && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#1e40af', display: 'block', marginBottom: '4px' }}>配图供应商</label>
                  <select value={aiImageProvider} onChange={(e) => setAiImageProvider(e.target.value)} style={{ width: '100%', padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }}>
                    <option value="default">默认(内置)</option>
                    <option value="volcengine">火山方舟</option>
                    <option value="google">Google AI Studio</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#1e40af', display: 'block', marginBottom: '4px' }}>配图尺寸</label>
                  <select value={aiImageSize} onChange={(e) => setAiImageSize(e.target.value)} style={{ width: '100%', padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }}>
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
                      <input type="checkbox" checked={removeWatermark} onChange={(e) => setRemoveWatermark(e.target.checked)} style={{ width: '16px', height: '16px', cursor: 'pointer' }} />
                      自动去水印
                    </label>
                    <span style={{ fontSize: '11px', color: '#6b7280' }}>{removeWatermark ? '✓ 将自动检测并移除水印' : '保留原始图片'}</span>
                  </div>
                </div>
              </div>
            )}

            {enableIllustration && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input type="text" value={aiImagePrompt} onChange={(e) => setAiImagePrompt(e.target.value)} placeholder="自定义配图描述（留空则根据章节标题自动生成）" style={{ flex: 1, padding: '6px 10px', border: '1px solid #bfdbfe', borderRadius: '6px', fontSize: '13px', background: 'white' }} />
                <button onClick={handleGenerateAiImage} disabled={aiImageLoading || !aiImagePrompt.trim()} style={{ padding: '6px 14px', background: aiImageLoading || !aiImagePrompt.trim() ? '#94a3b8' : '#2563eb', color: 'white', border: 'none', borderRadius: '6px', cursor: aiImageLoading || !aiImagePrompt.trim() ? 'not-allowed' : 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' }}>
                  {aiImageLoading ? <Loader2 size={12} /> : <ImageIcon size={12} />}
                  {aiImageLoading ? '生成中...' : '预览配图'}
                </button>
              </div>
            )}

            {aiImageResult && enableIllustration && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                <img src={aiImageResult} alt="AI配图预览" style={{ width: '200px', height: '120px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #bfdbfe' }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12px', color: '#059669', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>{removeWatermark ? '✓ 已启用去水印' : '○ 未启用去水印'}</div>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>此配图将在正文生成时自动插入到对应章节中</div>
                  {aiImageHistory.length > 0 && (
                    <div style={{ marginTop: '8px', display: 'flex', gap: '6px' }}>
                      {aiImageHistory.slice(0, 4).map((item, idx) => (
                        <img key={idx} src={item.url} alt={item.prompt} onClick={() => setAiImageResult(item.url)} style={{ width: '48px', height: '36px', objectFit: 'cover', borderRadius: '4px', cursor: 'pointer', border: '1px solid #bfdbfe' }} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>选择章节</label>
              <select id="chapter-id-select" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}>
                {outlineNodes.length === 0 ? (
                  <option value="">请先生成大纲</option>
                ) : (
                  outlineNodes.map(node => {
                    const childOptions = (node.children || []).map((child: OutlineNode) => (
                      <option key={child.id} value={child.id}>&nbsp;&nbsp;{child.id} {child.title}</option>
                    ));
                    return [<option key={node.id} value={node.id}>{node.id} {node.title}</option>, ...childOptions];
                  }).flat()
                )}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>生成模式</label>
              <select id="gen-mode-select" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}>
                <option value="A">A模式(大纲+招标要求)</option>
                <option value="B">B模式(知识库+大纲)</option>
                <option value="C">C模式(纯大纲)</option>
                <option value="D">D模式(自由生成)</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
            <button
              onClick={() => { const mode = (document.getElementById('gen-mode-select') as HTMLSelectElement)?.value || 'A'; handleBatchGenerateAll(mode); }}
              disabled={isBatchStreaming || isStreaming || !selectedProjectId || outlineNodes.length === 0}
              style={{ padding: '8px 16px', background: (isBatchStreaming || isStreaming || !selectedProjectId || outlineNodes.length === 0) ? '#94a3b8' : '#059669', color: 'white', border: 'none', borderRadius: '8px', cursor: (isBatchStreaming || isStreaming || !selectedProjectId || outlineNodes.length === 0) ? 'not-allowed' : 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <FileText size={14} /> {isBatchStreaming ? `批量生成中(${batchProgress?.current || 0}/${batchProgress?.total || 0})...` : '生成全部正文'}
            </button>
            {isBatchStreaming && (
              <button onClick={handleStopBatchStream} style={{ padding: '8px 16px', background: '#dc2626', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' }}>停止批量生成</button>
            )}
            <button
              onClick={() => { const selectEl = document.getElementById('chapter-id-select') as HTMLSelectElement; const chapterId = selectEl?.value || '1'; const mode = (document.getElementById('gen-mode-select') as HTMLSelectElement)?.value || 'A'; handleStreamGenerate(chapterId, mode); }}
              disabled={isStreaming || isBatchStreaming || !selectedProjectId || outlineNodes.length === 0}
              style={{ padding: '8px 16px', background: (isStreaming || isBatchStreaming || !selectedProjectId || outlineNodes.length === 0) ? '#94a3b8' : 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '8px', cursor: (isStreaming || isBatchStreaming || !selectedProjectId || outlineNodes.length === 0) ? 'not-allowed' : 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Play size={14} /> {isStreaming ? '生成中...' : '单章生成'}
            </button>
            {isStreaming && (
              <button onClick={handleStopStream} style={{ padding: '8px 16px', background: '#dc2626', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px' }}>停止</button>
            )}
            <button
              onClick={handleExtractMandatory}
              disabled={loading || !selectedProjectId}
              style={{ padding: '8px 16px', background: '#d97706', color: 'white', border: 'none', borderRadius: '8px', cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer', fontSize: '13px' }}
            >
              提取实质性要求
            </button>
          </div>

          {isBatchStreaming && batchProgress && (
            <div style={{ border: '1px solid #a7f3d0', borderRadius: '8px', padding: '16px', background: '#ecfdf5', marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#065f46' }}>批量生成进度 ({batchProgress.current}/{batchProgress.total})</span>
                <Loader2 size={14} className="animate-spin" style={{ color: '#059669' }} />
              </div>
              <div style={{ width: '100%', height: '8px', background: '#d1fae5', borderRadius: '4px', marginBottom: '12px', overflow: 'hidden' }}>
                <div style={{ width: `${batchProgress.total > 0 ? (batchProgress.current / batchProgress.total) * 100 : 0}%`, height: '100%', background: '#059669', borderRadius: '4px', transition: 'width 0.3s ease' }} />
              </div>
              {batchProgress.currentTitle && <div style={{ fontSize: '13px', color: '#047857', marginBottom: '8px' }}>正在生成: {batchProgress.currentTitle}</div>}
              {batchProgress.completed.length > 0 && (
                <div style={{ fontSize: '12px', color: '#065f46' }}>
                  <div style={{ fontWeight: 500, marginBottom: '4px' }}>已完成:</div>
                  {batchProgress.completed.map((c, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '2px 0' }}>
                      <CheckCircle2 size={12} color="#059669" /><span>{c.title}</span><span style={{ color: '#6b7280', fontSize: '11px' }}>({c.wordCount}字)</span>
                    </div>
                  ))}
                </div>
              )}
              {batchProgress.failed.length > 0 && (
                <div style={{ fontSize: '12px', color: '#dc2626', marginTop: '8px' }}>
                  <div style={{ fontWeight: 500, marginBottom: '4px' }}>失败:</div>
                  {batchProgress.failed.map((f, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '2px 0' }}>
                      <AlertTriangle size={12} color="#dc2626" /><span>{f.title}: {f.error}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {batchProgress && !isBatchStreaming && (batchProgress.completed.length > 0 || batchProgress.failed.length > 0) && (
            <div style={{ border: '1px solid #a7f3d0', borderRadius: '8px', padding: '16px', background: '#ecfdf5', marginBottom: '16px' }}>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#065f46', marginBottom: '8px' }}>批量生成完成 (成功{batchProgress.completed.length}章 / 失败{batchProgress.failed.length}章)</div>
              {batchProgress.scoringCoverage && (() => {
                const sc = batchProgress.scoringCoverage as { total?: number; covered?: number; coverage_rate?: number; missing_items?: string[] };
                return (
                  <div style={{ marginBottom: '8px', padding: '10px', background: '#f0fdf4', borderRadius: '6px', border: '1px solid #bbf7d0' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#166534', marginBottom: '6px' }}>评分覆盖检查 ({sc.coverage_rate || 0}%)</div>
                    <div style={{ width: '100%', height: '6px', background: '#dcfce7', borderRadius: '3px', marginBottom: '6px' }}>
                      <div style={{ width: `${sc.coverage_rate || 0}%`, height: '100%', background: sc.coverage_rate && sc.coverage_rate >= 80 ? '#059669' : '#d97706', borderRadius: '3px' }} />
                    </div>
                    <div style={{ fontSize: '12px', color: '#15803d' }}>共{sc.total || 0}项评分点，已覆盖{sc.covered || 0}项，未覆盖{sc.missing_items?.length || 0}项</div>
                    {sc.missing_items && sc.missing_items.length > 0 && <div style={{ fontSize: '11px', color: '#92400e', marginTop: '4px' }}>未覆盖: {sc.missing_items.slice(0, 5).join('、')}{sc.missing_items.length > 5 ? '...' : ''}</div>}
                  </div>
                );
              })()}
              {batchProgress.consistencyCheck && (() => {
                const cc = batchProgress.consistencyCheck as { risk_level?: string; summary?: { total?: number; critical?: number; major?: number }; checks?: Array<{ check_name?: string; severity?: string; suggestion?: string }> };
                const isHighRisk = cc.risk_level === 'high';
                return (
                  <div style={{ marginBottom: '8px', padding: '10px', background: isHighRisk ? '#fef2f2' : '#f0fdf4', borderRadius: '6px', border: `1px solid ${isHighRisk ? '#fecaca' : '#bbf7d0'}` }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: isHighRisk ? '#991b1b' : '#166534', marginBottom: '6px' }}>一致性检查 (风险等级: {cc.risk_level === 'high' ? '高风险' : cc.risk_level === 'medium' ? '中风险' : '低风险'})</div>
                    {cc.summary && <div style={{ fontSize: '12px', color: isHighRisk ? '#b91c1c' : '#15803d' }}>共{cc.summary.total || 0}项检查，严重{cc.summary.critical || 0}项，重要{cc.summary.major || 0}项</div>}
                    {cc.checks && cc.checks.filter(c => c.severity === 'critical' || c.severity === 'major').slice(0, 5).map((check, i) => (
                      <div key={i} style={{ fontSize: '11px', color: '#7f1d1d', marginTop: '2px' }}><AlertTriangle size={10} style={{ display: 'inline', verticalAlign: 'middle' }} /> {check.check_name}: {check.suggestion}</div>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}

          {generatedChapters.length > 0 && (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '10px', overflow: 'hidden', marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <BookOpen size={16} color="#059669" />
                  <span style={{ fontSize: '14px', fontWeight: 600 }}>已生成章节 ({generatedChapters.length}章)</span>
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                  <button onClick={() => { setContentViewMode('preview'); }} style={{ padding: '4px 10px', fontSize: '12px', border: '1px solid var(--color-border)', borderRadius: '4px 0 0 4px', cursor: 'pointer', background: contentViewMode === 'preview' ? 'var(--color-primary)' : 'white', color: contentViewMode === 'preview' ? 'white' : 'var(--color-text)' }}>
                    <Eye size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />预览
                  </button>
                  <button onClick={() => { setContentViewMode('source'); }} style={{ padding: '4px 10px', fontSize: '12px', border: '1px solid var(--color-border)', borderLeft: 'none', cursor: 'pointer', background: contentViewMode === 'source' ? 'var(--color-primary)' : 'white', color: contentViewMode === 'source' ? 'white' : 'var(--color-text)' }}>
                    <BookOpen size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />源码
                  </button>
                  <button onClick={() => { setEditingContent(selectedChapterContent); setContentViewMode('edit'); }} style={{ padding: '4px 10px', fontSize: '12px', border: '1px solid var(--color-border)', borderLeft: 'none', borderRadius: '0 4px 4px 0', cursor: 'pointer', background: contentViewMode === 'edit' ? '#d97706' : 'white', color: contentViewMode === 'edit' ? 'white' : 'var(--color-text)' }}>
                    <Edit3 size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />编辑
                  </button>
                  <button onClick={() => { if (!selectedProjectId) return; window.open(`/api/projects/${selectedProjectId}/export/word`, '_blank'); }} style={{ padding: '4px 10px', fontSize: '12px', border: '1px solid #059669', borderRadius: '4px', cursor: 'pointer', background: '#ecfdf5', color: '#059669', marginLeft: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Download size={12} /> 下载Word文档
                  </button>
                </div>
              </div>
              <div style={{ display: 'flex', minHeight: '400px' }}>
                <div style={{ width: '280px', minWidth: '280px', borderRight: '1px solid var(--color-border)', overflowY: 'auto', maxHeight: '600px', background: '#fafbfc' }}>
                  {generatedChapters.map((ch) => {
                    const isSelected = selectedChapterId === ch.id;
                    const statusColor = ch.status === 'generated' ? '#059669' : ch.status === 'edited' ? '#2563eb' : ch.status === 'failed' ? '#dc2626' : '#d97706';
                    return (
                      <div key={ch.id} onClick={() => handleViewChapter(ch.id)} style={{ padding: '10px 14px', cursor: 'pointer', borderLeft: isSelected ? '3px solid var(--color-primary)' : '3px solid transparent', background: isSelected ? '#eff6ff' : 'transparent', borderBottom: '1px solid #f1f5f9', transition: 'all 0.15s' }} onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '#f0f4f8'; }} onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                          <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: statusColor, flexShrink: 0 }} />
                          <span style={{ fontSize: '13px', fontWeight: isSelected ? 600 : 400, color: isSelected ? 'var(--color-primary)' : 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ch.title}</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingLeft: '12px' }}>
                          <span style={{ fontSize: '11px', color: '#64748b' }}>{ch.word_count}字</span>
                          <span style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '3px', background: ch.status === 'generated' ? '#dcfce7' : ch.status === 'edited' ? '#dbeafe' : ch.status === 'failed' ? '#fee2e2' : '#fef3c7', color: ch.status === 'generated' ? '#166534' : ch.status === 'edited' ? '#1e40af' : ch.status === 'failed' ? '#991b1b' : '#92400e' }}>{ch.status === 'generated' ? '已生成' : ch.status === 'edited' ? '已编辑' : ch.status === 'failed' ? '失败' : '待生成'}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div style={{ flex: 1, overflowY: 'auto', maxHeight: '600px', padding: '20px 24px' }}>
                  {selectedChapterId && selectedChapterContent ? (
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', paddingBottom: '12px', borderBottom: '1px solid #e2e8f0' }}>
                        <div>
                          <h4 style={{ fontSize: '16px', fontWeight: 600, margin: 0 }}>{generatedChapters.find(c => c.id === selectedChapterId)?.title || '章节内容'}</h4>
                          <span style={{ fontSize: '12px', color: '#64748b' }}>{contentViewMode === 'edit' ? editingContent.length : selectedChapterContent.length}字</span>
                        </div>
                        {contentViewMode === 'edit' && (
                          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <button
                              onClick={async () => {
                                if (!selectedProjectId || !selectedChapterId) return;
                                setSavingContent(true);
                                try {
                                  await generateApi.updateChapterContent(selectedProjectId, selectedChapterId, editingContent);
                                  setSelectedChapterContent(editingContent);
                                  setGeneratedChapters(prev => prev.map(ch =>
                                    ch.id === selectedChapterId ? { ...ch, content: editingContent, word_count: editingContent.length, status: 'edited' } : ch
                                  ));
                                  setContentViewMode('preview');
                                  setGateSuccessMsg('内容已保存');
                                  setTimeout(() => setGateSuccessMsg(''), 2000);
                                } catch (e: unknown) {
                                  setError(e instanceof Error ? e.message : '保存失败');
                                } finally {
                                  setSavingContent(false);
                                }
                              }}
                              disabled={savingContent}
                              style={{ padding: '6px 16px', background: savingContent ? '#94a3b8' : '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: savingContent ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}
                            >
                              {savingContent ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                              {savingContent ? '保存中...' : '保存修改'}
                            </button>
                            <button
                              onClick={() => { setEditingContent(selectedChapterContent); setContentViewMode('preview'); }}
                              style={{ padding: '6px 14px', background: 'white', color: '#64748b', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
                            >
                              取消
                            </button>
                          </div>
                        )}
                      </div>
                      {contentViewMode === 'preview' ? (
                        <MarkdownRenderer>{selectedChapterContent}</MarkdownRenderer>
                      ) : contentViewMode === 'source' ? (
                        <pre style={{ fontSize: '12px', lineHeight: '1.6', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#f8fafc', padding: '16px', borderRadius: '6px', border: '1px solid #e2e8f0' }}>{selectedChapterContent}</pre>
                      ) : (
                        <textarea
                          value={editingContent}
                          onChange={(e) => setEditingContent(e.target.value)}
                          style={{
                            width: '100%',
                            minHeight: '500px',
                            padding: '16px',
                            fontSize: '13px',
                            lineHeight: '1.8',
                            fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
                            border: '2px solid #d97706',
                            borderRadius: '8px',
                            background: '#fffbeb',
                            outline: 'none',
                            resize: 'vertical',
                          }}
                          placeholder="在此编辑章节内容..."
                        />
                      )}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', minHeight: '300px', color: '#94a3b8' }}>
                      <BookOpen size={48} strokeWidth={1} style={{ marginBottom: '12px' }} />
                      <div style={{ fontSize: '14px', fontWeight: 500 }}>点击左侧章节查看内容</div>
                      <div style={{ fontSize: '12px', marginTop: '4px' }}>选择一个章节即可在此预览正文</div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {(streamContent || isStreaming) && (
            <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', padding: '16px', background: '#f8fafc', maxHeight: '400px', overflow: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>{isStreaming ? '正在生成...' : '生成完成'}</span>
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
              <CopyableJson data={mandatoryResult} maxheight="300px" />
            </div>
          )}

          {generateCompleted && (
            <div style={{
              marginTop: '16px',
              padding: '16px',
              background: generateReviewConfirmed ? '#ecfdf5' : '#fffbeb',
              border: `1px solid ${generateReviewConfirmed ? '#a7f3d0' : '#fbbf24'}`,
              borderRadius: '10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '36px', height: '36px', borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: generateReviewConfirmed ? '#059669' : '#d97706',
                  color: 'white',
                }}>
                  <Shield size={18} />
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>
                    {generateReviewConfirmed ? '正文审核已通过' : '正文审核确认'}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>
                    {generateReviewConfirmed
                      ? `${generatedChapters.length} 章 · ${generatedChapters.reduce((sum, ch) => sum + ch.word_count, 0).toLocaleString()} 字`
                      : '确认正文内容完整、一致性检查通过后，才能进入投标检查'}
                  </div>
                </div>
              </div>
              {generateReviewConfirmed ? (
                <button onClick={async () => { setGenerateReviewConfirmed(false); try { await projectApi.resetGate(selectedProjectId, 'generate'); } catch { /* ignore */ } }} style={{ padding: '6px 14px', background: 'white', color: '#d97706', border: '1px solid #fbbf24', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}>撤回确认</button>
              ) : (
                <button onClick={handleConfirmGenerateReview} style={{ padding: '8px 20px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>确认正文审核通过</button>
              )}
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px' }}>
          {error}
        </div>
      )}

      {(() => {
        let nextAction: { label: string; onClick: () => void } | null = null;
        let nextMsg = '';
        if (selectedStructureTemplates.size > 0 && structureResult && activeSection === 'structure') {
          nextAction = { label: '下一步：编辑大纲', onClick: () => setActiveSection('outline') };
          nextMsg = '结构模板已应用';
        } else if (outlineGatePassed && activeSection === 'outline') {
          nextAction = { label: '下一步：生成正文', onClick: () => setActiveSection('generate') };
          nextMsg = '大纲审核已通过';
        } else if (generateGatePassed && activeSection === 'generate') {
          nextAction = { label: '下一步：投标检查', onClick: () => navigate('/check') };
          nextMsg = '正文审核已通过';
        }
        if (!nextAction) return null;
        return (
          <div style={{
            position: 'fixed',
            bottom: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '12px 24px',
            background: 'linear-gradient(135deg, #059669, #047857)',
            borderRadius: '16px',
            boxShadow: '0 8px 32px rgba(5, 150, 105, 0.35), 0 2px 8px rgba(0,0,0,0.1)',
            animation: 'slideUp 0.3s ease-out',
          }}>
            <CheckCircle2 size={18} color="white" />
            <span style={{ color: 'white', fontSize: '14px', fontWeight: 600 }}>
              {nextMsg}
            </span>
            <button
              onClick={nextAction.onClick}
              style={{
                padding: '8px 20px',
                background: 'white',
                color: '#059669',
                border: 'none',
                borderRadius: '10px',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'transform 0.15s, box-shadow 0.15s',
                boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)'; (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)'; (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)'; }}
            >
              {nextAction.label}
              <ArrowRight size={14} />
            </button>
          </div>
        );
      })()}

      <style>{`
        @keyframes slideUp {
          from { transform: translateX(-50%) translateY(20px); opacity: 0; }
          to { transform: translateX(-50%) translateY(0); opacity: 1; }
        }
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
        .skeleton-bar, .skeleton-circle {
          animation: skeleton-pulse 1.8s ease-in-out infinite;
        }
        @keyframes skeleton-pulse {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        .outline-loading-dots {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .outline-loading-dots span {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: var(--color-primary);
          animation: dot-bounce 1.4s ease-in-out infinite;
        }
        .outline-loading-dots span:nth-child(2) {
          animation-delay: 0.16s;
        }
        .outline-loading-dots span:nth-child(3) {
          animation-delay: 0.32s;
        }
        @keyframes dot-bounce {
          0%, 80%, 100% {
            transform: scale(0.6);
            opacity: 0.4;
          }
          40% {
            transform: scale(1.2);
            opacity: 1;
          }
        }
        .markdown-content {
          font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
          font-size: 14px;
          line-height: 1.8;
          color: #1e293b;
          word-break: break-word;
        }
        .markdown-content > *:first-child { margin-top: 0; }
        .markdown-content > *:last-child { margin-bottom: 0; }
        .markdown-content h1 { font-size: 1.6em; font-weight: 700; margin: 1.2em 0 0.6em; padding-bottom: 0.3em; border-bottom: 2px solid #059669; color: #0f172a; }
        .markdown-content h2 { font-size: 1.35em; font-weight: 700; margin: 1em 0 0.5em; padding-bottom: 0.2em; border-bottom: 1px solid #e2e8f0; color: #1e293b; }
        .markdown-content h3 { font-size: 1.15em; font-weight: 600; margin: 0.8em 0 0.4em; color: #334155; }
        .markdown-content h4 { font-size: 1.05em; font-weight: 600; margin: 0.7em 0 0.3em; color: #475569; }
        .markdown-content h5, .markdown-content h6 { font-size: 1em; font-weight: 600; margin: 0.6em 0 0.3em; color: #64748b; }
        .markdown-content p { margin: 0.6em 0; text-align: justify; }
        .markdown-content ul, .markdown-content ol { margin: 0.6em 0; padding-left: 1.8em; }
        .markdown-content li { margin: 0.25em 0; line-height: 1.75; }
        .markdown-content ul li { list-style-type: disc; }
        .markdown-content ul li li { list-style-type: circle; }
        .markdown-content ol li { list-style-type: decimal; }
        .markdown-content blockquote { margin: 0.8em 0; padding: 0.6em 1.2em; border-left: 4px solid #059669; background: #f0fdf4; border-radius: 0 6px 6px 0; color: #166534; }
        .markdown-content blockquote p { margin: 0.2em 0; }
        .markdown-content table { width: 100%; border-collapse: collapse; margin: 0.8em 0; font-size: 13px; }
        .markdown-content th { background: #059669; color: white; font-weight: 600; text-align: left; padding: 10px 14px; border: 1px solid #047857; }
        .markdown-content td { padding: 9px 14px; border: 1px solid #e2e8f0; }
        .markdown-content tr:nth-child(even) { background: #f8fafc; }
        .markdown-content tr:hover { background: #f0fdf4; }
        .markdown-content code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.88em; color: #e11d48; font-family: 'Fira Code', 'Consolas', monospace; }
        .markdown-content pre { background: #1e293b; color: #e2e8f0; padding: 16px 20px; border-radius: 8px; overflow-x: auto; margin: 0.8em 0; border: 1px solid #334155; }
        .markdown-content pre code { background: none; color: inherit; padding: 0; font-size: 0.88em; }
        .markdown-content hr { border: none; border-top: 2px solid #e2e8f0; margin: 2em 0; }
        .markdown-content strong { font-weight: 600; color: #0f172a; }
        .markdown-content em { font-style: italic; color: #475569; }
        .markdown-content a { color: #2563eb; text-decoration: none; border-bottom: 1px solid #93c5fd; }
        .markdown-content a:hover { color: #1d4ed8; border-bottom-color: #2563eb; }
        .markdown-content img { max-width: 100%; border-radius: 8px; margin: 0.8em 0; box-shadow: 0 2px 8px rgba(0,0,0,0.08); cursor: pointer; transition: box-shadow 0.2s; }
        .markdown-content img:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.15); }
        .markdown-content dl { margin: 0.8em 0; }
        .markdown-content dt { font-weight: 600; margin-top: 0.5em; }
        .markdown-content dd { margin-left: 1.5em; }
        .markdown-content sup.citation { font-size: 0.75em; vertical-align: super; color: #2563eb; }
      `}</style>
    </div>
  );
}
