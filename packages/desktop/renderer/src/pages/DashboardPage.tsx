import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileSearch, PenTool, ShieldCheck, FileText, Plus, ArrowRight,
  CheckCircle2, Clock, Newspaper, FolderOpen,
  Zap, Activity, ChevronDown, Lightbulb, AlertCircle, ShieldAlert, FileCheck,
} from 'lucide-react';
import { projectApi, type Project } from '../services/api';
import { useAppStore } from '../stores/appStore';

const pipelineSteps = [
  { path: '/interpret', icon: FileSearch, label: '招标解读', color: '#3b82f6', bg: '#eff6ff',
    desc: '上传招标文件，AI提取关键信息',
    input: '招标文件 (PDF/DOCX/TXT)',
    output: '15维度解读报告、评分矩阵、风险预警',
    rules: ['支持自动解析表格/图片', '评分标准自动映射', '强制性条款自动标注'] },
  { path: '/generate', icon: PenTool, label: '投标生成', color: '#059669', bg: '#ecfdf5',
    desc: '大纲编辑→AI生成正文',
    input: '解读结果 + 知识库资料',
    output: '完整投标文件正文、配图',
    rules: ['大纲可拖拽编辑调整', '闸门审核通过后进入下一步', 'AI配图自动去水印'] },
  { path: '/check', icon: ShieldCheck, label: '投标检查', color: '#d97706', bg: '#fffbeb',
    desc: '21项全面检查审核',
    input: '生成的投标文件',
    output: '检查报告 (合规/废标/资质/查重)',
    rules: ['21项检查可单独或批量运行', '支持上传已有标书直接检查', '★▲参数逐条响应对照'] },
  { path: '/format', icon: FileText, label: '文档输出', color: '#475569', bg: '#f8fafc',
    desc: '一键排版→PDF导出',
    input: '检查通过的投标文件',
    output: '格式化DOCX/PDF、修订痕迹',
    rules: ['4种模式：排版/检查/对比/美化', '7种标题编号格式', '60+排版配置项'] },
];

const quickActions = [
  { path: '/interpret', icon: FileSearch, label: '上传招标文件', desc: '开始解读', color: '#3b82f6', bg: '#eff6ff' },
  { path: '/check', icon: ShieldAlert, label: '上传标书检查', desc: '快速检查', color: '#d97706', bg: '#fffbeb' },
  { path: '/format', icon: FileCheck, label: '上传文档排版', desc: '一键排版', color: '#475569', bg: '#f8fafc' },
  { path: '/news', icon: Newspaper, label: '浏览今日商机', desc: '热点资讯', color: '#059669', bg: '#ecfdf5' },
];

const statusToStep: Record<string, number> = {
  created: 0, interpreting: 0, analyzing: 0,
  outlining: 1, generating: 1,
  checking: 2, formatting: 3,
  completed: 4, archived: 4,
};

const statusMap: Record<string, { label: string; color: string }> = {
  created: { label: '已创建', color: '#6b7280' },
  interpreting: { label: '解读中', color: '#3b82f6' },
  analyzing: { label: '分析中', color: '#3b82f6' },
  outlining: { label: '大纲中', color: '#059669' },
  generating: { label: '生成中', color: '#059669' },
  checking: { label: '检查中', color: '#d97706' },
  formatting: { label: '排版中', color: '#475569' },
  completed: { label: '已完成', color: '#059669' },
  archived: { label: '已归档', color: '#6b7280' },
};

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [expandedFlow, setExpandedFlow] = useState<number | null>(null);
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const { setCurrentProject, currentProjectId } = useAppStore();
  const navigate = useNavigate();

  useEffect(() => { loadProjects(); }, []);

  useEffect(() => {
    if (!projectPickerOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setProjectPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [projectPickerOpen]);

  const loadProjects = async () => {
    try {
      const res = await projectApi.list();
      setProjects(res.data.projects || []);
    } catch (e) {
      console.error('加载项目列表失败', e);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return;
    try {
      const res = await projectApi.create(newProjectName.trim());
      setNewProjectName('');
      setShowCreate(false);
      await loadProjects();
      const newId = res.data?.project_id || res.data?.id;
      if (newId) setCurrentProject(newId);
    } catch (e) {
      console.error('创建项目失败', e);
    }
  };

  const currentProject = projects.find(p => p.id === currentProjectId);
  const displayedProject = currentProject || projects[0];
  const currentStep = displayedProject ? (statusToStep[displayedProject.status] ?? 0) : 0;

  const totalProjects = projects.length;
  const completedProjects = projects.filter(p => p.status === 'completed' || p.status === 'archived').length;
  const inProgressProjects = projects.filter(p => !['completed', 'archived', 'created'].includes(p.status)).length;
  const pendingProjects = projects.filter(p => p.status === 'created').length;

  return (
    <div className="page-fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '22px', fontWeight: 700, color: '#0f172a' }}>工作台</h2>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>
            全流程智能招投标，按步骤推进
          </p>
        </div>
        <button
          onClick={() => { setShowCreate(true); setNewProjectName(''); }}
          style={{
            padding: '8px 18px', background: 'var(--color-primary)', color: 'white',
            border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
            display: 'flex', alignItems: 'center', gap: '6px',
            boxShadow: '0 2px 8px rgba(26,86,219,0.25)',
          }}
        >
          <Plus size={15} /> 新建项目
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '18px' }}>
        {[
          { icon: FolderOpen, label: '总项目', value: totalProjects, color: '#1a56db', bg: '#eff6ff' },
          { icon: Activity, label: '进行中', value: inProgressProjects, color: '#059669', bg: '#ecfdf5' },
          { icon: Clock, label: '待启动', value: pendingProjects, color: '#d97706', bg: '#fffbeb' },
          { icon: CheckCircle2, label: '已完成', value: completedProjects, color: '#475569', bg: '#f8fafc' },
        ].map(stat => (
          <div key={stat.label} style={{
            background: 'var(--color-surface)', borderRadius: '12px', padding: '14px 16px',
            border: '1px solid var(--color-border)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <div style={{
                width: '30px', height: '30px', borderRadius: '8px', background: stat.bg,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <stat.icon size={15} color={stat.color} />
              </div>
              <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>{stat.label}</span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>{stat.value}</div>
          </div>
        ))}
      </div>

      {(currentProject || projects.length > 0) && (
        <div style={{
          background: 'var(--color-surface)', borderRadius: '14px', padding: '18px 24px',
          border: '1px solid var(--color-border)', marginBottom: '18px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
              <div style={{
                width: '34px', height: '34px', borderRadius: '10px',
                background: `linear-gradient(135deg, ${pipelineSteps[Math.min(currentStep, 3)].color}, ${pipelineSteps[Math.min(currentStep, 3)].color}cc)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}>
                {(() => { const I = pipelineSteps[Math.min(currentStep, 3)].icon; return <I size={15} color="white" />; })()}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div ref={pickerRef} style={{ position: 'relative', display: 'inline-block' }}>
                  <button
                    onClick={() => setProjectPickerOpen(v => !v)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      padding: '4px 10px 4px 8px', background: projectPickerOpen ? '#f1f5f9' : 'transparent',
                      border: '1px solid var(--color-border)', borderRadius: '6px',
                      cursor: 'pointer', fontSize: '14px', fontWeight: 600, color: '#0f172a',
                      maxWidth: '320px',
                    }}
                  >
                    <FolderOpen size={13} color="var(--color-text-secondary)" style={{ flexShrink: 0 }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {currentProject ? currentProject.name : projects[0]?.name || '选择项目'}
                    </span>
                    <ChevronDown size={12} color="var(--color-text-secondary)" style={{
                      flexShrink: 0, transform: projectPickerOpen ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s',
                    }} />
                  </button>
                  {projectPickerOpen && (
                    <div style={{
                      position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 50,
                      background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px',
                      boxShadow: '0 4px 16px rgba(0,0,0,0.12)', minWidth: '280px', maxWidth: '360px',
                      maxHeight: '320px', overflowY: 'auto',
                    }}>
                      {projects.length === 0 ? (
                        <div style={{ padding: '14px', fontSize: '12px', color: 'var(--color-text-secondary)', textAlign: 'center' }}>
                          暂无项目
                        </div>
                      ) : projects.map(p => {
                        const pStep = statusToStep[p.status] ?? 0;
                        const st = statusMap[p.status] || { label: p.status, color: '#6b7280' };
                        const isActive = p.id === currentProjectId;
                        return (
                          <div
                            key={p.id}
                            onClick={() => { setCurrentProject(p.id); setProjectPickerOpen(false); }}
                            style={{
                              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                              padding: '8px 12px', cursor: 'pointer',
                              background: isActive ? '#eff6ff' : 'transparent',
                              borderBottom: '1px solid #f1f5f9',
                            }}
                            onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLDivElement).style.background = '#f8fafc'; }}
                            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = isActive ? '#eff6ff' : 'transparent'; }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
                              {isActive && <CheckCircle2 size={12} color="var(--color-primary)" style={{ flexShrink: 0 }} />}
                              <span style={{ fontSize: '12px', fontWeight: isActive ? 600 : 500, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {p.name}
                              </span>
                            </div>
                            <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', fontWeight: 500, background: `${st.color}10`, color: st.color, flexShrink: 0 }}>
                              {st.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                {currentProject && (
                  <span style={{
                    fontSize: '10px', padding: '1px 7px', borderRadius: '5px', fontWeight: 500, marginLeft: '8px',
                    background: `${(statusMap[currentProject.status] || statusMap.created).color}12`,
                    color: (statusMap[currentProject.status] || statusMap.created).color,
                  }}>
                    {(statusMap[currentProject.status] || statusMap.created).label}
                  </span>
                )}
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '1px' }}>当前项目进度</div>
              </div>
            </div>
            <button
              onClick={() => {
                if (!currentProject && projects[0]) setCurrentProject(projects[0].id);
                navigate(pipelineSteps[Math.min(currentStep, 3)].path);
              }}
              style={{
                padding: '6px 14px', background: pipelineSteps[Math.min(currentStep, 3)].color,
                color: 'white', border: 'none', borderRadius: '7px', cursor: 'pointer',
                fontSize: '12px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px',
                flexShrink: 0,
              }}
            >
              继续工作 <ArrowRight size={13} />
            </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {pipelineSteps.map((step, idx) => {
              const isCompleted = currentStep > idx;
              const isActive = currentStep === idx;
              return (
                <div key={step.path} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                  <div
                    onClick={() => { if (isCompleted || isActive) navigate(step.path); }}
                    style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: isCompleted || isActive ? 'pointer' : 'default', flex: 1 }}
                  >
                    <div style={{
                      width: '26px', height: '26px', borderRadius: '50%', flexShrink: 0,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: isCompleted ? step.color : isActive ? `linear-gradient(135deg, ${step.color}, ${step.color}cc)` : '#f1f5f9',
                      border: isActive ? `2px solid ${step.color}` : isCompleted ? `2px solid ${step.color}` : '2px solid #e2e8f0',
                      boxShadow: isActive ? `0 0 0 3px ${step.color}20` : 'none',
                    }}>
                      {isCompleted ? <CheckCircle2 size={12} color="white" /> : isActive ? <step.icon size={12} color="white" /> : <step.icon size={11} color="#94a3b8" />}
                    </div>
                    <div>
                      <div style={{ fontSize: '11px', fontWeight: isActive || isCompleted ? 600 : 400, color: isActive ? step.color : isCompleted ? step.color : '#94a3b8' }}>
                        {step.label}
                      </div>
                      <div style={{ fontSize: '9px', color: isCompleted || isActive ? 'var(--color-text-secondary)' : '#cbd5e1' }}>
                        {isCompleted ? '已完成' : isActive ? '进行中' : '待处理'}
                      </div>
                    </div>
                  </div>
                  {idx < pipelineSteps.length - 1 && (
                    <div style={{
                      width: '20px', height: '2px', flexShrink: 0,
                      background: isCompleted ? `linear-gradient(90deg, ${step.color}, ${pipelineSteps[idx + 1].color})` : '#e2e8f0',
                      borderRadius: '1px', margin: '0 2px',
                    }} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div style={{
        background: 'var(--color-surface)', borderRadius: '14px', padding: '20px',
        border: '1px solid var(--color-border)', marginBottom: '18px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <Lightbulb size={16} color="#1a56db" />
          <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a' }}>投标工作流程</h3>
          <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)', background: '#f1f5f9', padding: '1px 6px', borderRadius: '4px' }}>点击节点查看详情</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0', position: 'relative' }}>
          {pipelineSteps.map((step, idx) => {
            const isExpanded = expandedFlow === idx;
            const isLast = idx === pipelineSteps.length - 1;
            return (
              <div key={step.path} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div
                  onClick={() => setExpandedFlow(isExpanded ? null : idx)}
                  style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px',
                    cursor: 'pointer', width: '100%', padding: '8px 4px',
                    borderRadius: '10px', transition: 'background 0.15s',
                    background: isExpanded ? step.bg : 'transparent',
                  }}
                >
                  <div style={{
                    width: '44px', height: '44px', borderRadius: '50%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: isExpanded ? `linear-gradient(135deg, ${step.color}, ${step.color}cc)` : step.bg,
                    border: `2px solid ${isExpanded ? step.color : `${step.color}40`}`,
                    boxShadow: isExpanded ? `0 4px 12px ${step.color}30` : 'none',
                    transition: 'all 0.2s ease',
                  }}>
                    <step.icon size={20} color={isExpanded ? 'white' : step.color} />
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: isExpanded ? step.color : '#0f172a' }}>
                      {step.label}
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)', marginTop: '1px' }}>
                      Step {idx + 1}
                    </div>
                  </div>
                  <ChevronDown size={14} color={isExpanded ? step.color : '#cbd5e1'} style={{
                    transform: isExpanded ? 'rotate(180deg)' : 'rotate(0)',
                    transition: 'transform 0.2s',
                  }} />
                </div>

                {!isLast && (
                  <div style={{
                    position: 'absolute',
                    top: '30px',
                    left: `calc(${(idx + 0.5) * 25}% + 12px)`,
                    width: `calc(25% - 56px)`,
                    height: '2px',
                    background: `linear-gradient(90deg, ${step.color}60, ${pipelineSteps[idx + 1].color}60)`,
                    borderRadius: '1px',
                  }} />
                )}
              </div>
            );
          })}
        </div>

        {expandedFlow !== null && (
          <div style={{
            marginTop: '12px', padding: '16px 20px',
            background: pipelineSteps[expandedFlow].bg,
            borderRadius: '10px', border: `1px solid ${pipelineSteps[expandedFlow].color}20`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
              <div style={{
                width: '28px', height: '28px', borderRadius: '7px',
                background: pipelineSteps[expandedFlow].color,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {(() => { const I = pipelineSteps[expandedFlow].icon; return <I size={14} color="white" />; })()}
              </div>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a' }}>
                {pipelineSteps[expandedFlow].label}
              </span>
              <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>
                {pipelineSteps[expandedFlow].desc}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '12px' }}>
              <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: '8px', padding: '10px 14px' }}>
                <div style={{ fontSize: '10px', fontWeight: 600, color: pipelineSteps[expandedFlow].color, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  输入
                </div>
                <div style={{ fontSize: '12px', color: '#334155' }}>{pipelineSteps[expandedFlow].input}</div>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: '8px', padding: '10px 14px' }}>
                <div style={{ fontSize: '10px', fontWeight: 600, color: pipelineSteps[expandedFlow].color, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  输出
                </div>
                <div style={{ fontSize: '12px', color: '#334155' }}>{pipelineSteps[expandedFlow].output}</div>
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.7)', borderRadius: '8px', padding: '10px 14px', marginBottom: '12px' }}>
              <div style={{ fontSize: '10px', fontWeight: 600, color: pipelineSteps[expandedFlow].color, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                规则与说明
              </div>
              {pipelineSteps[expandedFlow].rules.map((rule, ri) => (
                <div key={ri} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '3px' }}>
                  <AlertCircle size={11} color={pipelineSteps[expandedFlow].color} style={{ flexShrink: 0, marginTop: '2px' }} />
                  <span style={{ fontSize: '11px', color: '#475569' }}>{rule}</span>
                </div>
              ))}
            </div>
            <button
              onClick={() => navigate(pipelineSteps[expandedFlow].path)}
              style={{
                padding: '6px 16px', background: pipelineSteps[expandedFlow].color, color: 'white',
                border: 'none', borderRadius: '6px', cursor: 'pointer',
                fontSize: '12px', fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: '4px',
              }}
            >
              进入{pipelineSteps[expandedFlow].label} <ArrowRight size={12} />
            </button>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '18px' }}>
        <div style={{
          background: 'var(--color-surface)', borderRadius: '14px', padding: '18px',
          border: '1px solid var(--color-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Zap size={15} color="#1a56db" />
            <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#0f172a' }}>快捷入口</h3>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {quickActions.map(action => (
              <div
                key={action.path}
                onClick={() => navigate(action.path)}
                style={{
                  padding: '10px', borderRadius: '8px', background: action.bg,
                  cursor: 'pointer', transition: 'all 0.15s', border: '1px solid transparent',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = action.color; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = 'transparent'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                  <action.icon size={14} color={action.color} />
                  <span style={{ fontSize: '12px', fontWeight: 600, color: '#0f172a' }}>{action.label}</span>
                </div>
                <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>{action.desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          background: 'var(--color-surface)', borderRadius: '14px', padding: '18px',
          border: '1px solid var(--color-border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <FolderOpen size={15} color="#1a56db" />
            <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#0f172a' }}>项目列表</h3>
            <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)', background: '#f1f5f9', padding: '1px 6px', borderRadius: '8px' }}>
              {totalProjects} 个
            </span>
          </div>

          {showCreate && (
            <div style={{
              display: 'flex', gap: '6px', alignItems: 'center',
              padding: '8px 10px', marginBottom: '8px',
              background: '#f0f7ff', borderRadius: '8px', border: '1px dashed #3b82f6',
            }}>
              <Plus size={14} color="#3b82f6" style={{ flexShrink: 0 }} />
              <input
                type="text"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                placeholder="输入项目名称"
                style={{ flex: 1, padding: '5px 10px', border: '1px solid #bfdbfe', borderRadius: '5px', fontSize: '12px', background: 'white' }}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateProject()}
                autoFocus
              />
              <button onClick={handleCreateProject} style={{
                padding: '5px 12px', background: '#059669', color: 'white', border: 'none',
                borderRadius: '5px', cursor: 'pointer', fontSize: '11px', fontWeight: 500,
              }}>确认</button>
              <button onClick={() => { setShowCreate(false); setNewProjectName(''); }} style={{
                padding: '5px 10px', background: 'white', color: 'var(--color-text)',
                border: '1px solid var(--color-border)', borderRadius: '5px', cursor: 'pointer', fontSize: '11px',
              }}>取消</button>
            </div>
          )}

          {loading ? (
            <p style={{ color: 'var(--color-text-secondary)', textAlign: 'center', padding: '20px', fontSize: '12px' }}>加载中...</p>
          ) : projects.length === 0 && !showCreate ? (
            <div style={{ textAlign: 'center', padding: '24px' }}>
              <div style={{
                width: '40px', height: '40px', borderRadius: '10px', background: '#eff6ff',
                display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 8px',
              }}>
                <Zap size={18} color="#1a56db" />
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '10px' }}>
                暂无项目，点击新建
              </p>
              <button
                onClick={() => { setShowCreate(true); setNewProjectName(''); }}
                style={{ padding: '5px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: '4px' }}
              >
                <Plus size={12} /> 创建项目
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '240px', overflowY: 'auto' }}>
              {projects.map((project) => {
                const st = statusMap[project.status] || { label: project.status, color: '#6b7280' };
                const pStep = statusToStep[project.status] ?? 0;
                const isActive = project.id === currentProjectId;
                const stepIdx = Math.min(pStep, 3);
                const StepIcon = pipelineSteps[stepIdx].icon;
                const stepColor = pipelineSteps[stepIdx].color;

                return (
                  <div
                    key={project.id}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '8px 10px',
                      border: `1px solid ${isActive ? 'var(--color-primary)' : 'var(--color-border)'}`,
                      borderRadius: '8px', cursor: 'pointer',
                      background: isActive ? '#eff6ff' : 'transparent',
                      transition: 'all 0.15s',
                    }}
                    onClick={() => setCurrentProject(project.id)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
                      <div style={{
                        width: '28px', height: '28px', borderRadius: '6px',
                        background: isActive ? 'var(--color-primary)' : pipelineSteps[stepIdx].bg,
                        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      }}>
                        {isActive ? <FolderOpen size={12} color="white" /> : <StepIcon size={12} color={stepColor} />}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '12px', fontWeight: 500, color: '#0f172a', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</span>
                          {isActive && (
                            <span style={{ fontSize: '8px', padding: '0px 4px', borderRadius: '3px', background: 'var(--color-primary)', color: 'white', fontWeight: 600, flexShrink: 0 }}>
                              当前
                            </span>
                          )}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '1px' }}>
                          {pipelineSteps.map((s, i) => (
                            <div key={i} title={s.label} style={{
                              width: pStep > i ? '7px' : pStep === i ? '7px' : '4px',
                              height: '4px', borderRadius: '2px',
                              background: pStep >= i ? s.color : '#e2e8f0',
                              opacity: pStep >= i ? 1 : 0.4,
                            }} />
                          ))}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                      <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', fontWeight: 500, background: `${st.color}10`, color: st.color }}>
                        {st.label}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); setCurrentProject(project.id); navigate(pipelineSteps[stepIdx].path); }}
                        style={{
                          padding: '3px 8px', background: stepColor, color: 'white',
                          border: 'none', borderRadius: '4px', cursor: 'pointer',
                          fontSize: '10px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '2px',
                        }}
                      >
                        进入 <ArrowRight size={9} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
