import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Project, LoginUser } from '../services/api';

interface AppState {
  currentProjectId: string | null;
  projects: Project[];
  sidebarCollapsed: boolean;
  user: LoginUser | null;
  token: string | null;
  _hydrated: boolean;
  setCurrentProject: (id: string | null) => void;
  setProjects: (projects: Project[]) => void;
  toggleSidebar: () => void;
  setUser: (user: LoginUser | null) => void;
  setToken: (token: string | null) => void;
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
      _hydrated: false,
      setCurrentProject: (id) => set({ currentProjectId: id }),
      setProjects: (projects) => set({ projects }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setUser: (user) => set({ user }),
      setToken: (token) => set({ token }),
      setHydrated: () => set({ _hydrated: true }),
      logout: () => {
        localStorage.removeItem('bidmaster_token');
        localStorage.removeItem('bidmaster_user');
        set({ user: null, token: null, currentProjectId: null, projects: [] });
      },
    }),
    {
      name: 'bidmaster-app-store',
      partialize: (state) => ({
        currentProjectId: state.currentProjectId,
        sidebarCollapsed: state.sidebarCollapsed,
        token: state.token,
        user: state.user,
      }),
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
