import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Bell, User, ChevronRight, LayoutDashboard, X } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';

const pipelineMeta: Record<string, { label: string; step: number; color: string }> = {
  '/interpret': { label: '招标解读', step: 1, color: '#3b82f6' },
  '/generate': { label: '投标生成', step: 2, color: '#059669' },
  '/check': { label: '投标检查', step: 3, color: '#d97706' },
  '/format': { label: '文档输出', step: 4, color: '#475569' },
};

const allSteps = [
  { path: '/interpret', label: '解读', color: '#3b82f6' },
  { path: '/generate', label: '生成', color: '#059669' },
  { path: '/check', label: '检查', color: '#d97706' },
  { path: '/format', label: '输出', color: '#475569' },
];

export default function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentProjectId } = useAppStore();
  const currentPath = location.pathname;
  const meta = pipelineMeta[currentPath];
  const [showNotif, setShowNotif] = useState(false);

  return (
    <header
      style={{
        height: 'var(--header-height)',
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        position: 'relative',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}>
          <span
            onClick={() => navigate('/dashboard')}
            style={{ color: 'var(--color-text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <LayoutDashboard size={14} />
            工作台
          </span>
          {meta && (
            <>
              <ChevronRight size={12} color="#cbd5e1" />
              <span style={{ color: meta.color, fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: '18px', height: '18px', borderRadius: '50%',
                  background: meta.color, color: 'white', fontSize: '10px', fontWeight: 700,
                }}>
                  {meta.step}
                </span>
                {meta.label}
              </span>
            </>
          )}
          {currentPath === '/news' && (
            <>
              <ChevronRight size={12} color="#cbd5e1" />
              <span style={{ color: '#3b82f6', fontWeight: 600 }}>资讯中心</span>
            </>
          )}
          {currentPath === '/settings' && (
            <>
              <ChevronRight size={12} color="#cbd5e1" />
              <span style={{ color: '#475569', fontWeight: 600 }}>平台设置</span>
            </>
          )}
        </div>

        {meta && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '3px', marginLeft: '8px' }}>
            {allSteps.map((s, idx) => {
              const isCurrent = s.path === currentPath;
              const isPast = meta.step > (idx + 1);
              return (
                <div key={s.path} style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <div
                    onClick={() => navigate(s.path)}
                    style={{
                      width: isCurrent ? '24px' : '8px',
                      height: '8px',
                      borderRadius: '4px',
                      background: isCurrent ? s.color : isPast ? s.color : '#e2e8f0',
                      opacity: isCurrent ? 1 : isPast ? 0.7 : 0.5,
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                    }}
                    title={s.label}
                  />
                </div>
              );
            })}
          </div>
        )}

        {currentProjectId && (
          <div style={{
            fontSize: '11px', color: 'var(--color-text-secondary)',
            background: '#f1f5f9', padding: '2px 10px',
            borderRadius: '10px', border: '1px solid #e2e8f0',
          }}>
            项目: {currentProjectId.slice(0, 8)}...
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowNotif(!showNotif)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', position: 'relative',
            }}
          >
            <Bell size={18} />
            <div style={{
              position: 'absolute', top: '-2px', right: '-2px',
              width: '7px', height: '7px', borderRadius: '50%',
              background: '#ef4444', border: '1.5px solid white',
            }} />
          </button>
          {showNotif && (
            <div style={{
              position: 'absolute', top: '32px', right: '0',
              width: '280px', background: 'var(--color-surface)',
              borderRadius: '10px', border: '1px solid var(--color-border)',
              boxShadow: '0 8px 24px rgba(0,0,0,0.12)', zIndex: 100,
              overflow: 'hidden',
            }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 14px', borderBottom: '1px solid var(--color-border)',
              }}>
                <span style={{ fontSize: '13px', fontWeight: 600 }}>通知</span>
                <button onClick={() => setShowNotif(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8' }}>
                  <X size={14} />
                </button>
              </div>
              <div style={{ padding: '16px 14px', textAlign: 'center' }}>
                <Bell size={24} color="#cbd5e1" style={{ margin: '0 auto 8px' }} />
                <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>暂无新通知</p>
              </div>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}
          onClick={() => navigate('/settings')}
        >
          <div style={{
            width: '30px', height: '30px', borderRadius: '8px',
            background: 'var(--color-primary-light)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <User size={14} color="var(--color-primary)" />
          </div>
          <span style={{ fontSize: '13px', color: 'var(--color-text)', fontWeight: 500 }}>管理员</span>
        </div>
      </div>
    </header>
  );
}
