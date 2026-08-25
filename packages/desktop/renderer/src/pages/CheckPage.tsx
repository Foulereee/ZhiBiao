import { useState, useEffect, useRef } from 'react';
import { ShieldCheck, Loader2, AlertTriangle, CheckCircle2, XCircle, Download, FileText, Upload, FolderOpen, Copy } from 'lucide-react';
import { checkApi, projectApi, type Project } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';

type CheckType = 'fullCheck' | 'compliance' | 'disqualification' | 'qualification' | 'pricing' | 'fitScore' | 'selfcheck' | 'deposit' | 'signature' | 'validity' | 'consistency' | 'duplicate' | 'mandatoryReq' | 'docIntegrity' | 'aiTextCheck' | 'riskScore' | 'crossCheck' | 'sampleReport' | 'jointBid' | 'ebidSubmit' | 'pricingLogic';
type CheckMode = 'project' | 'upload';

interface CheckOption {
  key: CheckType;
  label: string;
  description: string;
  color: string;
}

export default function CheckPage() {
  const [checkMode, setCheckMode] = useState<CheckMode>('upload');
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string>('');
  const [activeCheck, setActiveCheck] = useState<CheckType>('fullCheck');
  const [reports, setReports] = useState<Array<{ id: string; type: string; risk_level: string; created_at: string }>>([]);

  const [bidFile, setBidFile] = useState<File | null>(null);
  const [tenderFile, setTenderFile] = useState<File | null>(null);
  const bidFileRef = useRef<HTMLInputElement>(null);
  const tenderFileRef = useRef<HTMLInputElement>(null);

  const { currentProjectId } = useAppStore();

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (currentProjectId && !selectedProjectId) {
      setSelectedProjectId(currentProjectId);
    }
  }, [currentProjectId]);

  const loadProjects = async () => {
    try {
      const res = await projectApi.list();
      setProjects(res.data.projects || []);
    } catch (e) {
      console.error('加载项目列表失败', e);
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
  ];

  const handleProjectCheck = async () => {
    if (!selectedProjectId) return;
    setLoading(true);
    setError('');
    setResults(null);
    try {
      let res;
      switch (activeCheck) {
        case 'compliance': res = await checkApi.compliance(selectedProjectId); break;
        case 'disqualification': res = await checkApi.disqualification(selectedProjectId); break;
        case 'qualification': res = await checkApi.qualification(selectedProjectId); break;
        case 'pricing': res = await checkApi.pricing(selectedProjectId); break;
        case 'fitScore': res = await checkApi.fitScore(selectedProjectId); break;
        case 'selfcheck': res = await checkApi.selfcheck(selectedProjectId); break;
        case 'deposit': res = await checkApi.deposit(selectedProjectId); break;
        case 'signature': res = await checkApi.signature(selectedProjectId); break;
        case 'validity': res = await checkApi.validity(selectedProjectId); break;
        case 'consistency': res = await checkApi.consistency(selectedProjectId); break;
        case 'duplicate': res = await checkApi.duplicate(selectedProjectId); break;
        case 'mandatoryReq': res = await checkApi.mandatoryReq(selectedProjectId); break;
        case 'docIntegrity': res = await checkApi.docIntegrity(selectedProjectId); break;
        case 'aiTextCheck': res = await checkApi.aiTextCheck(selectedProjectId); break;
        case 'riskScore': res = await checkApi.riskScore(selectedProjectId); break;
        case 'crossCheck': res = await checkApi.crossCheck(selectedProjectId); break;
        case 'sampleReport': res = await checkApi.sampleReport(selectedProjectId); break;
        case 'jointBid': res = await checkApi.jointBid(selectedProjectId); break;
        case 'ebidSubmit': res = await checkApi.ebidSubmit(selectedProjectId); break;
        case 'pricingLogic': res = await checkApi.pricingLogic(selectedProjectId); break;
        case 'fullCheck':
        default: res = await checkApi.fullCheck(selectedProjectId); break;
      }
      setResults(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '检查失败');
    } finally {
      setLoading(false);
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
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '16px' }}>
          <div style={{ padding: '12px', background: '#ecfdf5', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#059669' }}>{passCount}</div>
            <div style={{ fontSize: '11px', color: '#059669' }}>通过</div>
          </div>
          <div style={{ padding: '12px', background: '#fef2f2', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#dc2626' }}>{failCount}</div>
            <div style={{ fontSize: '11px', color: '#dc2626' }}>存在问题</div>
          </div>
          <div style={{ padding: '12px', background: '#fffbeb', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#d97706' }}>{errorCount}</div>
            <div style={{ fontSize: '11px', color: '#d97706' }}>执行异常</div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {checkItems.map(item => (
            <div
              key={item.key}
              style={{
                padding: '10px 14px',
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                borderLeft: item.isHigh ? '3px solid #dc2626' : item.success ? '3px solid #059669' : '3px solid #d97706',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {item.success ? (
                  item.isHigh ? <XCircle size={16} color="#dc2626" /> : <CheckCircle2 size={16} color="#059669" />
                ) : (
                  <AlertTriangle size={16} color="#d97706" />
                )}
                <span style={{ fontSize: '13px', fontWeight: 500 }}>{item.label}</span>
              </div>
              <span style={{
                fontSize: '12px',
                padding: '2px 8px',
                borderRadius: '10px',
                background: item.isHigh ? '#fef2f2' : item.success ? '#ecfdf5' : '#fffbeb',
                color: item.isHigh ? '#dc2626' : item.success ? '#059669' : '#d97706',
              }}>
                {item.isHigh ? '高风险' : item.success ? '通过' : '异常'}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderSingleCheckResult = (data: Record<string, unknown>) => {
    const riskLevel = data.risk_level as string || 'low';
    const hasCritical = data.has_critical_issues as boolean || false;

    return (
      <div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '12px',
          borderRadius: '8px',
          marginBottom: '12px',
          background: `${getRiskColor(riskLevel)}15`,
        }}>
          {riskLevel === 'high' || hasCritical ? (
            <XCircle size={20} color="#dc2626" />
          ) : (
            <CheckCircle2 size={20} color="#059669" />
          )}
          <span style={{ fontWeight: 600, color: getRiskColor(riskLevel) }}>
            风险等级：{riskLevel === 'high' ? '高风险' : riskLevel === 'medium' ? '中风险' : '低风险'}
          </span>
        </div>
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

      {checkMode === 'project' && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)', marginBottom: '20px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px' }}>选择项目</h3>
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
          >
            <option value="">请选择项目</option>
            {projects.map(p => (
              <option key={p.id} value={p.id}>{p.name} ({p.status})</option>
            ))}
          </select>
        </div>
      )}

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

      <button
        onClick={handleCheck}
        disabled={loading || (checkMode === 'project' && !selectedProjectId) || (checkMode === 'upload' && !bidFile)}
        style={{
          width: '100%',
          padding: '12px',
          background: checkOptions.find(o => o.key === activeCheck)?.color || 'var(--color-primary)',
          color: 'white',
          border: 'none',
          borderRadius: '8px',
          cursor: loading || (checkMode === 'project' && !selectedProjectId) || (checkMode === 'upload' && !bidFile) ? 'not-allowed' : 'pointer',
          fontSize: '14px',
          fontWeight: 600,
          opacity: (checkMode === 'project' && !selectedProjectId) || (checkMode === 'upload' && !bidFile) ? 0.5 : 1,
          marginBottom: '20px',
        }}
      >
        {loading ? '检查中...' : `运行${checkOptions.find(o => o.key === activeCheck)?.label || '检查'}`}
      </button>

      {results && (
        <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600 }}>
              检查结果
              {(results as Record<string, unknown>).source === 'upload' && (
                <span style={{ fontSize: '12px', fontWeight: 400, color: 'var(--color-text-secondary)', marginLeft: '8px' }}>
                  来源：上传文件
                </span>
              )}
            </h3>
          </div>

          {activeCheck === 'fullCheck' && typeof results === 'object' && results !== null && 'data' in results
            ? renderFullCheckSummary((results as Record<string, unknown>).data as Record<string, unknown>)
            : renderSingleCheckResult(results as Record<string, unknown>)}
        </div>
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
                    {report.risk_level === 'high' ? '高风险' : report.risk_level === 'medium' ? '中风险' : '低风险'}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginLeft: '8px' }}>
                    {report.created_at ? new Date(report.created_at).toLocaleString() : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
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
    </div>
  );
}
