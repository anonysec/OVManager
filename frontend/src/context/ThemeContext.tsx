/* eslint-disable react-refresh/only-export-components */
import { createContext, useState, useContext, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';

const THEME_KEY = 'ovmanager-theme';

type Theme = 'system' | 'light' | 'dark';

type ThemeContextValue = {
  theme: Theme;
  setTheme: (next: string) => void;
  cycleTheme: () => void;
  toggleTheme: () => void;
  transitioning: boolean;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export const ThemeProvider = ({ children }: { children: ReactNode }) => {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved;
    // First visit follows the OS preference. Legacy "ultra" values are
    // discarded so the panel only exposes light/dark modes.
    return 'system';
  });

  const [transitioning, setTransitioning] = useState(false);
  const isInitialMount = useRef(true);

  useEffect(() => {
    const root = document.documentElement;

    if (theme === 'system') {
      const isLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
      root.dataset.theme = isLight ? 'light' : 'dark';
    } else {
      root.dataset.theme = theme;
    }

    // Smooth switch on user toggle only, never on initial mount.
    if (!isInitialMount.current) {
      root.classList.add('theme-transition');
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          root.classList.remove('theme-transition');
        });
      });
    }
    isInitialMount.current = false;
  }, [theme]);

  useEffect(() => {
    if (theme !== 'system') return;
    const mediaQuery = window.matchMedia('(prefers-color-scheme: light)');
    const handler = (e: MediaQueryListEvent) => {
      document.documentElement.dataset.theme = e.matches ? 'light' : 'dark';
    };
    mediaQuery.addEventListener?.('change', handler);
    return () => mediaQuery.removeEventListener?.('change', handler);
  }, [theme]);

  const setTheme = useCallback((next: string) => {
    const safeTheme: Theme = (['system', 'light', 'dark'] as string[]).includes(next) ? (next as Theme) : 'system';
    if (safeTheme === theme) return;

    setTransitioning(true);
    document.documentElement.classList.add('theme-transition');

    setThemeState(safeTheme);
    localStorage.setItem(THEME_KEY, safeTheme);

    if (safeTheme === 'system') {
      const isLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
      document.documentElement.dataset.theme = isLight ? 'light' : 'dark';
    } else {
      document.documentElement.dataset.theme = safeTheme;
    }

    requestAnimationFrame(() => {
      setTimeout(() => {
        setTransitioning(false);
        document.documentElement.classList.remove('theme-transition');
      }, 300);
    });
  }, [theme]);

  const cycleTheme = useCallback(() => {
    const cycle = ['system', 'light', 'dark'];
    const idx = cycle.indexOf(theme);
    const next = cycle[(idx + 1) % cycle.length];
    setTheme(next);
  }, [theme, setTheme]);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === THEME_KEY && e.newValue) {
        const raw = e.newValue;
        const next: Theme = raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
        if (next === theme) return;
        setThemeState(next);
        if (next === 'system') {
          const isLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
          document.documentElement.dataset.theme = isLight ? 'light' : 'dark';
        } else {
          document.documentElement.dataset.theme = next;
        }
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, cycleTheme, toggleTheme: cycleTheme, transitioning }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
};