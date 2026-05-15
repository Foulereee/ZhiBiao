import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  FileSearch,
  PenTool,
  ShieldCheck,
  FileText,
  Newspaper,
  Settings,
  ChevronRight,
} from 'lucide-react';
import logoImg from '../../assets/logo.png';

const pipelineSteps = [
  { path: '/interpret', icon: FileSearch, label: '招标解读', step: 1, desc: '上传招标文件，AI智能解读', color: '#3b82f6' },
  { path: '/generate', icon: PenTool, label: '投标生成', step: 2, desc: '大纲编辑，AI生成正文', color: '#059669' },
  { path: '/check', icon: ShieldCheck, label: '投标检查', step: 3, desc: '21项检查，全面审核', color: '#d97706' },
  { path: '/format', icon: FileText, label: '文档输出', step: 4, desc: '一键排版，模板配置', color: '#475569' },
];

const otherNavItems = [
  { path: '/news', icon: Newspaper, label: '资讯中心', desc: '今日热点/商机', color: '#3b82f6' },
  { path: '/settings', icon: Settings, label: '平台设置', desc: '模型/权限/技能', color: '#475569' },
];

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;

  const getStepStatus = (stepPath: string, stepIndex: number): 'completed' | 'active' | 'upcoming' => {
    if (currentPath === stepPath) return 'active';
    const pipelinePaths = pipelineSteps.map(s => s.path);
    const currentIdx = pipelinePaths.indexOf(currentPath);
    if (currentIdx === -1) return 'upcoming';
    if (stepIndex < currentIdx) return 'completed';
    return 'upcoming';
  };

  return (
    <aside
      style={{
        width: '260px',
        minWidth: '260px',
        background: '#ffffff',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'auto',
        color: '#1e293b',
        borderRight: '1px solid #e2e8f0',
      }}
    >
      <div
        style={{
          padding: '16px 20px 14px',
          borderBottom: '1px solid #f1f5f9',
        }}
      >
        <div
          onClick={() => navigate('/dashboard')}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}
        >
          <img
            src={logoImg}
            alt="BidMaster Pro"
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              objectFit: 'contain',
            }}
          />
          <div>
            <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
              BidMaster Pro
            </h1>
            <p style={{ fontSize: '10px', color: '#94a3b8', marginTop: '1px' }}>
              全流程智能招投标平台
            </p>
          </div>
        </div>
      </div>

      <NavLink
        to="/dashboard"
        style={({ isActive }) => ({
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '10px 20px',
          fontSize: '13px',
          color: isActive ? '#1a56db' : '#475569',
          background: isActive ? '#eff6ff' : 'transparent',
          textDecoration: 'none',
          borderLeft: isActive ? '3px solid #1a56db' : '3px solid transparent',
          transition: 'all 0.15s ease',
          fontWeight: isActive ? 600 : 400,
        })}
      >
        <LayoutDashboard size={17} />
        <span>工作台</span>
      </NavLink>

      <div style={{ padding: '12px 20px 6px' }}>
        <div style={{ fontSize: '10px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          投标工作流
        </div>
      </div>

      <div style={{ padding: '0 20px', position: 'relative' }}>
        {pipelineSteps.map((step, idx) => {
          const status = getStepStatus(step.path, idx);
          const isLast = idx === pipelineSteps.length - 1;

          return (
            <div key={step.path} style={{ position: 'relative' }}>
              {!isLast && (
                <div
                  className={status === 'completed' || status === 'active' ? 'sidebar-flow-line' : undefined}
                  style={{
                    position: 'absolute',
                    left: '15px',
                    top: '34px',
                    width: '2px',
                    height: 'calc(100% - 26px)',
                    background: status === 'completed' || status === 'active'
                      ? undefined
                      : '#e2e8f0',
                    borderRadius: '1px',
                  }}
                />
              )}

              <NavLink
                to={step.path}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '12px',
                  padding: '8px 0',
                  textDecoration: 'none',
                  color: 'inherit',
                }}
              >
                <div
                  className={status === 'active' ? 'sidebar-step-active' : undefined}
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    background: status === 'active'
                      ? `linear-gradient(135deg, ${step.color}, ${step.color}cc)`
                      : status === 'completed'
                      ? step.color
                      : '#f8fafc',
                    border: status === 'active'
                      ? `2px solid ${step.color}`
                      : status === 'completed'
                      ? `2px solid ${step.color}`
                      : '2px solid #e2e8f0',
                    transition: 'all 0.3s ease',
                    position: 'relative',
                    zIndex: 1,
                  }}
                >
                  {status === 'completed' ? (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  ) : (
                    <step.icon size={15} color={status === 'active' ? 'white' : '#94a3b8'} />
                  )}
                </div>

                <div style={{ flex: 1, paddingTop: '2px' }}>
                  <div style={{
                    fontSize: '13px',
                    fontWeight: status === 'active' ? 600 : 400,
                    color: status === 'active' ? '#0f172a' : status === 'completed' ? step.color : '#64748b',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}>
                    {step.label}
                    {status === 'active' && (
                      <span style={{
                        fontSize: '9px',
                        padding: '1px 5px',
                        borderRadius: '4px',
                        background: `${step.color}15`,
                        color: step.color,
                        fontWeight: 600,
                      }}>
                        当前
                      </span>
                    )}
                  </div>
                  <div style={{
                    fontSize: '10px',
                    color: '#94a3b8',
                    marginTop: '1px',
                  }}>
                    {step.desc}
                  </div>
                </div>

                {status === 'active' && (
                  <ChevronRight size={14} color={step.color} style={{ marginTop: '6px', flexShrink: 0 }} />
                )}
              </NavLink>
            </div>
          );
        })}
      </div>

      <div style={{ padding: '14px 20px 6px', marginTop: '6px', borderTop: '1px solid #f1f5f9' }}>
        <div style={{ fontSize: '10px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          资讯与管理
        </div>
      </div>

      {otherNavItems.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          style={({ isActive }) => ({
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '9px 20px',
            fontSize: '13px',
            color: isActive ? '#1a56db' : '#475569',
            background: isActive ? '#eff6ff' : 'transparent',
            textDecoration: 'none',
            borderLeft: isActive ? '3px solid #1a56db' : '3px solid transparent',
            transition: 'all 0.15s ease',
            fontWeight: isActive ? 600 : 400,
          })}
        >
          <item.icon size={17} />
          <div>
            <div>{item.label}</div>
            <div style={{ fontSize: '10px', color: '#94a3b8' }}>{item.desc}</div>
          </div>
        </NavLink>
      ))}

      <div style={{ flex: 1 }} />

      <div style={{
        padding: '14px 20px',
        borderTop: '1px solid #f1f5f9',
        fontSize: '10px',
        color: '#cbd5e1',
        textAlign: 'center',
      }}>
        BidMaster Pro v2.0
      </div>
    </aside>
  );
}
