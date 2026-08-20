/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useState, useContext, useEffect, useCallback, useRef } from 'react';

const THEME_KEY = 'ovmanager-theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [theme, setThemeState] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved;
    // First visit: follow the OS preference. Legacy "ultra" values are
    // intentionally discarded so the panel only exposes light/dark modes.
    return 'system';
  });

  const [transitioning, setTransitioning] = useState(false);
  const isInitialMount = useRef(true);

  // Apply on mount and whenever theme changes
  useEffect(() => {
    const root = document.documentElement;

    // Set the theme attribute
    if (theme === 'system') {
      const isLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
      root.dataset.theme = isLight ? 'light' : 'dark';
    } else {
      root.dataset.theme = theme;
    }

    // Add transition class for smooth theme switching (only on user toggle, not initial mount)
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

  // Listen for system theme changes when in 'system' mode
  useEffect(() => {
    if (theme !== 'system') return;
    const mediaQuery = window.matchMedia('(prefers-color-scheme: light)');
    const handler = (e) => {
      document.documentElement.dataset.theme = e.matches ? 'light' : 'dark';
    };
    mediaQuery.addEventListener?.('change', handler);
    return () => mediaQuery.removeEventListener?.('change', handler);
  }, [theme]);

  const setTheme = useCallback((next) => {
    const safeTheme = ['system', 'light', 'dark'].includes(next) ? next : 'system';
    if (safeTheme === theme) return;

    // Trigger transition class for smooth animation
    setTransitioning(true);
    document.documentElement.classList.add('theme-transition');

    setThemeState(safeTheme);
    localStorage.setItem(THEME_KEY, safeTheme);

    // Apply immediately for visual feedback
    if (safeTheme === 'system') {
      const isLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
      document.documentElement.dataset.theme = isLight ? 'light' : 'dark';
    } else {
      document.documentElement.dataset.theme = safeTheme;
    }

    // Allow transition to complete
    requestAnimationFrame(() => {
      setTimeout(() => {
        setTransitioning(false);
        document.documentElement.classList.remove('theme-transition');
      }, 300);
    });
  }, [theme]);

  // Three choices: system default, light, and dark.
  const cycleTheme = useCallback(() => {
    const cycle = ['system', 'light', 'dark'];
    const idx = cycle.indexOf(theme);
    const next = cycle[(idx + 1) % cycle.length];
    setTheme(next);
  }, [theme, setTheme]);

  // Keep every open tab in sync
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === THEME_KEY && e.newValue) {
        const next = ['system', 'light', 'dark'].includes(e.newValue) ? e.newValue : 'system';
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

export const useTheme = () => useContext(ThemeContext);