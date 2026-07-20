import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';

const THEME_KEY = 'ovmanager-theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [theme, setThemeState] = useState(() => localStorage.getItem(THEME_KEY) || 'dark');

  // Apply on mount and whenever theme changes.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setTheme = useCallback((next) => {
    const value = next === 'light' ? 'light' : 'dark';
    setThemeState(value);
    document.documentElement.dataset.theme = value;
    localStorage.setItem(THEME_KEY, value);
  }, []);

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
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
