import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Project } from '../services/api';

interface AppState {
  currentProjectId: string | null;
  projects: Project[];
  sidebarCollapsed: boolean;
  setCurrentProject: (id: string | null) => void;
  setProjects: (projects: Project[]) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentProjectId: null,
      projects: [],
      sidebarCollapsed: false,
      setCurrentProject: (id) => set({ currentProjectId: id }),
      setProjects: (projects) => set({ projects }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    }),
    {
      name: 'bidmaster-app-store',
      partialize: (state) => ({
        currentProjectId: state.currentProjectId,
        sidebarCollapsed: state.sidebarCollapsed,
      }),
    }
  )
);
