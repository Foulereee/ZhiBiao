import { useState, useEffect, useCallback } from 'react';
import { Upload, FileSearch, FileText, ChevronLeft, Loader2, CheckCircle2, AlertCircle, BarChart3, Shield, BookOpen, Eye, X, File, Copy } from 'lucide-react';
import { interpretApi, projectApi, type Project } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';

type Step = 'upload' | 'parse' | 'interpret' | 'done';

interface DocInfo {
  id: string;
  file_name: string;
  file_size: number;
  type: string;
  parsed: boolean;
  created_at: string;
}

interface ParseResult {
  project_id: string;
  text_length: number;
  tables_count: number;
  sections_count: number;
  sections: Array<{ title: string; level: number }>;
  doc_metadata: Record<string, unknown>;
}

interface InterpretResult {
  success: boolean;
  data?: Record<string, unknown>;
  error?: string;
  warnings?: string[];
}

const STEP_CONFIG: Array<{ key: Step; label: string; icon: typeof Upload }> = [
  { key: 'upload', label: '上传文件', icon: Upload },
  { key: 'parse', label: '解析文件', icon: FileText },
  { key: 'interpret', label: 'AI解读', icon: FileSearch },
  { key: 'done', label: '完成', icon: CheckCircle2 },
];

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

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
      <pre style={{ background: '#f8fafc', padding: '16px', borderRadius: '8px', fontSize: '12px', overflow: 'auto', maxHeight: maxheight, border: '1px solid var(--color-border)', paddingRight: '60px' }}>
        {jsonStr}
      </pre>
    </div>
  );
}

const FIELD_LABELS: Record<string, string> = {
  project_name: '项目名称', project_code: '项目编号', procurement_method: '采购方式',
  budget_amount: '预算金额', procurement_unit: '采购人', project_overview: '项目概况',
  unit_name: '单位名称', address: '地址', contact_person: '联系人', contact_phone: '联系电话',
  supervisor_dept: '主管部门',
  qualification_level: '资质等级', registered_capital: '注册资金', performance_requirement: '业绩要求',
  personnel_requirement: '人员要求', equipment_requirement: '设备要求', other_requirements: '其他要求',
  technical_parameters: '技术参数', technical_standards: '技术标准', service_requirements: '服务要求',
  acceptance_criteria: '验收标准', mandatory_params: '强制性参数',
  evaluation_method: '评标方法', business_weight: '商务分权重', technical_weight: '技术分权重',
  price_weight: '价格分权重', scoring_items: '评分细则',
  substantive_requirements: '实质性要求', mandatory_conditions: '强制性条件', disqualification_clauses: '废标条款',
  amount: '金额', payment_method: '缴纳形式', deadline: '截止时间', refund_conditions: '退还条件',
  opening_time: '开标时间', opening_location: '开标地点', sealing_requirements: '密封要求',
  submission_method: '递交方式', submission_deadline: '投标截止时间',
  method: '评标方法', committee_composition: '委员会组成', evaluation_process: '评标流程',
  qualification_score: '资质评分', performance_score: '业绩评分', financial_score: '财务评分',
  reputation_score: '信誉评分', other_items: '其他评分项',
  payment_terms: '付款方式', breach_liability: '违约责任', warranty_period: '质保期',
  acceptance_standard: '验收标准', dispute_resolution: '争议解决',
  exclusivity_clauses: '排他性条款', biased_scoring: '倾向性评分',
  unreasonable_requirements: '不合理要求', potential_risks: '潜在风险',
  potential_competitors: '潜在竞争对手', market_pattern: '市场格局', competitive_advantages: '竞争优势',
  announcement_date: '公告日期', clarification_deadline: '答疑截止', bid_deadline: '投标截止',
  opening_date: '开标日期', contract_signing_date: '合同签订',
  buyer_contact_person: '采购人联系人', buyer_contact_info: '采购人联系方式',
  agency_contact_person: '代理机构联系人', agency_contact_info: '代理机构联系方式',
  technical_contact_person: '技术联系人', technical_contact_info: '技术联系方式',
  name: '名称', description: '描述', score: '分数', type: '类型', clause: '条款号',
  clause_number: '条款号',
  '项目名称': '项目名称', '项目编号': '项目编号', '采购方式': '采购方式',
  '预算金额': '预算金额', '采购人': '采购人', '项目概况': '项目概况',
  '采购人人人人信息': '采购人信息', '编号': '编号',
  procurementUnitName: '单位名称', procurementUnitAddress: '地址',
  contactPerson: '联系人', contactInformation: '联系电话', principalDepartment: '主管部门',
  bidBondAmount: '金额', bidBondPaymentForm: '缴纳形式', bidBondDeadline: '截止时间',
  bidBondRefundConditions: '退还条件',
  bidOpeningTime: '开标时间', bidOpeningLocation: '开标地点',
  sealingRequirements: '密封要求', submissionMethod: '递交方式',
  CA_certificate: 'CA证书',
  '资质等级': '资质等级', '注册资金': '注册资金', '业绩要求': '业绩要求',
  '人员要求': '人员要求', '设备要求': '设备要求',
  '评标方法': '评标方法', '评标委员会组成': '委员会组成', '评标流程': '评标流程',
  '企业资质分': '资质评分', '业绩分': '业绩评分', '财务状况分': '财务评分', '信誉分': '信誉评分',
  '付款方式': '付款方式', '违约责任': '违约责任', '质保期': '质保期',
  '争议解决方式': '争议解决',
  '排他性条款': '排他性条款', '倾向性评分': '倾向性评分', '不合理要求': '不合理要求',
  '潜在竞争对手': '潜在竞争对手', '市场格局': '市场格局', '竞争优势': '竞争优势',
  '公告日期': '公告日期', '合同签订日期': '合同签订',
  non_compliance_will_be_disqualified: '废标条款',
  evaluation细则: '评分细则', market_market_pattern: '市场格局',
  answer疑问截止_date: '答疑截止',
  procuring_entity_contact_person: '采购人联系人',
  procuring_entity_contact_info: '采购人联系方式',
};

export default function InterpretPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [currentStep, setCurrentStep] = useState<Step>('upload');
  const [maxReachedStep, setMaxReachedStep] = useState<Step>('upload');
  const [loading, setLoading] = useState(false);
  const [documents, setDocuments] = useState<DocInfo[]>([]);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [interpretResult, setInterpretResult] = useState<InterpretResult | null>(null);
  const [error, setError] = useState<string>('');
  const [dragOver, setDragOver] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<{ name: string; content: string; metadata: Record<string, unknown> } | null>(null);
  const [restoring, setRestoring] = useState(false);

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
      restoreProjectState(selectedProjectId);
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

  const restoreProjectState = useCallback(async (projectId: string) => {
    setRestoring(true);
    try {
      const res = await interpretApi.getAnalysis(projectId);
      const data = res.data;

      if (data.has_documents) {
        const docRes = await interpretApi.listDocuments(projectId);
        setDocuments(docRes.data.documents || []);
      } else {
        setDocuments([]);
      }

      if (data.has_analysis && data.analysis?.dimensions) {
        setInterpretResult({
          success: true,
          data: { dimensions: data.analysis.dimensions },
        });
        if (data.parse_info) {
          setParseResult({
            project_id: projectId,
            text_length: data.parse_info.text_length || 0,
            tables_count: 0,
            sections_count: 0,
            sections: [],
            doc_metadata: data.parse_info.doc_metadata || {},
          });
        }
        resetToStep('done');
      } else if (data.has_parsed) {
        if (data.parse_info) {
          setParseResult({
            project_id: projectId,
            text_length: data.parse_info.text_length || 0,
            tables_count: 0,
            sections_count: 0,
            sections: [],
            doc_metadata: data.parse_info.doc_metadata || {},
          });
        }
        resetToStep('interpret');
      } else if (data.has_documents) {
        resetToStep('parse');
      } else {
        resetToStep('upload');
        setParseResult(null);
        setInterpretResult(null);
      }
    } catch {
      resetToStep('upload');
      setParseResult(null);
      setInterpretResult(null);
    } finally {
      setRestoring(false);
    }
  }, []);

  const handleUpload = async () => {
    if (files.length === 0 || !selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      await interpretApi.upload(selectedProjectId, files);
      setFiles([]);
      await loadDocuments();
      advanceToStep('parse');
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '上传失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleParse = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await interpretApi.parse(selectedProjectId);
      setParseResult(res.data as ParseResult);
      await loadDocuments();
      advanceToStep('interpret');
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '解析失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleInterpret = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const res = await interpretApi.interpret(selectedProjectId);
      setInterpretResult(res.data as InterpretResult);
      advanceToStep('done');
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '解读失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const advanceToStep = (step: Step) => {
    const stepOrder: Step[] = ['upload', 'parse', 'interpret', 'done'];
    const newIdx = stepOrder.indexOf(step);
    const maxIdx = stepOrder.indexOf(maxReachedStep);
    setCurrentStep(step);
    if (newIdx > maxIdx) {
      setMaxReachedStep(step);
    }
  };

  const resetToStep = (step: Step) => {
    setCurrentStep(step);
    setMaxReachedStep(step);
  };

  const goToStep = (step: Step) => {
    const stepOrder: Step[] = ['upload', 'parse', 'interpret', 'done'];
    const maxIdx = stepOrder.indexOf(maxReachedStep);
    const targetIdx = stepOrder.indexOf(step);
    if (targetIdx <= maxIdx) {
      setCurrentStep(step);
      setError('');
    }
  };

  const loadDocuments = async () => {
    try {
      const res = await interpretApi.listDocuments(selectedProjectId);
      setDocuments(res.data.documents || []);
    } catch { /* ignore */ }
  };

  const handlePreviewDoc = async (docId: string, docName: string) => {
    try {
      const res = await interpretApi.getDocument(docId);
      const data = res.data;
      setPreviewDoc({
        name: docName,
        content: data.parsed_content || '（文件尚未解析，请先执行解析步骤）',
        metadata: data.doc_metadata || {},
      });
    } catch {
      setPreviewDoc({ name: docName, content: '加载失败', metadata: {} });
    }
  };

  const stepIndex = STEP_CONFIG.findIndex(s => s.key === currentStep);
  const maxStepIdx = STEP_CONFIG.findIndex(s => s.key === maxReachedStep);

  const DIMENSION_META: Record<string, { label: string; icon: typeof BarChart3; color: string }> = {
    project_info: { label: '项目信息', icon: BookOpen, color: '#3b82f6' },
    buyer_info: { label: '甲方信息', icon: BookOpen, color: '#6366f1' },
    qualification: { label: '资格要求', icon: Shield, color: '#f59e0b' },
    technical: { label: '技术需求', icon: FileText, color: '#10b981' },
    scoring: { label: '评分细则', icon: BarChart3, color: '#ef4444' },
    disqualification: { label: '废标红线', icon: AlertCircle, color: '#dc2626' },
    deposit: { label: '保证金', icon: BookOpen, color: '#8b5cf6' },
    opening: { label: '开标要求', icon: BookOpen, color: '#0ea5e9' },
    evaluation: { label: '评标办法', icon: BarChart3, color: '#14b8a6' },
    commercial: { label: '商务评分', icon: BarChart3, color: '#f97316' },
    contract: { label: '合同条款', icon: BookOpen, color: '#64748b' },
    risk: { label: '风险提示', icon: AlertCircle, color: '#dc2626' },
    competition: { label: '竞争态势', icon: BarChart3, color: '#8b5cf6' },
    timeline: { label: '时间节点', icon: BookOpen, color: '#059669' },
    contacts: { label: '关键联系人', icon: BookOpen, color: '#0284c7' },
  };

  const renderValue = (value: unknown): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>未提及</span>;
    }
    if (typeof value === 'string') {
      return <span>{value}</span>;
    }
    if (typeof value === 'number') {
      return <span>{value}</span>;
    }
    if (typeof value === 'boolean') {
      return <span>{value ? '是' : '否'}</span>;
    }
    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>无</span>;
      }
      if (typeof value[0] === 'string') {
        return (
          <ul style={{ margin: 0, paddingLeft: '16px', lineHeight: 1.8 }}>
            {value.map((item, i) => <li key={i}>{String(item)}</li>)}
          </ul>
        );
      }
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {value.map((item, i) => (
            <div key={i} style={{ background: '#f8fafc', padding: '8px 10px', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '12px' }}>
              {typeof item === 'object' && item !== null ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px' }}>
                  {Object.entries(item as Record<string, unknown>).map(([k, v]) => (
                    <span key={k}><strong style={{ color: '#475569' }}>{FIELD_LABELS[k] || k}:</strong> {v === null ? <span style={{ color: '#94a3b8' }}>-</span> : String(v)}</span>
                  ))}
                </div>
              ) : String(item)}
            </div>
          ))}
        </div>
      );
    }
    if (typeof value === 'object') {
      return renderDimensionFields(value as Record<string, unknown>);
    }
    return <span>{String(value)}</span>;
  };

  const renderDimensionFields = (fields: Record<string, unknown>) => (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
      <tbody>
        {Object.entries(fields).map(([key, value]) => (
          <tr key={key} style={{ borderBottom: '1px solid #f1f5f9' }}>
            <td style={{ padding: '8px 12px', color: '#64748b', fontWeight: 500, whiteSpace: 'nowrap', verticalAlign: 'top', width: '140px' }}>
              {FIELD_LABELS[key] || key}
            </td>
            <td style={{ padding: '8px 12px', color: '#1e293b' }}>
              {renderValue(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  const renderDimensions = (data: Record<string, unknown>) => {
    const dims = data.dimensions as Record<string, unknown> | undefined;
    if (!dims || typeof dims !== 'object') {
      return (
        <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
          <CopyableJson data={data} maxheight="400px" />
        </div>
      );
    }

    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '16px' }}>
        {Object.entries(dims).map(([key, value]) => {
          const meta = DIMENSION_META[key] || { label: key, icon: FileText, color: '#64748b' };
          const Icon = meta.icon;
          const hasError = !!(value && typeof value === 'object' && 'error' in (value as Record<string, unknown>));
          const hasData = !!(value && typeof value === 'object' && !hasError &&
            Object.values(value as Record<string, unknown>).some(v => v !== null && v !== undefined));

          return (
            <div key={key} style={{
              borderRadius: '10px', border: `1px solid ${hasError ? '#fecaca' : hasData ? '#e2e8f0' : '#f1f5f9'}`,
              background: hasError ? '#fef2f2' : 'white', overflow: 'hidden',
            }}>
              <div style={{
                padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '8px',
                background: hasError ? '#fef2f2' : `${meta.color}08`, borderBottom: `1px solid ${hasError ? '#fecaca' : '#e2e8f0'}`,
              }}>
                <Icon size={15} color={meta.color} />
                <span style={{ fontWeight: 600, fontSize: '14px', color: '#1e293b' }}>{meta.label}</span>
                {!hasData && !hasError && <span style={{ fontSize: '11px', color: '#94a3b8', marginLeft: 'auto' }}>暂无数据</span>}
                {hasError && <span style={{ fontSize: '11px', color: '#dc2626', marginLeft: 'auto' }}>解读失败</span>}
              </div>
              <div style={{ padding: '4px 0' }}>
                {hasError ? (
                  <div style={{ padding: '10px 14px', fontSize: '13px', color: '#dc2626' }}>
                    {String((value as Record<string, unknown>).error)}
                  </div>
                ) : hasData ? (
                  renderDimensionFields(value as Record<string, unknown>)
                ) : (
                  <div style={{ padding: '16px', textAlign: 'center', fontSize: '13px', color: '#94a3b8' }}>
                    文件中未提取到相关信息
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="page-fade-in">
      <StepHeader step={1} title="招标解读" subtitle="上传招标文件，AI自动提取15维度关键信息、评分标准、资质要求" color="#3b82f6" nextPath="/generate" nextLabel="下一步：投标生成" />

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--color-border)', marginBottom: '20px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '10px' }}>选择项目</h3>
        <select value={selectedProjectId} onChange={(e) => { setSelectedProjectId(e.target.value); setParseResult(null); setInterpretResult(null); setError(''); }}
          style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', background: 'white' }}>
          <option value="">请选择项目</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name} ({p.status})</option>)}
        </select>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {STEP_CONFIG.map((step, i) => {
          const isCurrent = i === stepIndex;
          const isCompleted = i <= maxStepIdx && !isCurrent;
          const isAccessible = i <= maxStepIdx;
          const Icon = step.icon;
          return (
            <div key={step.key} onClick={() => goToStep(step.key)}
              style={{ flex: 1, padding: '10px 12px', borderRadius: '8px', textAlign: 'center', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
                background: isCurrent ? 'var(--color-primary)' : isCompleted ? '#eff6ff' : 'var(--color-surface)',
                color: isCurrent ? 'white' : isCompleted ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                border: `1px solid ${isCurrent ? 'var(--color-primary)' : isCompleted ? '#bfdbfe' : 'var(--color-border)'}`,
                cursor: isAccessible && !isCurrent ? 'pointer' : 'default', transition: 'all 0.2s' }}>
              {isCompleted ? <CheckCircle2 size={14} /> : <Icon size={14} />}
              {step.label}
            </div>
          );
        })}
      </div>

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '28px', border: '1px solid var(--color-border)' }}>
        {restoring ? (
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <Loader2 size={28} color="var(--color-primary)" style={{ animation: 'spin 1s linear infinite', margin: '0 auto 12px' }} />
            <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)' }}>正在恢复项目状态...</p>
          </div>
        ) : currentStep === 'upload' && (
          <>
            <div style={{ border: `2px dashed ${dragOver ? 'var(--color-primary)' : 'var(--color-border)'}`, borderRadius: '12px', padding: '40px', textAlign: 'center', cursor: 'pointer', background: dragOver ? '#eff6ff' : 'transparent', transition: 'all 0.2s' }}
              onClick={() => document.getElementById('file-input')?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); const newFiles = Array.from(e.dataTransfer.files); setFiles(prev => [...prev, ...newFiles]); }}>
              <Upload size={36} color="var(--color-text-secondary)" style={{ margin: '0 auto 12px' }} />
              <p style={{ fontSize: '15px', fontWeight: 500, color: 'var(--color-text)' }}>点击或拖拽上传招标文件</p>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '6px' }}>支持 PDF / DOCX / DOC / TXT 格式，可同时选择多个文件</p>
              <input id="file-input" type="file" accept=".pdf,.docx,.doc,.txt,.wps,.md" multiple style={{ display: 'none' }}
                onChange={(e) => { const newFiles = Array.from(e.target.files || []); setFiles(prev => [...prev, ...newFiles]); e.target.value = ''; }} />
            </div>

            {files.length > 0 && (
              <div style={{ marginTop: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <h4 style={{ fontSize: '13px', fontWeight: 600 }}>待上传文件 ({files.length})</h4>
                  <button onClick={() => setFiles([])} style={{ fontSize: '12px', color: '#dc2626', background: 'none', border: 'none', cursor: 'pointer' }}>清空全部</button>
                </div>
                {files.map((f, i) => (
                  <div key={i} style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid var(--color-border)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <File size={16} color="var(--color-primary)" />
                    <span style={{ flex: 1, fontSize: '13px' }}>{f.name}</span>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>{formatFileSize(f.size)}</span>
                    <button onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8' }}><X size={14} /></button>
                  </div>
                ))}
                <button onClick={handleUpload} disabled={loading || !selectedProjectId}
                  style={{ marginTop: '12px', width: '100%', padding: '10px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '8px', cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer', fontSize: '14px', fontWeight: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: !selectedProjectId ? 0.5 : 1 }}>
                  {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Upload size={14} />}
                  {loading ? '上传中...' : `上传 ${files.length} 个文件`}
                </button>
              </div>
            )}

            {documents.length > 0 && (
              <div style={{ marginTop: '20px', padding: '14px', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                  <CheckCircle2 size={16} color="#16a34a" />
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#16a34a' }}>已上传 {documents.length} 个文件</span>
                </div>
                {documents.map(d => (
                  <div key={d.id} style={{ fontSize: '12px', color: 'var(--color-text-secondary)', padding: '2px 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FileText size={12} /> {d.file_name} ({formatFileSize(d.file_size)}) {d.parsed ? '✓ 已解析' : ''}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {currentStep === 'parse' && (
          <>
            <div style={{ marginBottom: '16px' }}>
              <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '10px' }}>已上传文件 ({documents.length})</h4>
              {documents.map(d => (
                <div key={d.id} style={{ padding: '10px 14px', background: d.parsed ? '#f0fdf4' : '#f8fafc', borderRadius: '8px', border: `1px solid ${d.parsed ? '#bbf7d0' : 'var(--color-border)'}`, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <FileText size={18} color={d.parsed ? '#16a34a' : 'var(--color-primary)'} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '13px', fontWeight: 500 }}>{d.file_name}</div>
                    <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>{formatFileSize(d.file_size)} {d.parsed ? '· 已解析' : '· 待解析'}</div>
                  </div>
                  <button onClick={() => handlePreviewDoc(d.id, d.file_name)}
                    style={{ padding: '4px 10px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--color-primary)' }}>
                    <Eye size={12} /> 预览
                  </button>
                </div>
              ))}
            </div>

            {loading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Loader2 size={32} color="var(--color-primary)" style={{ animation: 'spin 1s linear infinite', margin: '0 auto 12px' }} />
                <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)' }}>正在解析文件，提取文本和表格...</p>
              </div>
            ) : parseResult ? (
              <div>
                <div style={{ marginBottom: '16px', padding: '14px', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <CheckCircle2 size={16} color="#16a34a" />
                    <span style={{ fontSize: '14px', fontWeight: 600, color: '#16a34a' }}>文件解析完成</span>
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                    <span>文本长度: {parseResult.text_length?.toLocaleString()} 字</span>
                    <span>表格数: {parseResult.tables_count}</span>
                    <span>章节数: {parseResult.sections_count}</span>
                  </div>
                </div>

                {parseResult.sections && parseResult.sections.length > 0 && (
                  <div style={{ marginBottom: '16px' }}>
                    <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>章节结构</h4>
                    <div style={{ background: '#f8fafc', borderRadius: '8px', padding: '12px', border: '1px solid var(--color-border)', maxHeight: '200px', overflow: 'auto' }}>
                      {parseResult.sections.map((s, i) => (
                        <div key={i} style={{ paddingLeft: `${(s.level - 1) * 20}px`, fontSize: '13px', padding: '2px 0', color: 'var(--color-text-secondary)' }}>
                          <span style={{ color: 'var(--color-primary)', marginRight: '6px' }}>H{s.level}</span>{s.title}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '16px' }}>
                  <button onClick={() => goToStep('upload')} style={{ padding: '8px 20px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ChevronLeft size={14} /> 重新上传
                  </button>
                  <button onClick={handleParse} style={{ padding: '8px 24px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 500 }}>
                    重新解析
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '32px' }}>
                <FileText size={32} color="var(--color-text-secondary)" style={{ margin: '0 auto 12px' }} />
                <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginBottom: '16px' }}>文件已上传，点击下方按钮开始解析</p>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '10px' }}>
                  <button onClick={() => goToStep('upload')} style={{ padding: '10px 20px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ChevronLeft size={14} /> 继续上传
                  </button>
                  <button onClick={handleParse} style={{ padding: '10px 32px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    <FileSearch size={16} /> 开始解析
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {currentStep === 'interpret' && (
          <>
            {parseResult && (
              <div style={{ marginBottom: '16px', padding: '10px 14px', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0', fontSize: '13px', color: '#16a34a', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={14} />
                解析完成: {parseResult.text_length?.toLocaleString()} 字 | {parseResult.tables_count} 表格 | {parseResult.sections_count} 章节
              </div>
            )}

            <div style={{ marginBottom: '16px' }}>
              <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>已解析文件</h4>
              {documents.filter(d => d.parsed).map(d => (
                <div key={d.id} style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: '6px', border: '1px solid var(--color-border)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <FileText size={16} color="#16a34a" />
                  <span style={{ flex: 1, fontSize: '13px' }}>{d.file_name}</span>
                  <button onClick={() => handlePreviewDoc(d.id, d.file_name)}
                    style={{ padding: '4px 10px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--color-primary)' }}>
                    <Eye size={12} /> 查看内容
                  </button>
                </div>
              ))}
            </div>

            {loading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Loader2 size={32} color="var(--color-primary)" style={{ animation: 'spin 1s linear infinite', margin: '0 auto 12px' }} />
                <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)' }}>正在进行15维度AI解读，请稍候...</p>
                <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '6px' }}>此过程可能需要1-3分钟</p>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '24px' }}>
                <FileSearch size={32} color="var(--color-primary)" style={{ margin: '0 auto 12px' }} />
                <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginBottom: '16px' }}>文件解析完成，点击下方按钮进行AI智能解读</p>
                <div style={{ display: 'flex', justifyContent: 'center', gap: '10px' }}>
                  <button onClick={() => goToStep('parse')} style={{ padding: '10px 20px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ChevronLeft size={14} /> 返回解析
                  </button>
                  <button onClick={handleInterpret} style={{ padding: '10px 32px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    <FileSearch size={16} /> 开始AI解读
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {currentStep === 'done' && interpretResult && (
          <>
            {interpretResult.success ? (
              <div>
                <div style={{ marginBottom: '20px', padding: '14px', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <CheckCircle2 size={18} color="#16a34a" />
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#16a34a' }}>AI解读完成</span>
                  {interpretResult.warnings && interpretResult.warnings.length > 0 && (
                    <span style={{ fontSize: '12px', color: '#d97706', marginLeft: '8px' }}>({interpretResult.warnings.length} 条警告)</span>
                  )}
                </div>
                {interpretResult.data && renderDimensions(interpretResult.data)}
                <details style={{ marginTop: '16px' }}>
                  <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-secondary)', padding: '8px 0' }}>查看完整JSON数据</summary>
                  <CopyableJson data={interpretResult.data} maxheight="400px" />
                </details>
              </div>
            ) : (
              <div style={{ padding: '16px', background: '#fef2f2', borderRadius: '8px', border: '1px solid #fecaca' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                  <AlertCircle size={18} color="#dc2626" />
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#dc2626' }}>解读失败</span>
                </div>
                <p style={{ fontSize: '13px', color: '#dc2626' }}>{interpretResult.error || '未知错误'}</p>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
              <button onClick={() => goToStep('interpret')} style={{ padding: '8px 20px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ChevronLeft size={14} /> 返回上一步
              </button>
              <button onClick={handleInterpret} disabled={loading} style={{ padding: '8px 24px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '6px' }}>
                {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <FileSearch size={14} />}
                重新解读
              </button>
            </div>
          </>
        )}

        {error && (
          <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', border: '1px solid #fecaca', color: '#dc2626', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}
      </div>

      {previewDoc && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setPreviewDoc(null)}>
          <div style={{ width: '80%', maxWidth: '900px', maxHeight: '85vh', background: 'white', borderRadius: '12px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
            onClick={(e) => e.stopPropagation()}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={18} color="var(--color-primary)" />
                <span style={{ fontSize: '15px', fontWeight: 600 }}>{previewDoc.name}</span>
              </div>
              <button onClick={() => setPreviewDoc(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8' }}><X size={20} /></button>
            </div>
            <div style={{ padding: '12px 20px', background: '#f8fafc', borderBottom: '1px solid var(--color-border)', fontSize: '12px', color: 'var(--color-text-secondary)', display: 'flex', gap: '16px' }}>
              {Object.entries(previewDoc.metadata).map(([k, v]) => (
                <span key={k}>{k}: {String(v)}</span>
              ))}
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '20px' }}>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '13px', lineHeight: 1.8, color: 'var(--color-text)', margin: 0, fontFamily: 'inherit' }}>
                {previewDoc.content}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
