import { useEffect, type ReactNode } from 'react';
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
  AlertCircle,
} from 'lucide-react';
import logoImg from '../../assets/logo.png';
import { useAppStore } from '../../stores/appStore';

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

const EXPANDED_WIDTH = 260;
const COLLAPSED_WIDTH = 64;

function Tooltip({ label, children, show }: { label: string; children: ReactNode; show: boolean }) {
  if (!show) return <>{children}</>;
  return (
    <div style={{ position: 'relative' }} className="sidebar-tooltip-wrapper">
      {children}
      <div
        className="sidebar-tooltip"
        style={{
          position: 'absolute',
          left: 'calc(100% + 8px)',
          top: '50%',
          transform: 'translateY(-50%)',
          background: '#0f172a',
          color: 'white',
          padding: '4px 10px',
          borderRadius: '6px',
          fontSize: '12px',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          opacity: 0,
          transition: 'opacity 0.15s',
          zIndex: 1000,
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        }}
      >
        {label}
      </div>
      <style>{`
        .sidebar-tooltip-wrapper:hover .sidebar-tooltip { opacity: 1 !important; }
      `}</style>
    </div>
  );
}

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const user = useAppStore((s) => s.user);

  const userRoleNames = (user?.roles || []).map(r => r.name);
  const isSystemAdmin = userRoleNames.includes('admin');
  const hasAnyRole = userRoleNames.length > 0;

  const visiblePipelineSteps = pipelineSteps.filter(step => {
    if (isSystemAdmin) return true;
    if (!hasAnyRole) return false;
    return true;
  });
  const visibleOtherNav = otherNavItems.filter(item => {
    if (isSystemAdmin) return true;
    if (item.path === '/settings') return userRoleNames.some(n => n === 'admin' || n === 'project_manager' || n === 'writer');
    if (item.path === '/news') return hasAnyRole;
    return hasAnyRole;
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b' && !e.altKey && !e.shiftKey) {
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName?.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return;
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleSidebar]);

  const getStepStatus = (stepPath: string, stepIndex: number): 'completed' | 'active' | 'upcoming' => {
    if (currentPath === stepPath) return 'active';
    const pipelinePaths = pipelineSteps.map(s => s.path);
    const currentIdx = pipelinePaths.indexOf(currentPath);
    if (currentIdx === -1) return 'upcoming';
    if (stepIndex < currentIdx) return 'completed';
    return 'upcoming';
  };

  const width = sidebarCollapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  return (
    <aside
      style={{
        width,
        minWidth: width,
        background: '#ffffff',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        color: '#1e293b',
        borderRight: '1px solid #e2e8f0',
        transition: 'width 0.25s ease, min-width 0.25s ease',
        position: 'relative',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: sidebarCollapsed ? '0' : '10px',
          cursor: 'pointer',
          justifyContent: 'center',
          minHeight: '64px',
          padding: sidebarCollapsed ? '14px 0' : '14px 20px',
          borderBottom: '1px solid #f1f5f9',
        }}
        onClick={() => navigate('/dashboard')}
        title="工作台"
      >
        <img
          src={logoImg}
          alt="BidMaster Pro"
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            objectFit: 'contain',
            flexShrink: 0,
          }}
        />
        {!sidebarCollapsed && (
          <div style={{ minWidth: 0, flex: 1 }}>
            <h1 style={{ fontSize: '15px', fontWeight: 700, color: '#0f172a', margin: 0, whiteSpace: 'nowrap' }}>
              BidMaster Pro
            </h1>
            <p style={{ fontSize: '10px', color: '#94a3b8', marginTop: '1px', whiteSpace: 'nowrap' }}>
              全流程智能招投标平台
            </p>
          </div>
        )}
      </div>

      <NavLink
        to="/dashboard"
        title="工作台"
        style={({ isActive }) => ({
          display: 'flex',
          alignItems: 'center',
          justifyContent: sidebarCollapsed ? 'center' : 'flex-start',
          gap: '10px',
          padding: sidebarCollapsed ? '10px 0' : '10px 20px',
          fontSize: '13px',
          color: isActive ? '#1a56db' : '#475569',
          background: isActive ? '#eff6ff' : 'transparent',
          textDecoration: 'none',
          borderLeft: isActive && !sidebarCollapsed ? '3px solid #1a56db' : '3px solid transparent',
          transition: 'all 0.15s ease',
          fontWeight: isActive ? 600 : 400,
        })}
      >
        <LayoutDashboard size={17} />
        {!sidebarCollapsed && <span>工作台</span>}
      </NavLink>

      {!sidebarCollapsed && (
        <div style={{ padding: '12px 20px 6px' }}>
          <div style={{ fontSize: '10px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            投标工作流
          </div>
        </div>
      )}

      {!hasAnyRole && !isSystemAdmin && (
        <div style={{
          margin: sidebarCollapsed ? '12px 8px' : '8px 16px',
          padding: sidebarCollapsed ? '8px 0' : '10px 12px',
          background: '#fef2f2',
          border: '1px solid #fecaca',
          borderRadius: '8px',
          textAlign: sidebarCollapsed ? 'center' : 'left',
        }}>
          <div style={{ display: 'flex', alignItems: sidebarCollapsed ? 'center' : 'flex-start', justifyContent: sidebarCollapsed ? 'center' : 'flex-start', gap: sidebarCollapsed ? '0' : '6px', flexDirection: sidebarCollapsed ? 'column' : 'row' }}>
            <AlertCircle size={sidebarCollapsed ? 14 : 14} color="#dc2626" />
            {!sidebarCollapsed && (
              <div style={{ fontSize: '11px', color: '#991b1b', lineHeight: 1.5 }}>
                <div style={{ fontWeight: 600 }}>尚未分配角色</div>
                <div style={{ marginTop: '2px', color: '#7f1d1d' }}>请管理员为您分配角色</div>
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ padding: sidebarCollapsed ? '0' : '0 20px', position: 'relative' }}>
        {visiblePipelineSteps.map((step, idx) => {
          const status = getStepStatus(step.path, idx);
          const isLast = idx === visiblePipelineSteps.length - 1;

          const node = (
            <div key={step.path} style={{ position: 'relative' }}>
              {!isLast && (
                <div
                  className={status === 'completed' || status === 'active' ? 'sidebar-flow-line' : undefined}
                  style={{
                    position: 'absolute',
                    left: sidebarCollapsed ? '15px' : '15px',
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
                title={sidebarCollapsed ? `${step.label} - ${step.desc}` : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: sidebarCollapsed ? 'center' : 'flex-start',
                  gap: '12px',
                  padding: sidebarCollapsed ? '8px 0' : '8px 0',
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

                {!sidebarCollapsed && (
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
                )}

                {!sidebarCollapsed && status === 'active' && (
                  <ChevronRight size={14} color={step.color} style={{ marginTop: '6px', flexShrink: 0 }} />
                )}
              </NavLink>
            </div>
          );

          return sidebarCollapsed ? <Tooltip key={step.path} label={`${step.label} - ${step.desc}`} show>{node}</Tooltip> : node;
        })}
      </div>

      {!sidebarCollapsed && (
        <div style={{ padding: '14px 20px 6px', marginTop: '6px', borderTop: '1px solid #f1f5f9' }}>
          <div style={{ fontSize: '10px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            资讯与管理
          </div>
        </div>
      )}

      {visibleOtherNav.map((item) => {
        const node = (
          <NavLink
            key={item.path}
            to={item.path}
            title={sidebarCollapsed ? `${item.label} - ${item.desc}` : undefined}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              flexDirection: sidebarCollapsed ? 'column' : 'row',
              justifyContent: sidebarCollapsed ? 'center' : 'flex-start',
              gap: sidebarCollapsed ? '0' : '10px',
              padding: sidebarCollapsed ? '10px 0' : '9px 20px',
              fontSize: '13px',
              color: isActive ? '#1a56db' : '#475569',
              background: isActive ? '#eff6ff' : 'transparent',
              textDecoration: 'none',
              borderLeft: isActive && !sidebarCollapsed ? '3px solid #1a56db' : '3px solid transparent',
              transition: 'all 0.15s ease',
              fontWeight: isActive ? 600 : 400,
            })}
          >
            <item.icon size={17} />
            {!sidebarCollapsed && (
              <div>
                <div>{item.label}</div>
                <div style={{ fontSize: '10px', color: '#94a3b8' }}>{item.desc}</div>
              </div>
            )}
          </NavLink>
        );
        return sidebarCollapsed ? <Tooltip key={item.path} label={`${item.label} - ${item.desc}`} show>{node}</Tooltip> : node;
      })}

      <div style={{ flex: 1 }} />

      {!sidebarCollapsed && (
        <div style={{
          padding: '14px 20px',
          borderTop: '1px solid #f1f5f9',
          fontSize: '10px',
          color: '#cbd5e1',
          textAlign: 'center',
        }}>
          BidMaster Pro v2.0
        </div>
      )}

      {sidebarCollapsed && (
        <div style={{
          padding: '10px 0',
          borderTop: '1px solid #f1f5f9',
          display: 'flex',
          justifyContent: 'center',
        }}>
          <span style={{ fontSize: '9px', color: '#cbd5e1' }}>v2.0</span>
        </div>
      )}
    </aside>
  );
}
