import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * RouteProgress — slim top loading bar.
 * Shows on route changes and whenever `ovmanager:loading` is dispatched
 * (the dashboard refresh triggers it). Auto-hides after ~700ms.
 */
const RouteProgress = () => {
  const location = useLocation();
  const [active, setActive] = useState(false);
  const timer = useRef(null);

  const show = () => {
    setActive(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setActive(false), 700);
  };

  useEffect(() => {
    show();
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [location.pathname, location.search]);

  useEffect(() => {
    const onLoading = () => show();
    window.addEventListener('ovmanager:loading', onLoading);
    return () => window.removeEventListener('ovmanager:loading', onLoading);
  }, []);

  return <div className={`route-progress${active ? ' is-active' : ''}`} aria-hidden="true" />;
};

export default RouteProgress;
