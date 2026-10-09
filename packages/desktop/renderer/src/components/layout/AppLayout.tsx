import { useEffect, useState } from 'react';
import { Outlet, Navigate, useLocation } from 'react-router-dom';
import Sidebar, { useIsMobile } from './Sidebar';
import Header from './Header';
import { useAppStore } from '../../stores/appStore';
import { projectApi } from '../../services/api';

export default function AppLayout() {
  const token = useAppStore((s) => s.token);
  const hydrated = useAppStore((s) => s._hydrated);
  const setProjects = useAppStore((s) => s.setProjects);

  // 移动端导航抽屉：开关状态由布局持有，Header 的「打开菜单」负责打开，
  // Sidebar 的「关闭菜单」/ 遮罩 / 点导航项负责关闭（对应 9-20 版 AppLayout 的实现）。
  const isMobile = useIsMobile();
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    let aborted = false;
    projectApi.list()
      .then((res) => {
        if (aborted) return;
        const list = res.data?.projects || res.data || [];
        setProjects(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!aborted) setProjects([]);
      });
    return () => { aborted = true; };
  }, [setProjects]);

  if (!hydrated) {
    const lsToken = localStorage.getItem('bidmaster_token');
    if (!lsToken) {
      return <Navigate to="/login" replace />;
    }
  } else if (!token) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="bmp-shell" style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar mobileOpen={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />
      {isMobile && mobileNavOpen && (
        <div
          className="bmp-nav-backdrop"
          onClick={() => setMobileNavOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15,23,42,0.45)',
            zIndex: 65,
            backdropFilter: 'blur(1px)',
          }}
        />
      )}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--color-bg)' }}>
        <Header onOpenNav={() => setMobileNavOpen(true)} />
        <main style={{ flex: 1, overflow: 'auto', padding: '20px 24px', background: 'var(--color-bg)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
