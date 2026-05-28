import { Outlet, Navigate } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { useAppStore } from '../../stores/appStore';

export default function AppLayout() {
  const token = useAppStore((s) => s.token);
  const hydrated = useAppStore((s) => s._hydrated);

  if (!hydrated) {
    const lsToken = localStorage.getItem('bidmaster_token');
    if (!lsToken) {
      return <Navigate to="/login" replace />;
    }
  } else if (!token) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--color-bg)' }}>
        <Header />
        <main style={{ flex: 1, overflow: 'auto', padding: '20px 24px', background: 'var(--color-bg)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
