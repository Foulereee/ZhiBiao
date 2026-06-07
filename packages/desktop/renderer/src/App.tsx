import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import DashboardPage from './pages/DashboardPage';
import InterpretPage from './pages/InterpretPage';
import GeneratePage from './pages/GeneratePage';
import CheckPage from './pages/CheckPage';
import FormatPage from './pages/FormatPage';
import NewsPage from './pages/NewsPage';
import SettingsPage from './pages/SettingsPage';
import LoginPage from './pages/LoginPage';
import { useAppStore } from './stores/appStore';

function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const token = useAppStore((s) => s.token);
  const hydrated = useAppStore((s) => s._hydrated);

  if (!hydrated) {
    const lsToken = localStorage.getItem('bidmaster_token');
    if (lsToken) {
      return <Navigate to="/dashboard" replace />;
    }
    return <>{children}</>;
  }

  if (token) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/interpret" element={<InterpretPage />} />
        <Route path="/generate" element={<GeneratePage />} />
        <Route path="/check" element={<CheckPage />} />
        <Route path="/format" element={<FormatPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
