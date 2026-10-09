import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Project, LoginUser, AppConfig } from '../services/api';
import { DEFAULT_APP_CONFIG } from '../services/api';

interface AppState {
  currentProjectId: string | null;
  projects: Project[];
  sidebarCollapsed: boolean;
  user: LoginUser | null;
  token: string | null;
  // 品牌信息：固定取源码里的 DEFAULT_APP_CONFIG，既不从服务端拉取，也不写进 localStorage。
  // 见下方 partialize / merge。
  appConfig: AppConfig;
  _hydrated: boolean;
  setCurrentProject: (id: string | null) => void;
  setProjects: (projects: Project[]) => void;
  toggleSidebar: () => void;
  setUser: (user: LoginUser | null) => void;
  setToken: (token: string | null) => void;
  setAppConfig: (config: AppConfig) => void;
  setHydrated: () => void;
  logout: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentProjectId: null,
      projects: [],
      sidebarCollapsed: false,
      user: null,
      token: null,
      appConfig: DEFAULT_APP_CONFIG,
      _hydrated: false,
      setCurrentProject: (id) => set({ currentProjectId: id }),
      setProjects: (projects) => set({ projects }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setUser: (user) => set({ user }),
      setToken: (token) => set({ token }),
      setAppConfig: (config) => set({ appConfig: config }),
      setHydrated: () => set({ _hydrated: true }),
      logout: () => {
        localStorage.removeItem('bidmaster_token');
        localStorage.removeItem('bidmaster_user');
        set({ user: null, token: null, currentProjectId: null, projects: [] });
      },
    }),
    {
      name: 'bidmaster-app-store',
      // 品牌信息不进 localStorage：界面永远用代码里的 DEFAULT_APP_CONFIG
      partialize: (state) => ({
        currentProjectId: state.currentProjectId,
        sidebarCollapsed: state.sidebarCollapsed,
        token: state.token,
        user: state.user,
      }),
      // 老版本（运行时拉品牌的那版）可能在 localStorage 里存了旧品牌名，
      // 回放时直接丢掉 appConfig 字段，保证旧值不会泄漏到界面。
      merge: (persisted, current) => {
        const saved = { ...((persisted || {}) as Partial<AppState>) };
        delete saved.appConfig;
        return { ...current, ...saved };
      },
      onRehydrateStorage: () => {
        return (_state, error) => {
          if (!error) {
            useAppStore.getState().setHydrated();
          }
        };
      },
    }
  )
);
