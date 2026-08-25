import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Loader2, AlertTriangle, CheckCircle2, XCircle, Download, FileText, Upload, FolderOpen, Copy, ChevronDown, ChevronRight, Eye, BookOpen, AlertCircle, ArrowRight } from 'lucide-react';
import { List, useDynamicRowHeight } from 'react-window';
import { checkApi, projectApi, generateApi, type Project } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';
import MarkdownRenderer from '../components/common/MarkdownRenderer';

type CheckType = 'fullCheck' | 'compliance' | 'disqualification' | 'qualification' | 'pricing' | 'fitScore' | 'selfcheck' | 'deposit' | 'signature' | 'validity' | 'consistency' | 'duplicate' | 'mandatoryReq' | 'docIntegrity' | 'aiTextCheck' | 'riskScore' | 'crossCheck' | 'sampleReport' | 'jointBid' | 'ebidSubmit' | 'pricingLogic' | 'scoreCoverage';
type CheckMode = 'project' | 'upload';

interface CheckOption {
  key: CheckType;
  label: string;
  description: string;
  color: string;
}

interface ChapterInfo {
  id: string;
  title: string;
  word_count?: number;
  status?: string;
}

// --- Findings virtualized list (extracted to use react-window hook) ---

type FindingRowProps = {
  findings: Array<Record<string, unknown>>;
  index: number;
  style: React.CSSProperties;
  ariaAttributes: { 'aria-posinset': number; 'aria-setsize': number; role: 'listitem' };
};

const computeFindingHeight = (finding: Record<string, unknown>): number => {
  let h = 56;
  if (finding.description || finding.detail || finding.reason || finding.message) h += 24;
  if (finding.suggestion || finding.fix || finding.recommendation) h += 32;
  return h;
};

const FindingRow = ({ findings, index, style, ariaAttributes }: FindingRowProps) => {
  const finding = findings[index];
  const severity = (finding.severity || finding.level || 'info') as string;
  const title = (finding.title || finding.name || finding.item || `发现 #${index + 1}`) as string;
  const description = (finding.description || finding.detail || finding.reason || finding.message || '') as string;
  const suggestion = (finding.suggestion || finding.fix || finding.recommendation || '') as string;
  const sevColor = severity === 'high' || severity === 'critical' || severity === 'error' ? '#dc2626'
    : severity === 'medium' || severity === 'warning' ? '#d97706' : '#059669';
  const sevBg = severity === 'high' || severity === 'critical' || severity === 'error' ? '#fef2f2'
    : severity === 'medium' || severity === 'warning' ? '#fffbeb' : '#ecfdf5';
  return (
    <div {...ariaAttributes} style={{
      ...style,
      padding: '4px 0',
      boxSizing: 'border-box',
    }}>
      <div style={{
        padding: '10px 12px',
        border: '1px solid var(--color-border)',
        borderRadius: '6px',
        borderLeft: `3px solid ${sevColor}`,
        background: sevBg,
        height: '100%',
        boxSizing: 'border-box',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: description || suggestion ? '6px' : 0 }}>
          <span style={{
            fontSize: '10px',
            padding: '1px 6px',
            borderRadius: '8px',
            background: sevColor,
            color: 'white',
            fontWeight: 600,
            textTransform: 'uppercase',
          }}>
            {severity}
          </span>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)' }}>{title}</span>
        </div>
        {description && (
          <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>{description}</div>
        )}
        {suggestion && (
          <div style={{ fontSize: '12px', color: '#1e40af', marginTop: '4px', padding: '4px 8px', background: '#eff6ff', borderRadius: '4px' }}>
            💡 {suggestion}
          </div>
        )}
      </div>
    </div>
  );
};

const FINDING_VIRTUALIZE_THRESHOLD = 20;
const FINDING_LIST_MAX_HEIGHT = 600;

const VirtualizedFindingsList = ({ findings }: { findings: Array<Record<string, unknown>> }) => {
  const dynamic = useDynamicRowHeight({ defaultRowHeight: 80 });
  return (
    <List
      rowCount={findings.length}
      rowHeight={(index) => {
        const h = computeFindingHeight(findings[index] || {});
        if (dynamic.getRowHeight(index) !== undefined) {
          return dynamic.getRowHeight(index) as number;
        }
        return h;
      }}
      rowComponent={FindingRow}
      rowProps={{ findings } as never}
      overscanCount={4}
      style={{
        height: Math.min(FINDING_LIST_MAX_HEIGHT, findings.length * 80),
        border: '1px solid var(--color-border)',
        borderRadius: '6px',
        background: 'var(--color-bg)',
      }}
    />
  );
};

export default function CheckPage() {
  const [checkMode, setCheckMode] = useState<CheckMode>('project');
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const goToGenerate = useCallback(() => {
    if (selectedProjectId) {
      try { localStorage.setItem('bidmaster_focus_project', selectedProjectId); } catch { /* ignore */ }
    }
    navigate('/generate');
  }, [navigate, selectedProjectId]);
  const [results, setResults] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string>('');
  const [activeCheck, setActiveCheck] = useState<CheckType>('fullCheck');
  const [reports, setReports] = useState<Array<{ id: string; type: string; risk_level: string; created_at: string }>>([]);
  const [checkProgress, setCheckProgress] = useState<string>('');

  const [bidFile, setBidFile] = useState<File | null>(null);
  const [tenderFile, setTenderFile] = useState<File | null>(null);
  const bidFileRef = useRef<HTMLInputElement>(null);
  const tenderFileRef = useRef<HTMLInputElement>(null);

  const [projectChapters, setProjectChapters] = useState<ChapterInfo[]>([]);
  const [projectHasContent, setProjectHasContent] = useState<boolean>(false);
  const [projectTotalWords, setProjectTotalWords] = useState<number>(0);
  const [previewExpanded, setPreviewExpanded] = useState<boolean>(false);
  const [selectedChapterId, setSelectedChapterId] = useState<string>('');
  const [chapterContent, setChapterContent] = useState<string>('');
  const [chapterLoading, setChapterLoading] = useState<boolean>(false);
  const [exportingDocx, setExportingDocx] = useState<boolean>(false);

  const [reportPreviewOpen, setReportPreviewOpen] = useState<boolean>(false);
  const [reportPreviewData, setReportPreviewData] = useState<{ reportId: string; reportType: string; riskLevel: string; format: string; content: string; loading: boolean; error: string }>({
    reportId: '',
    reportType: '',
    riskLevel: '',
    format: 'markdown',
    content: '',
    loading: false,
    error: '',
  });

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
    if (selectedProjectId && checkMode === 'project') {
      loadProjectChapters(selectedProjectId);
    } else {
      setProjectChapters([]);
      setProjectHasContent(false);
      setProjectTotalWords(0);
    }
  }, [selectedProjectId, checkMode]);

  useEffect(() => {
    if (selectedChapterId && selectedProjectId) {
      loadChapterContent(selectedProjectId, selectedChapterId);
    } else {
      setChapterContent('');
    }
  }, [selectedChapterId, selectedProjectId]);

  const loadProjects = async () => {
    try {
      const res = await projectApi.list();
      setProjects(res.data.projects || []);
    } catch (e) {
      console.error('加载项目列表失败', e);
    }
  };

  const loadProjectChapters = async (projectId: string) => {
    try {
      const res = await generateApi.listChapters(projectId);
      const chapters = (res.data as { chapters?: ChapterInfo[] }).chapters || [];
      setProjectChapters(chapters);
      const totalWords = chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0);
      setProjectTotalWords(totalWords);
      setProjectHasContent(chapters.length > 0 && totalWords > 0);
    } catch (e) {
      console.error('加载章节列表失败', e);
      setProjectChapters([]);
      setProjectHasContent(false);
      setProjectTotalWords(0);
    }
  };

  const loadChapterContent = async (projectId: string, chapterId: string) => {
    setChapterLoading(true);
    try {
      const res = await generateApi.getChapterContent(projectId, chapterId);
      const chapter = (res.data as Record<string, unknown>)?.chapter as Record<string, string> | undefined;
      setChapterContent(chapter?.content || chapter?.markdown || '');
    } catch (e) {
      console.error('加载章节内容失败', e);
      setChapterContent('');
    } finally {
      setChapterLoading(false);
    }
  };

  const handleExportDocx = async () => {
    if (!selectedProjectId) return;
    setExportingDocx(true);
    try {
      const res = await generateApi.exportDocx(selectedProjectId);
      const blob = new Blob([res.data as unknown as BlobPart], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const projectName = projects.find(p => p.id === selectedProjectId)?.name || 'bid';
      a.download = `${projectName}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('导出Word失败', e);
      setError('导出Word失败');
    } finally {
      setExportingDocx(false);
    }
  };

  const checkOptions: CheckOption[] = [
    { key: 'fullCheck', label: '全面检查', description: '运行所有检查项', color: '#1a56db' },
    { key: 'compliance', label: '合规性检查', description: '逐条检查硬性要求响应', color: '#059669' },
    { key: 'disqualification', label: '废标项检查', description: '检查废标条款响应', color: '#dc2626' },
    { key: 'mandatoryReq', label: '★▲参数对照', description: '强制性参数逐条响应', color: '#dc2626' },
    { key: 'qualification', label: '资质核查', description: '证书有效期/名称/三证合一', color: '#d97706' },
    { key: 'deposit', label: '保证金核查', description: '金额/形式/到账/保函有效期', color: '#d97706' },
    { key: 'signature', label: '签章核查', description: '法人签字/公章/骑缝章/CA', color: '#d97706' },
    { key: 'validity', label: '有效期核查', description: '投标有效期/保函/资质/CA', color: '#475569' },
    { key: 'pricing', label: '报价核查', description: '限价/算术/大小写/安全区间', color: '#475569' },
    { key: 'consistency', label: '一致性校验', description: '跨章节数据一致性', color: '#0f766e' },
    { key: 'duplicate', label: '标书查重', description: '内部重复/模板痕迹检测', color: '#0f766e' },
    { key: 'docIntegrity', label: '文件完整性', description: '正副本/密封/页码/附件', color: '#be185d' },
    { key: 'fitScore', label: '贴合度评分', description: '内容贴合/针对性/通用套话', color: '#be185d' },
    { key: 'selfcheck', label: '废标自查', description: '20项自查清单', color: '#be185d' },
    { key: 'crossCheck', label: '交叉比对', description: '评分标准↔投标内容逐项对照', color: '#1a56db' },
    { key: 'aiTextCheck', label: 'AI文本检查', description: '拼写/标点/实体识别', color: '#059669' },
    { key: 'riskScore', label: '风险评分', description: '6维度加权综合风险评分', color: '#dc2626' },
    { key: 'sampleReport', label: '样品/检测报告', description: 'CMA/CNAS/检测项核查', color: '#d97706' },
    { key: 'jointBid', label: '联合投标协议', description: '联合体协议完整性核查', color: '#475569' },
    { key: 'ebidSubmit', label: '电子投标提交', description: 'OFD/PDF/CA签章核查', color: '#0f766e' },
    { key: 'pricingLogic', label: '报价逻辑闭环', description: '人天×单价/成本分配验证', color: '#be185d' },
    { key: 'scoreCoverage', label: '评分覆盖检查', description: '评分项↔正文内容覆盖核查', color: '#059669' },
  ];

  const handleProjectCheck = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    setResults(null);
    setCheckProgress('');
    try {
      if (activeCheck === 'fullCheck') {
        const submitRes = await checkApi.fullCheck(selectedProjectId);
        const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
        if (taskId) {
          setCheckProgress('全面检查任务已提交...');
          const result = await checkApi.pollCheckTask(taskId, (msg) => setCheckProgress(msg));
          setResults(result);
          setCheckProgress('');
          return;
        }
        setResults(submitRes.data);
        return;
      }

      if (activeCheck === 'scoreCoverage') {
        const submitRes = await generateApi.scoreCoverage(selectedProjectId);
        const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
        if (taskId) {
          setCheckProgress('评分覆盖检查任务已提交...');
          const result = await generateApi.pollTask(taskId, (msg) => setCheckProgress(msg));
          setResults(result);
          setCheckProgress('');
          return;
        }
        setResults(submitRes.data);
        return;
      }

      // All other checks: unified submit + poll
      const submitRes = await checkApi.submitCheck(selectedProjectId, activeCheck);
      const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
      if (taskId) {
        setCheckProgress(`${activeCheck} 检查任务已提交...`);
        const result = await checkApi.pollCheckTask(taskId, (msg) => setCheckProgress(msg));
        setResults(result);
        setCheckProgress('');
        return;
      }
      setResults(submitRes.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '检查失败');
    } finally {
      setLoading(false);
      setCheckProgress('');
      if (checkMode === 'project') loadReports();
    }
  };

  const handleUploadCheck = async () => {
    if (!bidFile) {
      setError('请先上传投标文件');
      return;
    }
    setLoading(true);
    setError('');
    setResults(null);
    try {
      const res = await checkApi.uploadCheck(bidFile, tenderFile, activeCheck);
      setResults(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '检查失败');
    } finally {
      setLoading(false);
      if (checkMode === 'project') loadReports();
    }
  };

  const handleCheck = () => {
    if (checkMode === 'upload') {
      handleUploadCheck();
    } else {
      handleProjectCheck();
    }
  };

  const getRiskColor = (level: string) => {
    switch (level) {
      case 'high': return '#dc2626';
      case 'medium': return '#d97706';
      case 'low': return '#059669';
      default: return '#6b7280';
    }
  };

  const getRiskLabel = (level: string) => {
    switch (level) {
      case 'high': return '高风险';
      case 'medium': return '中风险';
      case 'low': return '低风险';
      default: return '未知';
    }
  };

  const loadReports = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await checkApi.listReports(selectedProjectId);
      setReports(res.data.reports || []);
    } catch (e) {
      console.error('加载报告列表失败', e);
    }
  };

  const handleExportReport = async (reportId: string, format: string = 'markdown') => {
    if (!selectedProjectId) return;
    try {
      const res = await checkApi.exportReport(selectedProjectId, reportId, format);
      const blob = new Blob([res.data as unknown as BlobPart], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `check_report_${reportId.slice(0, 8)}.${format === 'markdown' ? 'md' : format === 'html' ? 'html' : 'json'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('导出报告失败', e);
    }
  };

  const handlePreviewReport = async (report: { id: string; type: string; risk_level: string }, format: 'markdown' | 'html' = 'markdown') => {
    if (!selectedProjectId) return;
    setReportPreviewData({
      reportId: report.id,
      reportType: report.type,
      riskLevel: report.risk_level,
      format,
      content: '',
      loading: true,
      error: '',
    });
    setReportPreviewOpen(true);
    try {
      const res = await checkApi.getReportContent(selectedProjectId, report.id, format);
      const payload = res.data as { success: boolean; content: string; error: string };
      if (payload.success) {
        setReportPreviewData(prev => ({ ...prev, content: payload.content || '', loading: false }));
      } else {
        setReportPreviewData(prev => ({ ...prev, error: payload.error || '加载失败', loading: false }));
      }
    } catch (e: unknown) {
      setReportPreviewData(prev => ({
        ...prev,
        error: e instanceof Error ? e.message : '加载报告内容失败',
        loading: false,
      }));
    }
  };

  useEffect(() => {
    if (selectedProjectId && checkMode === 'project') loadReports();
  }, [selectedProjectId, checkMode]);

  const renderUploadZone = (
    label: string,
    file: File | null,
    setFileFn: (f: File | null) => void,
    ref: React.RefObject<HTMLInputElement | null>,
    accept: string,
    required: boolean,
  ) => (
    <div>
      <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>
        {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
      </label>
      <div
        onClick={() => ref.current?.click()}
        style={{
          border: `2px dashed ${file ? '#059669' : 'var(--color-border)'}`,
          borderRadius: '10px',
          padding: '20px',
          textAlign: 'center',
          cursor: 'pointer',
          background: file ? '#ecfdf5' : '#f8fafc',
          transition: 'all 0.2s',
        }}
      >
        <Upload size={24} color={file ? '#059669' : '#94a3b8'} style={{ margin: '0 auto 8px' }} />
        <div style={{ fontSize: '13px', fontWeight: 500 }}>
          {file ? file.name : '点击上传文件'}
        </div>
        {file && (
          <div style={{ fontSize: '11px', color: '#059669', marginTop: '4px' }}>
            {(file.size / 1024).toFixed(1)} KB
          </div>
        )}
        {!file && (
          <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
            支持 .docx .pdf .txt .md 格式
          </div>
        )}
      </div>
      <input
        ref={ref}
        type="file"
        accept={accept}
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) {
            setFileFn(e.target.files[0]);
          }
        }}
        style={{ display: 'none' }}
      />
      {file && (
        <button
          onClick={(e) => { e.stopPropagation(); setFileFn(null); }}
          style={{ marginTop: '4px', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', color: '#dc2626' }}
        >
          移除文件
        </button>
      )}
    </div>
  );

  const [showFullReport, setShowFullReport] = useState(false);

  const renderFullCheckSummary = (data: Record<string, unknown>) => {
    const checks = Object.entries(data);
    let passCount = 0;
    let failCount = 0;
    let errorCount = 0;

    const checkItems = checks.map(([key, val]) => {
      const v = val as Record<string, unknown>;
      const d = (v.data || {}) as Record<string, unknown>;
      const success = v.success as boolean;
      const riskLevel = d.risk_level as string || 'low';
      const hasCritical = d.has_critical_issues as boolean || false;
      const isHigh = riskLevel === 'high' || hasCritical;

      if (!success) errorCount++;
      else if (isHigh) failCount++;
      else passCount++;

      const label = checkOptions.find(o => o.key === key)?.label || key;

      return { key, label, success, riskLevel, hasCritical, isHigh, data: d };
    });

    return (
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
          <div style={{ padding: '8px', background: '#ecfdf5', borderRadius: '6px', textAlign: 'center' }}>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#059669' }}>{passCount}</div>
            <div style={{ fontSize: '10px', color: '#059669' }}>通过</div>
          </div>
          <div style={{ padding: '8px', background: '#fef2f2', borderRadius: '6px', textAlign: 'center' }}>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#dc2626' }}>{failCount}</div>
            <div style={{ fontSize: '10px', color: '#dc2626' }}>存在问题</div>
          </div>
          <div style={{ padding: '8px', background: '#fffbeb', borderRadius: '6px', textAlign: 'center' }}>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#d97706' }}>{errorCount}</div>
            <div style={{ fontSize: '10px', color: '#d97706' }}>执行异常</div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {checkItems.map(item => (
            <div
              key={item.key}
              onClick={() => { setActiveCheck(item.key as CheckType); }}
              style={{
                padding: '8px 12px',
                border: '1px solid var(--color-border)',
                borderRadius: '6px',
                borderLeft: item.isHigh ? '3px solid #dc2626' : item.success ? '3px solid #059669' : '3px solid #d97706',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                cursor: 'pointer',
                transition: 'background 0.15s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#f8fafc'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
              title="点击查看此项检查的详细报告"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {item.success ? (
                  item.isHigh ? <XCircle size={14} color="#dc2626" /> : <CheckCircle2 size={14} color="#059669" />
                ) : (
                  <AlertTriangle size={14} color="#d97706" />
                )}
                <span style={{ fontSize: '12px', fontWeight: 500 }}>{item.label}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{
                  fontSize: '11px',
                  padding: '1px 6px',
                  borderRadius: '8px',
                  background: item.isHigh ? '#fef2f2' : item.success ? '#ecfdf5' : '#fffbeb',
                  color: item.isHigh ? '#dc2626' : item.success ? '#059669' : '#d97706',
                }}>
                  {item.isHigh ? '高风险' : item.success ? '通过' : '异常'}
                </span>
                <Eye size={12} color="var(--color-text-secondary)" />
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={() => setShowFullReport(true)}
          style={{
            width: '100%',
            marginTop: '12px',
            padding: '8px 12px',
            background: 'var(--color-primary)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px',
          }}
        >
          <FileText size={14} /> 查看最终检查报告
        </button>

        {showFullReport && (
          <div
            onClick={() => setShowFullReport(false)}
            style={{
              position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
              background: 'rgba(0,0,0,0.5)', zIndex: 9999,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '20px',
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                background: 'white', borderRadius: '12px',
                width: '90%', maxWidth: '900px', height: '85vh',
                display: 'flex', flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              <div style={{
                padding: '16px 20px', borderBottom: '1px solid var(--color-border)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <div>
                  <h2 style={{ fontSize: '16px', fontWeight: 600, margin: 0 }}>最终检查报告</h2>
                  <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0' }}>
                    通过 {passCount} 项 · 存在风险 {failCount} 项 · 异常 {errorCount} 项
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => {
                      const lines: string[] = [`# 最终检查报告\n`, `生成时间: ${new Date().toLocaleString('zh-CN')}\n`];
                      lines.push(`## 概览\n通过: ${passCount} | 风险: ${failCount} | 异常: ${errorCount}\n`);
                      lines.push(`## 详细结果\n`);
                      checkItems.forEach(item => {
                        const d = item.data as Record<string, unknown>;
                        lines.push(`### ${item.label} - ${item.isHigh ? '高风险' : item.success ? '通过' : '异常'}`);
                        lines.push(`风险等级: ${item.riskLevel || '-'}`);
                        if (d.summary) lines.push(`摘要: ${String(d.summary)}`);
                        if (Array.isArray(d.findings) && d.findings.length > 0) {
                          lines.push(`发现问题数: ${(d.findings as unknown[]).length}`);
                        }
                        if (d.suggestion) lines.push(`建议: ${String(d.suggestion)}`);
                        if (d.overall_assessment) lines.push(`评估: ${String(d.overall_assessment)}`);
                        lines.push('');
                      });
                      const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url; a.download = `check-report-${Date.now()}.md`; a.click();
                      URL.revokeObjectURL(url);
                    }}
                    style={{ padding: '6px 12px', background: 'white', color: 'var(--color-primary)', border: '1px solid var(--color-primary)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <Download size={12} /> 下载报告
                  </button>
                  <button
                    onClick={() => setShowFullReport(false)}
                    style={{ padding: '6px 12px', background: '#f1f5f9', color: 'var(--color-text)', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                  >
                    关闭
                  </button>
                </div>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '20px', background: '#f8fafc' }}>
                {checkItems.map(item => {
                  const d = item.data as Record<string, unknown>;
                  return (
                    <div key={item.key} style={{ background: 'white', borderRadius: '8px', padding: '16px', marginBottom: '12px', border: '1px solid var(--color-border)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
                          {item.success ? (
                            item.isHigh ? <XCircle size={16} color="#dc2626" /> : <CheckCircle2 size={16} color="#059669" />
                          ) : <AlertTriangle size={16} color="#d97706" />}
                          {item.label}
                        </h3>
                        <span style={{
                          fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                          background: item.isHigh ? '#fef2f2' : item.success ? '#ecfdf5' : '#fffbeb',
                          color: item.isHigh ? '#dc2626' : item.success ? '#059669' : '#d97706',
                          fontWeight: 500,
                        }}>
                          {item.isHigh ? '高风险' : item.success ? '通过' : '执行异常'}
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px' }}>
                        <div>风险等级: <strong style={{ color: '#0f172a' }}>{item.riskLevel || '-'}</strong></div>
                        <div>是否存在严重问题: <strong style={{ color: '#0f172a' }}>{item.hasCritical ? '是' : '否'}</strong></div>
                        {d.summary != null && <div style={{ gridColumn: '1 / -1' }}>摘要: {String(d.summary)}</div>}
                        {d.overall_assessment != null && <div style={{ gridColumn: '1 / -1' }}>整体评估: {String(d.overall_assessment)}</div>}
                        {Array.isArray(d.findings) && (d.findings as unknown[]).length > 0 && (
                          <div style={{ gridColumn: '1 / -1', marginTop: '4px' }}>
                            <div style={{ fontWeight: 500, marginBottom: '4px' }}>发现问题 ({String((d.findings as unknown[]).length)}):</div>
                            {(d.findings as Array<Record<string, unknown>>).slice(0, 5).map((f, i) => (
                              <div key={i} style={{ background: '#f8fafc', padding: '6px 8px', borderRadius: '4px', marginBottom: '3px', fontSize: '11px' }}>
                                <div>• {String(f.title || f.issue || f.description || JSON.stringify(f))}</div>
                                {f.severity != null && <div style={{ color: 'var(--color-text-secondary)' }}>严重度: {String(f.severity)}</div>}
                              </div>
                            ))}
                            {(d.findings as unknown[]).length > 5 && <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>...还有 {String((d.findings as unknown[]).length - 5)} 项</div>}
                          </div>
                        )}
                        {d.suggestion != null && <div style={{ gridColumn: '1 / -1' }}>建议: {String(d.suggestion)}</div>}
                        {d.raw_text != null && <details style={{ gridColumn: '1 / -1', marginTop: '6px' }}><summary style={{ cursor: 'pointer', fontSize: '11px' }}>查看原始输出</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px', background: '#f1f5f9', padding: '8px', borderRadius: '4px', marginTop: '4px' }}>{String(d.raw_text).slice(0, 2000)}</pre></details>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderStructuredFindings = (findings: Array<Record<string, unknown>>) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px', color: 'var(--color-text)' }}>
        发现问题 ({findings.length})
      </div>
      {findings.length > FINDING_VIRTUALIZE_THRESHOLD ? (
        <VirtualizedFindingsList findings={findings} />
      ) : (
        findings.map((finding, idx) => {
          const severity = (finding.severity || finding.level || 'info') as string;
          const title = (finding.title || finding.name || finding.item || `发现 #${idx + 1}`) as string;
          const description = (finding.description || finding.detail || finding.reason || finding.message || '') as string;
          const suggestion = (finding.suggestion || finding.fix || finding.recommendation || '') as string;
          const sevColor = severity === 'high' || severity === 'critical' || severity === 'error' ? '#dc2626'
            : severity === 'medium' || severity === 'warning' ? '#d97706' : '#059669';
          const sevBg = severity === 'high' || severity === 'critical' || severity === 'error' ? '#fef2f2'
            : severity === 'medium' || severity === 'warning' ? '#fffbeb' : '#ecfdf5';

          return (
            <div key={idx} style={{
              padding: '10px 12px',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              borderLeft: `3px solid ${sevColor}`,
              background: sevBg,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: description || suggestion ? '6px' : 0 }}>
                <span style={{
                  fontSize: '10px',
                  padding: '1px 6px',
                  borderRadius: '8px',
                  background: sevColor,
                  color: 'white',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                }}>
                  {severity}
                </span>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)' }}>{title}</span>
              </div>
              {description && (
                <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>{description}</div>
              )}
              {suggestion && (
                <div style={{ fontSize: '12px', color: '#1e40af', marginTop: '4px', padding: '4px 8px', background: '#eff6ff', borderRadius: '4px' }}>
                  💡 {suggestion}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );

  const renderStructuredChecks = (checks: Array<Record<string, unknown>>) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px', color: 'var(--color-text)' }}>
        检查项 ({checks.length})
      </div>
      {checks.map((check, idx) => {
        const passed = (check.passed || check.pass || check.status === 'pass' || check.status === 'passed') as boolean;
        const name = (check.name || check.item || check.title || check.requirement || `检查项 #${idx + 1}`) as string;
        const detail = (check.detail || check.description || check.reason || check.message || '') as string;

        return (
          <div key={idx} style={{
            padding: '8px 12px',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '8px',
            background: passed ? '#f0fdf4' : '#fef2f2',
          }}>
            {passed ? <CheckCircle2 size={14} color="#059669" style={{ marginTop: '2px', flexShrink: 0 }} /> : <XCircle size={14} color="#dc2626" style={{ marginTop: '2px', flexShrink: 0 }} />}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '12px', fontWeight: 500, color: 'var(--color-text)' }}>{name}</div>
              {detail && <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>{detail}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );

  const renderStructuredSuggestions = (suggestions: Array<Record<string, unknown> | string>) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px', color: 'var(--color-text)' }}>
        改进建议 ({suggestions.length})
      </div>
      {suggestions.map((sug, idx) => {
        const text = typeof sug === 'string' ? sug : ((sug as Record<string, unknown>).title || (sug as Record<string, unknown>).description || (sug as Record<string, unknown>).text || (sug as Record<string, unknown>).content || JSON.stringify(sug)) as string;
        const priority = typeof sug === 'string' ? '' : ((sug as Record<string, unknown>).priority || (sug as Record<string, unknown>).severity || '') as string;
        const priColor = priority === 'high' || priority === 'critical' ? '#dc2626' : priority === 'medium' ? '#d97706' : '#059669';

        return (
          <div key={idx} style={{
            padding: '8px 12px',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            background: '#eff6ff',
          }}>
            {priority && (
              <span style={{
                fontSize: '10px',
                padding: '1px 6px',
                borderRadius: '8px',
                background: priColor,
                color: 'white',
                fontWeight: 600,
                flexShrink: 0,
              }}>
                {priority}
              </span>
            )}
            <span style={{ fontSize: '12px', color: '#1e40af' }}>{text}</span>
          </div>
        );
      })}
    </div>
  );

  const renderSingleCheckResult = (data: Record<string, unknown>) => {
    const riskLevel = data.risk_level as string || 'low';
    const hasCritical = data.has_critical_issues as boolean || false;
    const findings = (data.findings || data.issues || data.problems || data.items || []) as Array<Record<string, unknown>>;
    const checks = (data.checks || data.check_items || data.details || []) as Array<Record<string, unknown>>;
    const suggestions = (data.suggestions || data.recommendations || data.fixes || data.actions || []) as Array<Record<string, unknown> | string>;
    const hasStructuredData = (Array.isArray(findings) && findings.length > 0) || (Array.isArray(checks) && checks.length > 0);

    return (
      <div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '10px 12px',
          borderRadius: '6px',
          marginBottom: '12px',
          background: `${getRiskColor(riskLevel)}15`,
        }}>
          {riskLevel === 'high' || hasCritical ? (
            <XCircle size={18} color="#dc2626" />
          ) : (
            <CheckCircle2 size={18} color="#059669" />
          )}
          <span style={{ fontWeight: 600, color: getRiskColor(riskLevel), fontSize: '14px' }}>
            风险等级：{getRiskLabel(riskLevel)}
          </span>
          {data.score !== undefined && (
            <span style={{ marginLeft: '12px', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
              评分：{String(data.score)}
            </span>
          )}
        </div>

        {hasStructuredData ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {Array.isArray(checks) && checks.length > 0 && renderStructuredChecks(checks)}
            {Array.isArray(findings) && findings.length > 0 && renderStructuredFindings(findings)}
            {Array.isArray(suggestions) && suggestions.length > 0 && renderStructuredSuggestions(suggestions)}
          </div>
        ) : (
          <div style={{ position: 'relative' }}>
            <button
              onClick={async () => {
                try { await navigator.clipboard.writeText(JSON.stringify(data, null, 2)); } catch { /* fallback */ }
                const btn = document.getElementById('check-copy-btn');
                if (btn) { btn.textContent = '已复制'; setTimeout(() => { btn.textContent = '复制'; }, 2000); }
              }}
              id="check-copy-btn"
              style={{ position: 'absolute', top: '8px', right: '8px', zIndex: 1, padding: '4px 8px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px', color: '#64748b' }}
            >
              <Copy size={12} /> 复制
            </button>
            <pre style={{ background: '#f8fafc', padding: '16px', borderRadius: '8px', fontSize: '12px', overflow: 'auto', maxHeight: '500px', paddingRight: '60px' }}>
              {JSON.stringify(data, null, 2)}
            </pre>
          </div>
        )}
      </div>
    );
  };

  const renderProjectSelector = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)', marginBottom: '20px' }}>
      <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px' }}>选择项目</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <select
          value={selectedProjectId}
          onChange={(e) => { setSelectedProjectId(e.target.value); setSelectedChapterId(''); setChapterContent(''); }}
          style={{ flex: 1, padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
        >
          <option value="">请选择项目</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name} ({p.status})</option>
          ))}
        </select>
        {selectedProjectId && (
          projectHasContent ? (
            <span style={{
              fontSize: '11px',
              padding: '4px 10px',
              borderRadius: '12px',
              background: '#ecfdf5',
              color: '#059669',
              fontWeight: 600,
              whiteSpace: 'nowrap',
              border: '1px solid #a7f3d0',
            }}>
              已生成 {projectChapters.length} 章 / {projectTotalWords.toLocaleString()} 字
            </span>
          ) : (
            <span style={{
              fontSize: '11px',
              padding: '4px 10px',
              borderRadius: '12px',
              background: '#fef2f2',
              color: '#dc2626',
              fontWeight: 600,
              whiteSpace: 'nowrap',
              border: '1px solid #fecaca',
            }}>
              未生成正文
            </span>
          )
        )}
      </div>
      {selectedProjectId && !projectHasContent && (
        <div style={{
          marginTop: '10px',
          padding: '12px 14px',
          background: '#fef2f2',
          border: '1px solid #fecaca',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'flex-start',
          gap: '10px',
        }}>
          <AlertCircle size={18} color="#dc2626" style={{ flexShrink: 0, marginTop: '1px' }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#991b1b' }}>
              该项目尚未生成正文内容
            </div>
            <div style={{ fontSize: '12px', color: '#7f1d1d', marginTop: '4px', lineHeight: 1.5 }}>
              投标检查需要基于标书正文进行AI审核。可以先到「投标生成」完成正文生成，或改为上传已有标书进行检查。
            </div>
            <div style={{ display: 'flex', gap: '6px', marginTop: '10px' }}>
              <button
                onClick={goToGenerate}
                style={{
                  padding: '6px 12px', background: '#dc2626', color: 'white',
                  border: 'none', borderRadius: '5px', cursor: 'pointer',
                  fontSize: '12px', fontWeight: 500,
                  display: 'flex', alignItems: 'center', gap: '4px',
                }}
              >
                前往生成正文 <ArrowRight size={12} />
              </button>
              <button
                onClick={() => setCheckMode('upload')}
                style={{
                  padding: '6px 12px', background: 'white', color: '#dc2626',
                  border: '1px solid #fca5a5', borderRadius: '5px', cursor: 'pointer',
                  fontSize: '12px',
                  display: 'flex', alignItems: 'center', gap: '4px',
                }}
              >
                <Upload size={12} /> 改为上传文件
              </button>
            </div>
          </div>
        </div>
      )}
      {selectedProjectId && projectHasContent && (
        <div style={{ marginTop: '12px' }}>
          <button
            onClick={() => { setPreviewExpanded(!previewExpanded); if (!previewExpanded && !selectedChapterId && projectChapters.length > 0) { setSelectedChapterId(projectChapters[0].id); } }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
              color: 'var(--color-text)',
            }}
          >
            {previewExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <BookOpen size={14} /> 预览标书
          </button>
          {previewExpanded && (
            <div style={{ marginTop: '10px', display: 'flex', gap: '12px', border: '1px solid var(--color-border)', borderRadius: '8px', overflow: 'hidden', maxHeight: '400px' }}>
              <div style={{ width: '240px', borderRight: '1px solid var(--color-border)', overflowY: 'auto', background: '#f8fafc', flexShrink: 0 }}>
                {projectChapters.map(ch => (
                  <div
                    key={ch.id}
                    onClick={() => setSelectedChapterId(ch.id)}
                    style={{
                      padding: '8px 12px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: selectedChapterId === ch.id ? 600 : 400,
                      color: selectedChapterId === ch.id ? 'var(--color-primary)' : 'var(--color-text)',
                      background: selectedChapterId === ch.id ? '#eff6ff' : 'transparent',
                      borderLeft: selectedChapterId === ch.id ? '3px solid var(--color-primary)' : '3px solid transparent',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ch.title}</span>
                    {ch.word_count !== undefined && (
                      <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)', flexShrink: 0, marginLeft: '4px' }}>{ch.word_count}字</span>
                    )}
                  </div>
                ))}
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
                {chapterLoading ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                    <Loader2 size={16} className="animate-spin" style={{ marginRight: '8px' }} /> 加载中...
                  </div>
                ) : chapterContent ? (
                  <MarkdownRenderer>{chapterContent}</MarkdownRenderer>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                    点击左侧章节查看内容
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );

  const renderCheckOptionsGrid = () => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '20px' }}>
      {checkOptions.map(opt => {
        const needsTender = ['compliance', 'disqualification', 'mandatoryReq', 'crossCheck', 'fitScore'].includes(opt.key);
        const disabled = checkMode === 'upload' && needsTender && !tenderFile;

        return (
          <div
            key={opt.key}
            onClick={() => { if (!disabled) setActiveCheck(opt.key); }}
            style={{
              padding: '12px',
              borderRadius: '8px',
              border: `2px solid ${activeCheck === opt.key ? opt.color : 'var(--color-border)'}`,
              background: activeCheck === opt.key ? `${opt.color}10` : disabled ? '#f9fafb' : 'var(--color-surface)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s',
              opacity: disabled ? 0.5 : 1,
            }}
          >
            <div style={{ fontSize: '13px', fontWeight: 600, color: activeCheck === opt.key ? opt.color : disabled ? '#9ca3af' : 'var(--color-text)' }}>
              {opt.label}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
              {opt.description}
            </div>
            {disabled && (
              <div style={{ fontSize: '10px', color: '#d97706', marginTop: '2px' }}>需上传招标文件</div>
            )}
          </div>
        );
      })}
    </div>
  );

  const isCheckDisabled = loading || (checkMode === 'project' && (!selectedProjectId || !projectHasContent)) || (checkMode === 'upload' && !bidFile);

  const renderCheckButton = () => (
    <button
      onClick={handleCheck}
      disabled={isCheckDisabled}
      title={checkMode === 'project' && selectedProjectId && !projectHasContent ? '请先生成正文内容' : undefined}
      style={{
        width: '100%',
        padding: '12px',
        background: checkOptions.find(o => o.key === activeCheck)?.color || 'var(--color-primary)',
        color: 'white',
        border: 'none',
        borderRadius: '8px',
        cursor: isCheckDisabled ? 'not-allowed' : 'pointer',
        fontSize: '14px',
        fontWeight: 600,
        opacity: isCheckDisabled ? 0.5 : 1,
        marginBottom: '20px',
      }}
    >
      {loading ? (checkProgress || '检查中...') : `运行${checkOptions.find(o => o.key === activeCheck)?.label || '检查'}`}
    </button>
  );

  const renderResultsPanel = () => {
    if (!results) return null;

    const activeLabel = checkOptions.find(o => o.key === activeCheck)?.label || '检查';
    const singleData = (results as Record<string, unknown>).data as Record<string, unknown> | undefined;
    const riskLevel = activeCheck === 'fullCheck'
      ? ''
      : (singleData?.risk_level as string || 'low');

    return (
      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--color-border)', height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>
              {activeLabel}结果
            </h3>
            {riskLevel && (
              <span style={{
                fontSize: '11px',
                padding: '2px 8px',
                borderRadius: '10px',
                background: `${getRiskColor(riskLevel)}15`,
                color: getRiskColor(riskLevel),
                fontWeight: 600,
              }}>
                {getRiskLabel(riskLevel)}
              </span>
            )}
            {(results as Record<string, unknown>).source === 'upload' && (
              <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>
                来源：上传文件
              </span>
            )}
          </div>
          {checkMode === 'project' && selectedProjectId && (
            <button
              onClick={handleExportDocx}
              disabled={exportingDocx}
              style={{
                padding: '6px 14px',
                background: '#2563eb',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: exportingDocx ? 'not-allowed' : 'pointer',
                fontSize: '12px',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                opacity: exportingDocx ? 0.6 : 1,
              }}
            >
              {exportingDocx ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
              下载标书Word
            </button>
          )}
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {activeCheck === 'fullCheck' && typeof results === 'object' && results !== null && 'data' in results
            ? renderFullCheckSummary((results as Record<string, unknown>).data as Record<string, unknown>)
            : renderSingleCheckResult((results as Record<string, unknown>).data as Record<string, unknown>)}
        </div>
      </div>
    );
  };

  return (
    <div className="page-fade-in">
      <StepHeader
        step={3}
        title="投标检查"
        subtitle="上传已有标书直接检查，或从项目中检查，21项全面审核"
        color="#d97706"
        nextPath="/format"
        nextLabel="下一步：文档输出"
      />

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {([
          { key: 'upload' as CheckMode, label: '上传标书检查', icon: <Upload size={14} /> },
          { key: 'project' as CheckMode, label: '项目检查', icon: <FolderOpen size={14} /> },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => { setCheckMode(tab.key); setResults(null); setError(''); }}
            style={{
              padding: '8px 16px',
              background: checkMode === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
              color: checkMode === tab.key ? 'white' : 'var(--color-text)',
              border: `1px solid ${checkMode === tab.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
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

      {results ? (
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
          <div style={{ width: '40%', flexShrink: 0, maxHeight: 'calc(100vh - 200px)', overflowY: 'auto', paddingRight: '4px' }}>
            {checkMode === 'upload' && (
              <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)', marginBottom: '20px' }}>
                <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>上传标书文件</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                  {renderUploadZone('投标文件（必填）', bidFile, setBidFile, bidFileRef, '.docx,.pdf,.txt,.md', true)}
                  {renderUploadZone('招标文件（可选）', tenderFile, setTenderFile, tenderFileRef, '.docx,.pdf,.txt,.md', false)}
                </div>
                <div style={{ marginTop: '12px', padding: '10px', background: '#f0f9ff', borderRadius: '6px', fontSize: '12px', color: '#1e40af' }}>
                  💡 上传招标文件后可进行合规性检查、废标项检查、★▲参数对照等需要对照招标文件的检查项。仅上传投标文件时，可进行标书查重、AI文本检查、报价核查等。
                </div>
              </div>
            )}
            {checkMode === 'project' && renderProjectSelector()}
            {renderCheckOptionsGrid()}
            {renderCheckButton()}
          </div>
          <div style={{ width: '1px', background: 'var(--color-border)', alignSelf: 'stretch', flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0, maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' }}>
            {renderResultsPanel()}
          </div>
        </div>
      ) : (
        <>
          {checkMode === 'upload' && (
            <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)', marginBottom: '20px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>上传标书文件</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                {renderUploadZone('投标文件（必填）', bidFile, setBidFile, bidFileRef, '.docx,.pdf,.txt,.md', true)}
                {renderUploadZone('招标文件（可选）', tenderFile, setTenderFile, tenderFileRef, '.docx,.pdf,.txt,.md', false)}
              </div>
              <div style={{ marginTop: '12px', padding: '10px', background: '#f0f9ff', borderRadius: '6px', fontSize: '12px', color: '#1e40af' }}>
                💡 上传招标文件后可进行合规性检查、废标项检查、★▲参数对照等需要对照招标文件的检查项。仅上传投标文件时，可进行标书查重、AI文本检查、报价核查等。
              </div>
            </div>
          )}
          {checkMode === 'project' && renderProjectSelector()}
          {renderCheckOptionsGrid()}
          {renderCheckButton()}
        </>
      )}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {checkMode === 'project' && reports.length > 0 && (
        <div style={{ marginTop: '20px', background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>检查报告</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {reports.map(report => (
              <div key={report.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', border: '1px solid var(--color-border)', borderRadius: '8px' }}>
                <div>
                  <span style={{ fontSize: '13px', fontWeight: 500 }}>{report.type}</span>
                  <span style={{ fontSize: '12px', color: getRiskColor(report.risk_level), marginLeft: '8px' }}>
                    {getRiskLabel(report.risk_level)}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginLeft: '8px' }}>
                    {report.created_at ? new Date(report.created_at).toLocaleString() : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button onClick={() => handlePreviewReport(report, 'markdown')} style={{ padding: '4px 10px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Eye size={10} /> 预览
                  </button>
                  <button onClick={() => handleExportReport(report.id, 'markdown')} style={{ padding: '4px 10px', background: '#059669', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Download size={10} /> Markdown
                  </button>
                  <button onClick={() => handleExportReport(report.id, 'html')} style={{ padding: '4px 10px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Download size={10} /> HTML
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {reportPreviewOpen && (
        <div
          onClick={() => setReportPreviewOpen(false)}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', zIndex: 9999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'white', borderRadius: '12px',
              width: '90%', maxWidth: '1000px', height: '88vh',
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}
          >
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid var(--color-border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <h2 style={{ fontSize: '16px', fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <FileText size={18} color="var(--color-primary)" />
                  {reportPreviewData.reportType} 检查报告
                </h2>
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0' }}>
                  风险等级: <span style={{ color: getRiskColor(reportPreviewData.riskLevel), fontWeight: 500 }}>{getRiskLabel(reportPreviewData.riskLevel)}</span>
                </p>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <div style={{ display: 'flex', border: '1px solid var(--color-border)', borderRadius: '6px', overflow: 'hidden' }}>
                  {(['markdown', 'html'] as const).map(fmt => (
                    <button
                      key={fmt}
                      onClick={() => handlePreviewReport({ id: reportPreviewData.reportId, type: reportPreviewData.reportType, risk_level: reportPreviewData.riskLevel }, fmt)}
                      style={{
                        padding: '6px 12px',
                        background: reportPreviewData.format === fmt ? 'var(--color-primary)' : 'white',
                        color: reportPreviewData.format === fmt ? 'white' : 'var(--color-text)',
                        border: 'none',
                        cursor: 'pointer',
                        fontSize: '12px',
                      }}
                    >
                      {fmt === 'markdown' ? 'Markdown' : 'HTML'}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => handleExportReport(reportPreviewData.reportId, reportPreviewData.format)}
                  style={{ padding: '6px 12px', background: 'white', color: 'var(--color-primary)', border: '1px solid var(--color-primary)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <Download size={12} /> 下载
                </button>
                <button
                  onClick={() => setReportPreviewOpen(false)}
                  style={{ padding: '6px 12px', background: '#f1f5f9', color: 'var(--color-text)', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  关闭
                </button>
              </div>
            </div>
            <div style={{ flex: 1, overflow: 'auto', background: '#f8fafc' }}>
              {reportPreviewData.loading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '8px' }}>
                  <Loader2 size={32} className="animate-spin" color="var(--color-primary)" />
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '13px' }}>加载报告内容中...</span>
                </div>
              ) : reportPreviewData.error ? (
                <div style={{ padding: '40px', textAlign: 'center', color: '#dc2626' }}>
                  <AlertTriangle size={32} style={{ margin: '0 auto 8px' }} />
                  <div style={{ fontSize: '14px' }}>{reportPreviewData.error}</div>
                </div>
              ) : reportPreviewData.format === 'html' ? (
                <iframe
                  srcDoc={reportPreviewData.content}
                  style={{ width: '100%', height: '100%', border: 'none', background: 'white' }}
                  title="report-preview-html"
                />
              ) : (
                <div style={{ padding: '20px 32px', maxWidth: '900px', margin: '0 auto' }}>
                  <MarkdownRenderer>{reportPreviewData.content || '（报告内容为空）'}</MarkdownRenderer>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
