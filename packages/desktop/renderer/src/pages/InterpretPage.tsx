import { useState, useEffect } from 'react';
import { Upload, FileSearch, Loader2 } from 'lucide-react';
import { interpretApi, projectApi, type Project } from '../services/api';
import { useAppStore } from '../stores/appStore';
import StepHeader from '../components/common/StepHeader';

type Step = 'upload' | 'parse' | 'interpret' | 'done';

export default function InterpretPage() {
  const [file, setFile] = useState<File | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [currentStep, setCurrentStep] = useState<Step>('upload');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [parseResult, setParseResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string>('');

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

  const handleUpload = async () => {
    if (!file || !selectedProjectId) return;
    setLoading(true);
    setError('');
    try {
      const uploadRes = await interpretApi.upload(selectedProjectId, file);
      setResult(uploadRes.data);
      setCurrentStep('parse');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '上传失败');
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
      setParseResult(res.data);
      setCurrentStep('interpret');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '解析失败');
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
      setResult(res.data);
      setCurrentStep('done');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '解读失败');
    } finally {
      setLoading(false);
    }
  };

  const steps = [
    { key: 'upload', label: '1. 上传文件', action: handleUpload },
    { key: 'parse', label: '2. 解析文件', action: handleParse },
    { key: 'interpret', label: '3. AI解读', action: handleInterpret },
    { key: 'done', label: '4. 完成', action: () => {} },
  ] as const;

  const stepIndex = steps.findIndex(s => s.key === currentStep);

  return (
    <div className="page-fade-in">
      <StepHeader
        step={1}
        title="招标解读"
        subtitle="上传招标文件，AI自动提取15维度关键信息、评分标准、资质要求"
        color="#3b82f6"
        nextPath="/generate"
        nextLabel="下一步：投标生成"
      />

      <div
        style={{
          background: 'var(--color-surface)',
          borderRadius: '12px',
          padding: '24px',
          border: '1px solid var(--color-border)',
          marginBottom: '20px',
        }}
      >
        <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px' }}>选择项目</h3>
        <select
          value={selectedProjectId}
          onChange={(e) => setSelectedProjectId(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid var(--color-border)',
            borderRadius: '6px',
            fontSize: '14px',
          }}
        >
          <option value="">请选择项目</option>
          {projects.map(p => (
            <option key={p.id} value={p.id}>{p.name} ({p.status})</option>
          ))}
        </select>
      </div>

      <div
        style={{
          display: 'flex',
          gap: '12px',
          marginBottom: '20px',
        }}
      >
        {steps.map((step, i) => (
          <div
            key={step.key}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              textAlign: 'center',
              fontSize: '13px',
              fontWeight: 500,
              background: i <= stepIndex ? 'var(--color-primary)' : 'var(--color-surface)',
              color: i <= stepIndex ? 'white' : 'var(--color-text-secondary)',
              border: `1px solid ${i <= stepIndex ? 'var(--color-primary)' : 'var(--color-border)'}`,
            }}
          >
            {step.label}
          </div>
        ))}
      </div>

      <div
        style={{
          background: 'var(--color-surface)',
          borderRadius: '12px',
          padding: '32px',
          border: '1px solid var(--color-border)',
        }}
      >
        {currentStep === 'upload' && (
          <>
            <div
              style={{
                border: '2px dashed var(--color-border)',
                borderRadius: '12px',
                padding: '48px',
                textAlign: 'center',
                cursor: 'pointer',
              }}
              onClick={() => document.getElementById('file-input')?.click()}
            >
              <Upload size={40} color="var(--color-text-secondary)" style={{ margin: '0 auto 16px' }} />
              <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--color-text)' }}>
                点击或拖拽上传招标文件
              </p>
              <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '8px' }}>
                支持 PDF / DOCX / DOC / TXT 格式
              </p>
              <input
                id="file-input"
                type="file"
                accept=".pdf,.docx,.doc,.txt"
                style={{ display: 'none' }}
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </div>

            {file && (
              <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                <FileSearch size={18} color="var(--color-primary)" />
                <span style={{ fontSize: '14px' }}>{file.name}</span>
                <button
                  onClick={handleUpload}
                  disabled={loading || !selectedProjectId}
                  style={{
                    marginLeft: 'auto',
                    padding: '8px 20px',
                    background: 'var(--color-primary)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: loading || !selectedProjectId ? 'not-allowed' : 'pointer',
                    fontSize: '13px',
                    opacity: !selectedProjectId ? 0.5 : 1,
                  }}
                >
                  {loading ? '上传中...' : '上传并解析'}
                </button>
              </div>
            )}
          </>
        )}

        {(currentStep === 'parse' || currentStep === 'interpret') && (
          <div style={{ textAlign: 'center', padding: '32px' }}>
            {loading ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                <Loader2 size={32} color="var(--color-primary)" style={{ animation: 'spin 1s linear infinite' }} />
                <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)' }}>
                  {currentStep === 'parse' ? '正在解析文件...' : '正在进行15维度AI解读，请稍候...'}
                </p>
              </div>
            ) : (
              <button
                onClick={currentStep === 'parse' ? handleParse : handleInterpret}
                style={{
                  padding: '12px 32px',
                  background: 'var(--color-primary)',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
              >
                {currentStep === 'parse' ? '开始解析' : '开始AI解读'}
              </button>
            )}
          </div>
        )}

        {currentStep === 'done' && result && (
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>解读结果</h3>
            {(() => {
              const data = result.data as Record<string, unknown> | undefined;
              if (data && typeof data === 'object' && 'dimensions' in data) {
                const dims = (data as { dimensions: Record<string, unknown> }).dimensions;
                return (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '16px' }}>
                    {Object.entries(dims).map(([key, value]) => (
                      <div
                        key={key}
                        style={{
                          padding: '12px',
                          border: '1px solid var(--color-border)',
                          borderRadius: '8px',
                          fontSize: '12px',
                        }}
                      >
                        <div style={{ fontWeight: 600, marginBottom: '4px' }}>{key}</div>
                        <pre style={{ maxHeight: '120px', overflow: 'auto', fontSize: '11px', margin: 0 }}>
                          {JSON.stringify(value, null, 1)}
                        </pre>
                      </div>
                    ))}
                  </div>
                );
              }
              return (
                <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                  <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '8px' }}>
                    解读结果格式非标准维度格式，原始数据如下：
                  </div>
                  <pre style={{ maxHeight: '300px', overflow: 'auto', fontSize: '12px', margin: 0 }}>
                    {JSON.stringify(data, null, 2)}
                  </pre>
                </div>
              );
            })()}
            <details>
              <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-secondary)' }}>
                查看完整JSON
              </summary>
              <pre
                style={{
                  background: '#f8fafc',
                  padding: '16px',
                  borderRadius: '8px',
                  fontSize: '12px',
                  overflow: 'auto',
                  maxHeight: '400px',
                }}
              >
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </div>
        )}

        {error && (
          <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px' }}>
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
