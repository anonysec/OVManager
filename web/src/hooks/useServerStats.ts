import { useState, useEffect, useCallback } from 'react';
import apiClient from '../services/api';

export function useServerStats() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      const [n, m] = await Promise.all([apiClient.get('/nodes'), apiClient.get('/telemetry/metrics')]);
      setNodes(n.data?.nodes ?? n.data ?? []);
      setMetrics(m.data ?? null);
    } catch {
      setNodes([]);
      setMetrics(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); const id = setInterval(() => { if (!document.hidden) load(); }, 30000); return () => clearInterval(id); }, [load]);
  return { nodes, metrics, loading, refresh: load };
}
