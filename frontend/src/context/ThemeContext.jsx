/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useState, useContext, useEffect, useCallback, useRef } from 'react';

const THEME_KEY = 'ovmanager-theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [theme, setThemeState] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    // First visit: follow the OS preference.
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });

  const [transitioning, setTransitioning] = useState(false);
  const isInitialMount = useRef(true);

  // Apply on mount and whenever theme changes.
  useEffect(() => {
    const root = document.documentElement;
    
    // Set the theme attribute
    root.dataset.theme = theme;
    
    // Add transition class for smooth theme switching (only on user toggle, not initial mount)
    if (!isInitialMount.current) {
      root.classList.add('theme-transition');
      
      // Force reflow for transition to work, then remove class
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          root.classList.remove('theme-transition');
        });
      });
    }
    
    isInitialMount.current = false;
  }, [theme]);

  const setTheme = useCallback((next) => {
    const value = next === 'light' ? 'light' : 'dark';
    if (value === theme) return;

    // Trigger transition class for smooth animation
    setTransitioning(true);
    document.documentElement.classList.add('theme-transition');

    setThemeState(value);
    document.documentElement.dataset.theme = value;
    localStorage.setItem(THEME_KEY, value);

    // Allow transition to complete
    requestAnimationFrame(() => {
      setTimeout(() => {
        setTransitioning(false);
        document.documentElement.classList.remove('theme-transition');
      }, 300);
    });
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  }, [theme, setTheme]);

  // Keep every open tab in sync (theme toggled in one tab updates the others).
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === THEME_KEY && e.newValue && e.newValue !== theme) {
        setThemeState(e.newValue);
        document.documentElement.dataset.theme = e.newValue;
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme, transitioning }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);