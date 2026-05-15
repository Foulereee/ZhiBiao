import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import DashboardPage from './pages/DashboardPage';
import InterpretPage from './pages/InterpretPage';
import GeneratePage from './pages/GeneratePage';
import CheckPage from './pages/CheckPage';
import FormatPage from './pages/FormatPage';
import NewsPage from './pages/NewsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <Routes>
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
