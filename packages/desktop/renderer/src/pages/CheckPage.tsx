import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, Loader2, AlertTriangle, CheckCircle2, XCircle, Download, FileText, Upload, FolderOpen, Copy, ChevronDown, ChevronRight, Eye, BookOpen, AlertCircle, ArrowRight, Trash2, Wrench, MapPin, Undo2 } from 'lucide-react';
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

// --- 检查类型中文名（老版 St 字典，1:1 还原）---
const CHECK_TYPE_LABELS: Record<string, string> = {
  fullCheck: '全面检查', full_check: '全面检查',
  compliance: '合规性检查',
  disqualification: '废标项检查',
  mandatoryReq: '强制性参数对照', mandatory_req: '强制性参数对照', mandatory: '强制性参数对照',
  qualification: '资质核查',
  deposit: '保证金核查',
  signature: '签章核查',
  validity: '有效期核查',
  pricing: '报价核查',
  consistency: '一致性校验',
  duplicate: '标书查重',
  docIntegrity: '文件完整性', doc_integrity: '文件完整性',
  fitScore: '贴合度评分', fit_score: '贴合度评分',
  selfcheck: '废标自查',
  crossCheck: '交叉比对', cross_check: '交叉比对',
  aiTextCheck: 'AI文本检查', ai_text_check: 'AI文本检查',
  riskScore: '风险评分', risk_score: '风险评分',
  sampleReport: '样品/检测报告', sample_report: '样品/检测报告',
  jointBid: '联合投标协议', joint_bid: '联合投标协议',
  ebidSubmit: '电子投标提交', ebid_submit: '电子投标提交',
  pricingLogic: '报价逻辑闭环', pricing_logic: '报价逻辑闭环',
  scoreCoverage: '评分覆盖检查', score_coverage: '评分覆盖检查',
};

// --- 检查结果字段中文名字典（老版 Be 字典，供「检查结果明细」逐字段展示）---
const FIELD_LABELS: Record<string, string> = {
  risk_level: '风险等级', overall_risk: '总体风险', has_critical_issues: '是否存在致命问题',
  total: '总计', passed: '通过', failed: '未通过', warning: '警告数', pass: '通过数', score: '得分',
  detail: '说明', summary: '概要', checks: '检查明细', suggestions: '改进建议', recommendations: '改进建议',
  items: '问题清单', missing: '未响应条数', fully_responded: '已响应条数', total_clauses: '条款总数',
  status: '状态', check_type: '检查项', fit_score: '匹配度', dimensions: '评估维度', risk_score: '风险分',
  message: '说明', reason: '原因', suggestion: '建议', clause_id: '条款编号', clause_type: '条款类型',
  description: '描述', title: '标题', high: '高', medium: '中', low: '低', error: '失败原因',
  clause_content: '招标条款原文', clause_title: '条款标题', response_content: '我方响应内容',
  response_quality: '响应质量', response_found: '是否找到响应', is_responded: '是否响应',
  severity: '严重程度', level: '级别', category: '类别', location: '位置', where: '位置',
  fix: '修改建议', fixes: '修改建议', action: '处理动作', actions: '处理动作', advice: '建议',
  conclusion: '结论', overall: '总体情况', risk: '风险', risks: '风险点', issues: '问题',
  problems: '问题', findings: '发现的问题', total_items: '问题总数', count: '数量', coverage: '覆盖率',
  covered: '已覆盖', uncovered: '未覆盖', matched: '已匹配', position: '位置', page: '页码',
  section: '章节', chapter: '章节', text: '文本', keyword: '关键词', keywords: '关键词',
  rule: '规则', rules: '规则', value: '取值', expected: '应有', actual: '实际情况', limit: '限额',
  amount: '金额', price: '价格', similarity: '相似度', duplicate_rate: '重复率', ratio: '比例',
  percent: '百分比', word_count: '字数', char_count: '字符数', paragraph: '段落', chunk: '片段',
  ai_score: 'AI 特征分', ai_probability: 'AI 生成概率', human_score: '人工特征分',
  deadline: '截止时间', expire_date: '到期日', valid_until: '有效期至', expire: '是否到期',
  expired: '已过期', days_left: '剩余天数', issuer: '出具单位', holder: '持有人',
  cert_name: '证书名称', cert_no: '证书编号', company: '单位名称', bidder: '投标人', tenderer: '招标人',
  project_name: '项目名称', bid_amount: '投标报价', deposit_amount: '保证金金额',
  deposit_form: '保证金形式', paid: '是否已缴纳', seal: '盖章', signature: '签字',
  has_seal: '是否盖章', has_signature: '是否签字', missing_items: '缺失项', extra_items: '多余项',
  required: '招标要求', recommendation: '建议', note: '备注', remarks: '备注', comment: '说明',
  content: '内容', details: '明细', answered: '已响应条数', compliant: '符合条数',
  non_compliant: '不符合条数', coverage_rate: '覆盖率', disqualification_risk: '废标风险',
  ebid_summary: '电子投标摘要', negative_deviation: '负偏离', partial: '部分响应',
  vague_response: '表述含糊', risk_assessment: '风险评估', total_checks: '检查项总数',
  total_mandatory: '强制项总数', total_requirements: '要求总数', mandatory_total: '强制项总数',
  passed_checks: '通过项数', failed_checks: '未通过项数', unresponded: '未响应条数',
  responded: '已响应条数', is_compliant: '是否合规', response: '响应情况', gap: '差距', gaps: '差距项',
};

// --- 枚举值中文名（老版 Mn 字典）---
const VALUE_LABELS: Record<string, string> = {
  pass: '通过', passed: '通过', fail: '不通过', failed: '不通过',
  warning: '警告', warn: '警告', error: '执行失败', high: '高', medium: '中', low: '低',
  critical: '严重', severe: '严重', info: '提示', none: '无', unknown: '未知', pending: '待处理',
  ok: '正常', normal: '正常', partial: '部分响应', partial_response: '部分响应', full: '完整响应',
  complete: '完整', missing: '缺失', matched: '已匹配', unmatched: '未匹配', covered: '已覆盖',
  uncovered: '未覆盖', yes: '是', no: '否', true: '是', false: '否', na: '不适用',
  not_applicable: '不适用', compliant: '符合', non_compliant: '不符合', risky: '有风险', safe: '无风险',
};

const SEVERITY_LABELS: Record<string, string> = {
  high: '高', medium: '中', low: '低', critical: '严重', severe: '严重', error: '错误',
  warning: '警告', warn: '警告', info: '提示', none: '无', pass: '通过', passed: '通过',
  fail: '不通过', failed: '不通过', ok: '正常', unknown: '未知',
};

/** 去掉正文里携带的「（xx检查）」类型后缀，避免报告正文重复啰嗦 */
const stripTypeSuffix = (v: unknown): string =>
  String(v ?? '')
    .replace(/[（(]\s*(fullCheck|full_check|compliance|disqualification|mandatoryReq|mandatory_req|mandatory|qualification|deposit|signature|validity|pricing|consistency|duplicate|docIntegrity|doc_integrity|fitScore|fit_score|selfcheck|crossCheck|cross_check|aiTextCheck|ai_text_check|riskScore|risk_score|sampleReport|sample_report|jointBid|joint_bid|ebidSubmit|ebid_submit|pricingLogic|pricing_logic|scoreCoverage|score_coverage)\s*[)）]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();

/** 检查类型 key → 中文名 */
const checkTypeLabel = (type: unknown): string => {
  const k = String(type ?? '').trim();
  if (!k) return '检查项';
  return CHECK_TYPE_LABELS[k] || CHECK_TYPE_LABELS[k.replace(/_/g, '').toLowerCase()] || stripTypeSuffix(k);
};

/** 结果字段 key → 中文名 */
const fieldLabel = (key: string): string =>
  FIELD_LABELS[key] || CHECK_TYPE_LABELS[key] || CHECK_TYPE_LABELS[String(key).replace(/_/g, '').toLowerCase()] || '';

/** 严重程度/枚举值 → 中文名 */
const severityLabel = (v: unknown): string => {
  const k = String(v ?? '').trim().toLowerCase();
  return SEVERITY_LABELS[k] || String(v ?? '');
};

/** 把模型/网络错误变成客户看得懂的一句话（老版 Ge） */
const friendlyError = (err: unknown): string => {
  let s = typeof err === 'string' ? err : err == null ? '' : (err instanceof Error ? err.message : JSON.stringify(err));
  if (/rpm exhausted|429|quota_exceeded/i.test(s)) return '模型调用额度不足（触发限流），请稍后重试或联系管理员更换 API Key';
  if (/timeout|timed out|超时/i.test(s)) return '模型响应超时，请稍后重试';
  if (/Connection error|connect|无法连接/i.test(s)) return '无法连接模型服务，请检查网络与 API 地址';
  if (/Invalid API key|401|unauthorized/i.test(s)) return 'API Key 无效或已过期，请在平台配置中重新填写';
  s = s.split(/Traceback \(most recent call last\)/)[0];
  s = s.replace(/File "[^"]*", line \d+[^\n]*/g, '');
  s = s.replace(/([A-Za-z]:\\|\/usr\/|\/app\/|\/opt\/)[^\s"']+/g, '');
  s = s.replace(/[A-Za-z_.]*(Error|Exception)[a-zA-Z]*:[^\n]*/g, '');
  s = s.replace(/\s*\n\s*/g, ' ').replace(/\s{2,}/g, ' ').trim();
  return s.slice(0, 300) || '无返回内容';
};

/** 检查结果里的任意值 → 可展示文本 */
const displayValue = (v: unknown): string => {
  if (v === true) return '是';
  if (v === false) return '否';
  if (v == null || v === '') return '—';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'string') {
    const s = stripTypeSuffix(v).trim();
    return VALUE_LABELS[s.toLowerCase()] || friendlyError(s);
  }
  if (Array.isArray(v)) {
    if (!v.length) return '—';
    if (v.every(x => typeof x === 'string')) return v.map(x => '• ' + displayValue(x)).join('\n');
    return `共 ${v.length} 项(展开下方"技术明细"查看)`;
  }
  return '（结构化数据，展开下方"技术明细"查看）';
};

/** 报告的生成时间：按本地时间展示（后端存的是无时区字符串） */
const formatDateTime = (v: unknown, opts: { seconds?: boolean } = {}): string => {
  if (v == null || v === '') return '';
  const raw = String(v).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const iso = hasTz ? raw : `${raw.replace(' ', 'T')}Z`;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  const date = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  const time = `${p(d.getHours())}:${p(d.getMinutes())}${opts.seconds === false ? '' : `:${p(d.getSeconds())}`}`;
  return `${date} ${time}`;
};

// --- 修复方案数据结构 ---
interface FixItem {
  idx?: number;
  check_name?: string;
  problem?: string;
  where?: string;
  why?: string;
  fix_text?: string;
  steps?: string[];
  manual?: string;
  severity?: string;
  orig_text?: string;
  orig_len?: number;
  fix_len?: number;
  needs_manual?: boolean;
  is_summary?: boolean;
}

interface FixPlan {
  generated_at?: string;
  model?: string;
  problem_count?: number;
  summary?: string;
  fixes?: FixItem[];
}

interface LocateInfo {
  old_text?: string;
  title?: string;
  found?: boolean;
  reason?: string;
  score?: number;
}

interface FixLocateData {
  locate?: { found?: boolean; title?: string; score?: number; reason?: string; kind?: string };
  excerpt?: { before?: string; match?: string; after?: string; start?: number; total?: number };
  fix_text?: string;
  check_name?: string;
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
            {severityLabel(severity)}
          </span>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)' }}>{stripTypeSuffix(title)}</span>
        </div>
        {description && (
          <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>{stripTypeSuffix(description)}</div>
        )}
        {suggestion && (
          <div style={{ fontSize: '12px', color: '#1e40af', marginTop: '4px', padding: '4px 8px', background: '#eff6ff', borderRadius: '4px' }}>
            💡 {stripTypeSuffix(suggestion)}
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

  // --- 运行并发控制：点其它检查时切换到新检查，旧检查继续在后台跑完 ---
  const runSeqRef = useRef(0);
  const runningRef = useRef<{ seq: number; label: string } | null>(null);

  // --- 检查报告删除 ---
  const [deletingReportId, setDeletingReportId] = useState<string | null>(null);

  // --- 修复方案（整改方案）---
  const [fixPlanOpen, setFixPlanOpen] = useState<boolean>(false);
  const [fixPlanState, setFixPlanState] = useState<{ reportId: string; loading: boolean; error: string; plan: FixPlan | null }>({
    reportId: '',
    loading: false,
    error: '',
    plan: null,
  });
  const [fixApplied, setFixApplied] = useState<Record<string, { applying: boolean; ok: boolean; msg: string }>>({});
  const [fixTexts, setFixTexts] = useState<Record<string, string>>({});
  const [fixLocateMap, setFixLocateMap] = useState<Record<string, LocateInfo>>({});
  const [fixLocateAllLoading, setFixLocateAllLoading] = useState<boolean>(false);
  const [copiedIdx, setCopiedIdx] = useState<number>(-1);
  const [locateModal, setLocateModal] = useState<{ open: boolean; idx: number; loading: boolean; error: string; data: FixLocateData | null }>({
    open: false,
    idx: -1,
    loading: false,
    error: '',
    data: null,
  });

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

  /** 检查返回体统一入口：success=false 时给出可读提示（老版 Ft） */
  const applyCheckResult = useCallback((payload: Record<string, unknown> | null | undefined) => {
    const data = (payload || {}) as Record<string, unknown>;
    if (data.success === false) {
      setError(String(data.error || '本次检查未取得有效结果，请重新运行该检查'));
    }
    setResults(payload as Record<string, unknown>);
  }, []);

  const handleProjectCheck = async (checkType?: CheckType) => {
    if (!selectedProjectId) return;
    const key: CheckType = checkType || activeCheck;
    const label = checkOptions.find(o => o.key === key)?.label || key;
    const seq = runSeqRef.current + 1;
    runSeqRef.current = seq;
    const isCurrent = () => runSeqRef.current === seq;
    const setProgress = (msg: string) => { if (isCurrent()) setCheckProgress(msg); };
    const prev = runningRef.current;
    runningRef.current = { seq, label };
    const switchedNote = prev && prev.seq !== seq
      ? `（已切换到本次；「${prev.label}」仍在后台运行，完成后会出现在下方报告列表）`
      : '';
    setLoading(true);
    setError('');
    setResults(null);
    setCheckProgress(`${label}：任务已提交，正在检查…${switchedNote}`);
    try {
      if (key === 'fullCheck') {
        const submitRes = await checkApi.fullCheck(selectedProjectId);
        const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
        if (taskId) {
          const result = await checkApi.pollCheckTask(taskId, msg => setProgress(`${label}：${msg}`), 200, 3000, isCurrent);
          if (!isCurrent()) return;
          applyCheckResult(result);
          setCheckProgress('');
          return;
        }
        if (!isCurrent()) return;
        applyCheckResult(submitRes.data);
        return;
      }

      if (key === 'scoreCoverage') {
        const submitRes = await generateApi.scoreCoverage(selectedProjectId);
        const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
        if (taskId) {
          const result = await generateApi.pollTask(taskId, msg => setProgress(`${label}：${msg}`), 200, 3000, isCurrent);
          if (!isCurrent()) return;
          applyCheckResult(result);
          setCheckProgress('');
          return;
        }
        if (!isCurrent()) return;
        applyCheckResult(submitRes.data);
        return;
      }

      // 其余检查：统一提交 + 轮询
      const submitRes = await checkApi.submitCheck(selectedProjectId, key);
      const taskId = (submitRes.data as Record<string, unknown>)?.task_id as string;
      if (taskId) {
        const result = await checkApi.pollCheckTask(taskId, msg => setProgress(`${label}：${msg}`), 200, 3000, isCurrent);
        if (!isCurrent()) return;
        applyCheckResult(result);
        setCheckProgress('');
        return;
      }
      if (!isCurrent()) return;
      applyCheckResult(submitRes.data);
    } catch (e: unknown) {
      if (!isCurrent()) return;
      if (e instanceof Error && e.message === 'TASK_CANCELLED') return;
      setError(friendlyError(e) || '检查失败');
    } finally {
      if (isCurrent()) {
        runningRef.current = null;
        setLoading(false);
        setCheckProgress('');
        if (checkMode === 'project') loadReports();
      }
    }
  };

  const handleUploadCheck = async () => {
    if (!bidFile) {
      setError('请先上传投标文件');
      return;
    }
    const seq = runSeqRef.current + 1;
    runSeqRef.current = seq;
    const isCurrent = () => runSeqRef.current === seq;
    setLoading(true);
    setError('');
    setResults(null);
    setCheckProgress('上传文件检查中…');
    try {
      const res = await checkApi.uploadCheck(bidFile, tenderFile, activeCheck);
      if (!isCurrent()) return;
      applyCheckResult(res.data);
    } catch (e: unknown) {
      if (!isCurrent()) return;
      setError(friendlyError(e) || '检查失败');
    } finally {
      if (isCurrent()) {
        setLoading(false);
        setCheckProgress('');
        if (checkMode === 'project') loadReports();
      }
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

  // --- 检查报告删除 ---
  const handleDeleteReport = async (report: { id: string; type: string; risk_level: string; created_at: string }) => {
    if (!selectedProjectId) return;
    const createdText = report.created_at ? formatDateTime(report.created_at) : '';
    const ok = window.confirm(
      `确定删除这条检查报告？\n\n` +
      `${checkTypeLabel(report.type)} · ${getRiskLabel(report.risk_level)}${createdText ? ` · ${createdText}` : ''}\n\n` +
      `删除后报告及其修复方案、已应用的修复记录都会一并清除，且无法恢复。`,
    );
    if (!ok) return;
    setDeletingReportId(report.id);
    try {
      await checkApi.deleteReport(selectedProjectId, report.id);
      if (reportPreviewData.reportId === report.id) setReportPreviewOpen(false);
      await loadReports();
    } catch (e: unknown) {
      setError(friendlyError(e) || '删除报告失败');
    } finally {
      setDeletingReportId(null);
    }
  };

  // --- 修复方案：整改文本初值 + 一次性定位（黄底/绿底对照）---
  const prepareFixPlan = (plan: FixPlan | null, reportId: string) => {
    const fixes = (plan || {}).fixes || [];
    const texts: Record<string, string> = {};
    fixes.forEach((f, i) => { texts[String(f.idx ?? i)] = String(f.fix_text || ''); });
    setFixTexts(texts);
    setFixLocateMap({});
    if (!selectedProjectId || fixes.length === 0) return;
    setFixLocateAllLoading(true);
    checkApi.fixLocateAll(selectedProjectId, reportId)
      .then(res => {
        const items = ((res.data || {}) as { items?: Array<Record<string, unknown>> }).items || [];
        const map: Record<string, LocateInfo> = {};
        items.forEach(it => {
          map[String(it.idx)] = {
            old_text: String(it.old_text || ''),
            title: String(it.title || ''),
            found: !!it.found,
            reason: String(it.reason || ''),
            score: typeof it.score === 'number' ? it.score : undefined,
          };
        });
        setFixLocateMap(map);
      })
      .catch(() => { /* 定位失败不阻塞方案展示 */ })
      .finally(() => setFixLocateAllLoading(false));
  };

  const loadFixPlan = async (reportId: string) => {
    if (!selectedProjectId) return;
    const seq = runSeqRef.current + 1;
    runSeqRef.current = seq;
    const isCurrent = () => runSeqRef.current === seq;
    setCopiedIdx(-1);
    setFixPlanOpen(true);
    setFixPlanState({ reportId, loading: true, error: '', plan: null });
    try {
      const existing = (await checkApi.getFixPlan(selectedProjectId, reportId)).data as
        { has_plan?: boolean; fix_plan?: FixPlan | null };
      if (existing.has_plan && existing.fix_plan) {
        setFixPlanState({ reportId, loading: false, error: '', plan: existing.fix_plan });
        prepareFixPlan(existing.fix_plan, reportId);
        return;
      }
      const submitted = await checkApi.fixPlan(selectedProjectId, reportId);
      const taskId = String((submitted.data as Record<string, unknown>)?.task_id || '');
      if (!taskId) throw new Error('修复方案任务提交失败');
      await checkApi.pollCheckTask(taskId, msg => { if (isCurrent()) setCheckProgress(`修复方案：${msg}`); }, 200, 3000, isCurrent);
      if (!isCurrent()) return;
      const after = (await checkApi.getFixPlan(selectedProjectId, reportId)).data as
        { fix_plan?: FixPlan | null };
      setFixPlanState({
        reportId,
        loading: false,
        error: after.fix_plan ? '' : '未生成修复方案,请重试',
        plan: after.fix_plan || null,
      });
      if (after.fix_plan) prepareFixPlan(after.fix_plan, reportId);
    } catch (e: unknown) {
      if (!isCurrent()) {
        setFixPlanState(prev => ({ ...prev, loading: false, error: '' }));
        return;
      }
      setFixPlanState(prev => ({ ...prev, loading: false, error: friendlyError(e) || '生成修复方案失败' }));
    }
  };

  // --- 写入标书：整段替换 / 追加到段落末尾 ---
  const handleApplyFix = async (idx: number, mode: 'replace' | 'append' = 'replace') => {
    if (!selectedProjectId || !fixPlanState.reportId) return;
    const key = String(idx);
    const edited = fixTexts[key];
    const modelText = String(
      (fixPlanState.plan?.fixes || []).find(f => String(f.idx ?? '') === key)?.fix_text || '',
    );
    const isEdited = typeof edited === 'string' && edited.trim() !== modelText.trim();
    const oldLen = (fixLocateMap[key]?.old_text || '').length;
    const newLen = typeof edited === 'string' ? edited.length : modelText.length;
    const tooShort = mode === 'replace' && oldLen > 0 && newLen < oldLen * 0.7;
    const what = isEdited ? '你「手动修改后」的整改文本' : '这条整改文本';
    const confirmMsg = mode === 'append'
      ? `确认把${what}追加到该段落末尾？原文不会删除，会以【整改补充】标注。`
      : tooShort
        ? `⚠️ 注意：新文本只有 ${newLen} 字，将被换掉的原文段落有 ${oldLen} 字，整段替换会删掉原文约 ${oldLen - newLen} 字。\n确认仍要整段替换吗？(建议改用「➕ 追加到段落末尾」)`
        : `确认把${what}整段替换到标书对应位置？原段落会自动备份，可在报告修复记录里追溯。`;
    if (!window.confirm(confirmMsg)) return;

    setFixApplied(prev => ({ ...prev, [key]: { applying: true, ok: true, msg: '' } }));
    try {
      const res = (await checkApi.fixApply(
        selectedProjectId,
        fixPlanState.reportId,
        idx,
        typeof edited === 'string' ? edited : undefined,
        mode,
      )).data as { message?: string; target_title?: string; short_warning?: string };
      setFixApplied(prev => ({
        ...prev,
        [key]: {
          applying: false,
          ok: true,
          msg: (res.message || `已写入《${res.target_title || '标书'}》`) + (res.short_warning ? ` ⚠️ ${res.short_warning}` : ''),
        },
      }));
    } catch (e: unknown) {
      setFixApplied(prev => ({ ...prev, [key]: { applying: false, ok: false, msg: friendlyError(e) || '写入失败' } }));
    }
  };

  // --- 打开文本当前位置 ---
  const handleLocateFix = async (idx: number) => {
    if (!selectedProjectId || !fixPlanState.reportId) return;
    setLocateModal({ open: true, idx, loading: true, error: '', data: null });
    try {
      const res = await checkApi.fixLocate(selectedProjectId, fixPlanState.reportId, idx);
      setLocateModal({ open: true, idx, loading: false, error: '', data: res.data as FixLocateData });
    } catch (e: unknown) {
      setLocateModal({ open: true, idx, loading: false, error: friendlyError(e) || '定位失败', data: null });
    }
  };

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

      const label = checkOptions.find(o => o.key === key)?.label || checkTypeLabel(key);

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
                        <div>风险等级: <strong style={{ color: '#0f172a' }}>{displayValue(item.riskLevel)}</strong></div>
                        <div>是否存在严重问题: <strong style={{ color: '#0f172a' }}>{item.hasCritical ? '是' : '否'}</strong></div>
                        {d.summary != null && <div style={{ gridColumn: '1 / -1' }}>摘要: {stripTypeSuffix(String(d.summary))}</div>}
                        {d.overall_assessment != null && <div style={{ gridColumn: '1 / -1' }}>整体评估: {stripTypeSuffix(String(d.overall_assessment))}</div>}
                        {Array.isArray(d.findings) && (d.findings as unknown[]).length > 0 && (
                          <div style={{ gridColumn: '1 / -1', marginTop: '4px' }}>
                            <div style={{ fontWeight: 500, marginBottom: '4px' }}>发现问题 ({String((d.findings as unknown[]).length)}):</div>
                            {(d.findings as Array<Record<string, unknown>>).slice(0, 5).map((f, i) => (
                              <div key={i} style={{ background: '#f8fafc', padding: '6px 8px', borderRadius: '4px', marginBottom: '3px', fontSize: '11px' }}>
                                <div>• {stripTypeSuffix(String(f.title || f.issue || f.description || f.detail || f.reason || f.message || '该项需人工复核'))}</div>
                                {f.severity != null && <div style={{ color: 'var(--color-text-secondary)' }}>严重度: {severityLabel(f.severity)}</div>}
                              </div>
                            ))}
                            {(d.findings as unknown[]).length > 5 && <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>...还有 {String((d.findings as unknown[]).length - 5)} 项</div>}
                          </div>
                        )}
                        {d.suggestion != null && <div style={{ gridColumn: '1 / -1' }}>建议: {stripTypeSuffix(String(d.suggestion))}</div>}
                        {d.raw_text != null && <details style={{ gridColumn: '1 / -1', marginTop: '6px' }}><summary style={{ cursor: 'pointer', fontSize: '11px', color: '#64748b' }}>查看技术明细（原始数据，一般无需查看）</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px', background: '#f1f5f9', padding: '8px', borderRadius: '4px', marginTop: '4px' }}>{String(d.raw_text).slice(0, 2000)}</pre></details>}
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
                  {severityLabel(severity)}
                </span>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)' }}>{stripTypeSuffix(title)}</span>
              </div>
              {description && (
                <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>{stripTypeSuffix(description)}</div>
              )}
              {suggestion && (
                <div style={{ fontSize: '12px', color: '#1e40af', marginTop: '4px', padding: '4px 8px', background: '#eff6ff', borderRadius: '4px' }}>
                  💡 {stripTypeSuffix(suggestion)}
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
              <div style={{ fontSize: '12px', fontWeight: 500, color: 'var(--color-text)' }}>{stripTypeSuffix(name)}</div>
              {detail && <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>{stripTypeSuffix(detail)}</div>}
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
            <span style={{ fontSize: '12px', color: '#1e40af' }}>{stripTypeSuffix(text)}</span>
          </div>
        );
      })}
    </div>
  );

  /** 无结构化 findings/checks 时：把结果对象按「字段中文名：值」逐项铺开（老版 Vr） */
  const renderDetailGrid = (data: Record<string, unknown>) => {
    const entries = Object.entries(data)
      .filter(([k]) => k !== 'raw_text' && !/^(success|type)$/.test(k))
      .map(([k, v]) => [fieldLabel(k), v] as [string, unknown])
      .filter(([label]) => !!label);
    if (entries.length === 0) {
      return (
        <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
          本次检查未返回可展示的明细，可展开下方"技术明细"查看原始数据。
        </div>
      );
    }
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '6px 18px', fontSize: '12px' }}>
        {entries.map(([label, value], idx) => {
          const text = displayValue(value);
          return (
            <div
              key={`${label}-${idx}`}
              style={{ whiteSpace: 'pre-wrap', gridColumn: typeof text === 'string' && text.includes('\n') ? '1 / -1' : 'auto' }}
            >
              <span style={{ color: 'var(--color-text-secondary)' }}>{label}：</span>
              <span>{text}</span>
            </div>
          );
        })}
      </div>
    );
  };

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
          <div>
            <div style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '8px', padding: '14px 16px' }}>
              <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '10px' }}>检查结果明细</div>
              {renderDetailGrid(data)}
            </div>
            <details style={{ marginTop: '10px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '11px', color: '#64748b' }}>查看技术明细（原始数据，一般无需查看）</summary>
              <button
                onClick={async () => {
                  try { await navigator.clipboard.writeText(JSON.stringify(data, null, 2)); } catch { /* fallback */ }
                }}
                style={{ marginTop: '6px', padding: '4px 8px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', color: '#64748b' }}
              >
                <Copy size={12} /> 复制原始数据
              </button>
              <pre style={{ background: '#f8fafc', padding: '12px', borderRadius: '8px', fontSize: '11px', overflow: 'auto', maxHeight: '280px' }}>
                {JSON.stringify(data, null, 2)}
              </pre>
            </details>
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
            onClick={() => { if (!disabled) { setActiveCheck(opt.key); handleProjectCheck(opt.key); } }}
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
    <>
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
          marginBottom: loading ? '6px' : '20px',
        }}
      >
        {loading ? (checkProgress || '检查中...') : `运行${checkOptions.find(o => o.key === activeCheck)?.label || '检查'}`}
      </button>
      {loading && (
        <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginBottom: '16px', lineHeight: 1.6 }}>
          {activeCheck === 'fullCheck'
            ? '全面检查会并行执行 18 项技能，通常 2–4 分钟，请勿关闭页面。'
            : '单项检查通常 1–2 分钟。期间点其它检查会切换到新检查，旧检查仍在后台完成并出现在报告列表。'}
        </div>
      )}
    </>
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
          {(() => {
            const inner = (results as Record<string, unknown>)?.data;
            const values = inner && typeof inner === 'object' ? Object.values(inner as Record<string, unknown>) : [];
            const isFullCheckResult = values.length > 1
              && values.every(v => !!v && typeof v === 'object' && 'success' in (v as Record<string, unknown>));
            return isFullCheckResult
              ? renderFullCheckSummary(inner as Record<string, unknown>)
              : renderSingleCheckResult(inner as Record<string, unknown>);
          })()}
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
              <div key={report.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', padding: '12px', border: '1px solid var(--color-border)', borderRadius: '8px', flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0 }}>
                  <span style={{ fontSize: '13px', fontWeight: 500 }}>{checkTypeLabel(report.type)}</span>
                  <span style={{ fontSize: '12px', color: getRiskColor(report.risk_level), marginLeft: '8px' }}>
                    {getRiskLabel(report.risk_level)}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginLeft: '8px' }}>
                    {report.created_at ? formatDateTime(report.created_at) : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <button onClick={() => handlePreviewReport(report, 'markdown')} style={{ padding: '4px 10px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Eye size={10} /> 预览
                  </button>
                  <button onClick={() => handleExportReport(report.id, 'markdown')} style={{ padding: '4px 10px', background: '#059669', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Download size={10} /> Markdown
                  </button>
                  <button onClick={() => handleExportReport(report.id, 'html')} style={{ padding: '4px 10px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Download size={10} /> HTML
                  </button>
                  <button
                    onClick={() => handleDeleteReport(report)}
                    disabled={deletingReportId === report.id}
                    title="删除这条检查报告"
                    style={{
                      padding: '4px 10px',
                      background: deletingReportId === report.id ? '#fca5a5' : '#fef2f2',
                      color: '#dc2626',
                      border: '1px solid #fecaca',
                      borderRadius: '4px',
                      cursor: deletingReportId === report.id ? 'wait' : 'pointer',
                      fontSize: '11px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      marginLeft: '4px',
                    }}
                  >
                    {deletingReportId === report.id ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                    {deletingReportId === report.id ? '删除中' : '删除'}
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
                  {checkTypeLabel(reportPreviewData.reportType)} 检查报告
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
                  onClick={() => { loadFixPlan(reportPreviewData.reportId); }}
                  disabled={!reportPreviewData.reportId}
                  style={{ padding: '6px 12px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <Wrench size={12} /> 一键生成修复方案
                </button>
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

      {fixPlanOpen && (
        <div
          onMouseDown={(e) => { if (e.target === e.currentTarget) setFixPlanOpen(false); }}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'white', borderRadius: '12px', width: '92%', maxWidth: '1000px',
              height: '88vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}
          >
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid var(--color-border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <h2 style={{ fontSize: '16px', fontWeight: 600, margin: 0 }}>🔧 问题修复方案</h2>
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0' }}>
                  {fixPlanState.plan
                    ? `${fixPlanState.plan.problem_count ?? 0} 个问题 · 模型 ${fixPlanState.plan.model || '-'} · 生成于 ${formatDateTime(fixPlanState.plan.generated_at)}`
                    : '按检查结果逐条给出可直接落地的整改方案'}
                </p>
              </div>
              <button
                onClick={() => setFixPlanOpen(false)}
                style={{ padding: '6px 12px', background: '#f1f5f9', color: 'var(--color-text)', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
              >
                关闭
              </button>
            </div>

            <div style={{ flex: 1, overflow: 'auto', background: '#f8fafc', padding: '16px 20px' }}>
              {fixPlanState.loading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '8px' }}>
                  <Loader2 size={32} className="animate-spin" color="var(--color-primary)" />
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: '13px' }}>
                    正在针对问题项逐条生成修复方案…（约 30-90 秒）
                  </span>
                </div>
              ) : fixPlanState.error ? (
                <div style={{ padding: '40px', textAlign: 'center', color: '#dc2626', fontSize: '14px' }}>
                  {fixPlanState.error}
                </div>
              ) : !fixPlanState.plan || (fixPlanState.plan.fixes || []).length === 0 ? (
                <div style={{ padding: '40px', textAlign: 'center', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
                  {fixPlanState.plan?.summary || '本次检查未发现需要修复的问题项。'}
                </div>
              ) : (
                <>
                  <div style={{
                    display: 'flex', gap: '14px', flexWrap: 'wrap', background: 'white',
                    border: '1px solid var(--color-border)', borderRadius: '8px',
                    padding: '8px 12px', marginBottom: '12px', fontSize: '12px', color: '#475569',
                  }}>
                    <span>
                      <span className="bmp-fix-old" style={{ borderRadius: '4px', padding: '1px 6px', background: '#fef9c3', border: '1px solid #fde047', color: '#713f12' }}>🟡 黄底</span>
                      {' '}＝ 将被替换掉的原文
                    </span>
                    <span>
                      <span className="bmp-fix-new" style={{ borderRadius: '4px', padding: '1px 6px', background: '#dcfce7', border: '1px solid #86efac', color: '#14532d' }}>🟢 绿底</span>
                      {' '}＝ 替换后写入标书的新内容（可直接编辑）
                    </span>
                  </div>

                  {String(fixPlanState.plan.summary || '') ? (
                    <div style={{
                      background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '8px',
                      padding: '12px 14px', marginBottom: '14px', fontSize: '13px', color: '#1e3a8a', lineHeight: 1.7,
                    }}>
                      <b>整体整改思路：</b>{String(fixPlanState.plan.summary)}
                    </div>
                  ) : null}

                  {(fixPlanState.plan.fixes || []).map((fix, fi) => {
                    const sev = String(fix.severity || '');
                    const must = sev.includes('fail') || sev.includes('high');
                    const key = String(fix.idx ?? fi);
                    const modelText = String(fix.fix_text || '');
                    const current = fixTexts[key] ?? modelText;
                    const edited = current.trim() !== modelText.trim();
                    const loc = fixLocateMap[key];
                    const oldLen = (loc?.old_text || String(fix.orig_text || '')).length;
                    const newLen = current.length;
                    const tooShort = oldLen > 0 && newLen < oldLen * 0.7;
                    const pct = oldLen > 0 ? Math.round((newLen / oldLen - 1) * 100) : 0;
                    const isSummary = !!fix.is_summary;
                    const applied = fixApplied[key];
                    return (
                      <div key={fi} style={{ background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px', padding: '14px 16px', marginBottom: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                          <div style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a' }}>
                            {fi + 1}. {stripTypeSuffix(String(fix.check_name || '检查项')) || '检查项'}
                          </div>
                          <span style={{
                            fontSize: '11px', padding: '2px 8px', borderRadius: '10px', whiteSpace: 'nowrap',
                            background: must ? '#fee2e2' : '#fef3c7', color: must ? '#b91c1c' : '#92400e',
                          }}>
                            {must ? '必须修复' : '建议修复'}
                          </span>
                        </div>

                        <div style={{ fontSize: '13px', color: '#334155', marginTop: '8px', lineHeight: 1.8 }}>
                          {String(fix.problem || '') ? <div><b>问题：</b>{String(fix.problem)}</div> : null}
                          {String(fix.where || '') ? <div><b>位置：</b>{String(fix.where)}</div> : null}
                          {String(fix.why || '') ? <div><b>为什么不合规：</b>{String(fix.why)}</div> : null}
                        </div>

                        <div style={{ marginTop: '10px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <b style={{ fontSize: '13px' }}>整改文本（可手动修改）</b>
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                              <button
                                onClick={() => { navigator.clipboard.writeText(current); setCopiedIdx(fi); }}
                                style={{
                                  padding: '3px 10px', fontSize: '12px',
                                  background: copiedIdx === fi ? '#dcfce7' : 'white',
                                  color: copiedIdx === fi ? '#15803d' : 'var(--color-primary)',
                                  border: '1px solid var(--color-primary)', borderRadius: '6px', cursor: 'pointer',
                                }}
                              >
                                {copiedIdx === fi ? '已复制' : '复制文本'}
                              </button>
                              {isSummary ? (
                                <span style={{
                                  fontSize: '12px', color: '#92400e', background: '#fffbeb',
                                  border: '1px solid #fcd34d', borderRadius: '6px', padding: '3px 10px',
                                }}>
                                  「汇总行」不对应某一个段落，无法自动替换：请复制文本后到各对应章节分别修改
                                </span>
                              ) : (
                                <>
                                  <button
                                    onClick={() => { handleApplyFix(Number(fix.idx ?? fi), 'replace'); }}
                                    disabled={!!applied?.applying}
                                    style={{
                                      padding: '3px 10px', fontSize: '12px',
                                      background: tooShort ? '#fff7ed' : edited ? '#f0fdf4' : '#eff6ff',
                                      color: tooShort ? '#c2410c' : edited ? '#15803d' : '#1d4ed8',
                                      border: `1px solid ${tooShort ? '#fdba74' : edited ? '#86efac' : '#93c5fd'}`,
                                      borderRadius: '6px', cursor: 'pointer', opacity: applied?.applying ? 0.6 : 1,
                                    }}
                                  >
                                    {applied?.applying ? '写入中…' : tooShort ? '⚠️ 仍要整段替换' : edited ? '🔁 整段替换（用修改后的文本）' : '🔁 整段替换'}
                                  </button>
                                  <button
                                    onClick={() => { handleApplyFix(Number(fix.idx ?? fi), 'append'); }}
                                    disabled={!!applied?.applying}
                                    style={{
                                      padding: '3px 10px', fontSize: '12px',
                                      background: tooShort ? '#f0fdf4' : 'white', color: '#15803d',
                                      border: `1px solid ${tooShort ? '#86efac' : '#bbf7d0'}`,
                                      borderRadius: '6px', cursor: 'pointer',
                                      opacity: applied?.applying ? 0.6 : 1, fontWeight: tooShort ? 600 : 400,
                                    }}
                                  >
                                    {tooShort ? '➕ 追加到段落末尾（推荐）' : '➕ 追加到段落末尾'}
                                  </button>
                                </>
                              )}
                              {isSummary ? null : (
                                <button
                                  onClick={() => { handleLocateFix(Number(fix.idx ?? fi)); }}
                                  style={{ padding: '3px 10px', fontSize: '12px', background: 'white', color: '#0f766e', border: '1px solid #5eead4', borderRadius: '6px', cursor: 'pointer' }}
                                >
                                  📍 打开文本当前位置
                                </button>
                              )}
                              {edited ? (
                                <button
                                  onClick={() => setFixTexts(prev => ({ ...prev, [key]: modelText }))}
                                  style={{ padding: '3px 10px', fontSize: '12px', background: 'white', color: '#b45309', border: '1px solid #fcd34d', borderRadius: '6px', cursor: 'pointer' }}
                                >
                                  ↩︎ 恢复模型原文
                                </button>
                              ) : null}
                            </div>
                          </div>

                          {applied?.msg ? (
                            <div style={{
                              marginTop: '8px', fontSize: '12px', lineHeight: 1.7,
                              color: applied.ok ? '#15803d' : '#b91c1c',
                              background: applied.ok ? '#f0fdf4' : '#fef2f2',
                              border: `1px solid ${applied.ok ? '#bbf7d0' : '#fecaca'}`,
                              borderRadius: '6px', padding: '6px 10px',
                            }}>
                              {applied.msg}
                            </div>
                          ) : null}

                          {tooShort ? (
                            <div style={{
                              marginTop: '8px', fontSize: '12px', lineHeight: 1.8, color: '#92400e',
                              background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: '6px', padding: '8px 10px',
                            }}>
                              ⚠️ <b>这条新文本比原文短 {Math.abs(pct)}%</b>（原文 {oldLen} 字 → 新文 {newLen} 字）。
                              它更像「补充说明」而不是完整段落，<b>整段替换会删掉原文约 {oldLen - newLen} 字</b>。
                              建议点「➕ 追加到段落末尾（推荐）」只做补充；若确实要替换，请先在新文本里把原文的关键信息（名称、金额、日期、承诺、清单项）补全。
                            </div>
                          ) : null}

                          <div style={{ marginTop: '10px' }}>
                            <div style={{ fontSize: '12px', color: '#92400e', marginBottom: '4px' }}>
                              <b>🟡 被替换的原文</b>
                              {loc?.title ? ` · 位置：《${loc.title}》` : ''}
                              {loc && loc.found === false ? ' · 未精确定位到段落，替换时会追加到该正文末尾' : ''}
                            </div>
                            <div className="bmp-fix-old" style={{ borderRadius: '6px', padding: '8px 10px', fontSize: '12.5px', lineHeight: 1.8, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#fef9c3', border: '1px solid #fde047', color: '#713f12' }}>
                              {loc?.old_text
                                ? stripTypeSuffix(loc.old_text)
                                : fixLocateAllLoading
                                  ? '正在读取原文位置…'
                                  : loc?.reason || '（未在正文中找到完全对应的原段落，替换时会作为【整改补充】追加到该正文末尾）'}
                            </div>
                          </div>

                          <div style={{ marginTop: '10px' }}>
                            <div style={{ fontSize: '12px', color: '#15803d', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                              <span><b>🟢 替换后的新内容</b>（可直接修改，点「一键替换」写入的就是这里的内容）</span>
                              <span style={{ color: edited ? '#b45309' : 'var(--color-text-secondary)' }}>
                                {oldLen > 0
                                  ? `原文 ${oldLen} 字 → 新文 ${newLen} 字（${pct >= 0 ? '+' : ''}${pct}%）`
                                  : `${newLen} 字`}
                                {edited ? ' · 已手动修改' : ' · 模型原文'}
                              </span>
                            </div>
                            <textarea
                              value={current}
                              onChange={(e) => setFixTexts(prev => ({ ...prev, [key]: e.target.value }))}
                              spellCheck={false}
                              placeholder={modelText ? '' : '模型这一条没能给出完整整改文本：请按上面的问题说明，在这里写好可直接替换的完整段落，再点「整段替换」或「追加到段落末尾」。'}
                              className="bmp-fix-new"
                              style={{ width: '100%', minHeight: '110px', borderRadius: '6px', padding: '10px 12px', fontSize: '12.5px', lineHeight: 1.8, fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box', background: '#dcfce7', border: '1px solid #86efac', color: '#14532d' }}
                            />
                          </div>
                        </div>

                        {Array.isArray(fix.steps) && fix.steps.length > 0 ? (
                          <div style={{ marginTop: '10px', fontSize: '13px', color: '#334155' }}>
                            <b>操作步骤：</b>
                            <ol style={{ margin: '6px 0 0 18px', padding: 0, lineHeight: 1.9 }}>
                              {fix.steps.map((s, si) => <li key={si}>{String(s)}</li>)}
                            </ol>
                          </div>
                        ) : null}
                        {String(fix.manual || '') ? (
                          <div style={{ marginTop: '10px', fontSize: '13px', color: '#475569', background: '#f1f5f9', borderRadius: '6px', padding: '8px 10px', lineHeight: 1.7 }}>
                            <b>手动修复路径：</b>{String(fix.manual)}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {locateModal.open && (
        <div
          onMouseDown={(e) => { if (e.target === e.currentTarget) setLocateModal(prev => ({ ...prev, open: false })); }}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', zIndex: 10001,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'white', borderRadius: '12px', width: '92%', maxWidth: '960px',
              height: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
            }}
          >
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid var(--color-border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <h2 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>📍 文本当前位置</h2>
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', margin: '2px 0 0' }}>
                  {locateModal.data?.locate?.title ? `《${locateModal.data.locate.title}》` : '标书正文'}
                  {locateModal.data?.locate?.found === false ? ' · 未精确定位到段落，替换时会追加到正文末尾' : ''}
                </p>
              </div>
              <button
                onClick={() => setLocateModal(prev => ({ ...prev, open: false }))}
                style={{ padding: '6px 12px', background: '#f1f5f9', color: 'var(--color-text)', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
              >
                关闭
              </button>
            </div>

            <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px', background: '#f8fafc' }}>
              {locateModal.loading ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '8px' }}>
                  <Loader2 size={26} className="animate-spin" color="var(--color-primary)" />
                  <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)' }}>正在定位…</span>
                </div>
              ) : locateModal.error ? (
                <div style={{ padding: '30px', textAlign: 'center', color: '#dc2626', fontSize: '13px' }}>
                  {locateModal.error}
                </div>
              ) : (
                <>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '8px' }}>
                    命中位置：第 {(locateModal.data?.excerpt?.start ?? 0) + 1} / {locateModal.data?.excerpt?.total ?? 0} 字
                    {typeof locateModal.data?.locate?.score === 'number' ? ` · 相似度 ${locateModal.data?.locate?.score}` : ''}
                    {locateModal.data?.locate?.reason ? ` · ${locateModal.data.locate.reason}` : ''}
                  </div>

                  <div style={{ fontSize: '12px', marginBottom: '6px', color: '#92400e' }}>
                    <b>🟡 被替换的原文</b>（黄底即为将被替换掉的内容）
                  </div>
                  <pre style={{
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '13px', lineHeight: 1.9,
                    background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px',
                    padding: '14px 16px', fontFamily: 'inherit', color: '#0f172a',
                  }}>
                    {stripTypeSuffix(locateModal.data?.excerpt?.before || '')}
                    <mark style={{ background: '#fde68a', padding: '1px 2px' }}>
                      {stripTypeSuffix(locateModal.data?.excerpt?.match || '') || '（未精确定位到段落）'}
                    </mark>
                    {stripTypeSuffix(locateModal.data?.excerpt?.after || '')}
                  </pre>

                  {(() => {
                    const key = String(locateModal.idx);
                    const current = fixTexts[key] ?? String(locateModal.data?.fix_text || '');
                    return (
                      <div style={{ marginTop: '12px' }}>
                        <div style={{ fontSize: '12px', marginBottom: '6px', color: '#15803d', display: 'flex', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                          <span><b>🟢 替换后的新内容</b>（一键替换后将写入上面高亮位置，可直接修改）</span>
                          <span style={{ color: 'var(--color-text-secondary)' }}>{current.length} 字</span>
                        </div>
                        <textarea
                          value={current}
                          onChange={(e) => setFixTexts(prev => ({ ...prev, [key]: e.target.value }))}
                          spellCheck={false}
                          className="bmp-fix-new"
                          style={{ width: '100%', minHeight: '130px', borderRadius: '8px', padding: '12px 14px', fontSize: '12.5px', lineHeight: 1.8, fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box', background: '#dcfce7', border: '1px solid #86efac', color: '#14532d' }}
                        />
                      </div>
                    );
                  })()}
                </>
              )}
            </div>

            <div style={{
              padding: '12px 20px', borderTop: '1px solid var(--color-border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap',
            }}>
              <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                黄底部分会被「整段替换」删掉；只想补充内容请用「追加到段落末尾」。
              </span>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => { handleApplyFix(locateModal.idx, 'append'); }}
                  disabled={locateModal.idx < 0}
                  style={{ padding: '6px 14px', background: '#f0fdf4', color: '#15803d', border: '1px solid #86efac', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  ➕ 追加到段落末尾（不删原文）
                </button>
                <button
                  onClick={() => { handleApplyFix(locateModal.idx, 'replace'); }}
                  disabled={locateModal.idx < 0}
                  style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px' }}
                >
                  🔁 整段替换到该位置
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
