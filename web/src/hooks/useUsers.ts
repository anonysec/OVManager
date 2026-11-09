import { useState, useEffect, useCallback } from 'react';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { useLive } from '../context/LiveContext';
import { useTranslation } from 'react-i18next';

export function useUsers(page: number, pageSize: number, search: string) {
  const [users, setUsers] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const { t } = useTranslation();
  const { subscribe } = useLive();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.get(`/users?page=${page}&page_size=${pageSize}${search ? `&search=${encodeURIComponent(search)}` : ''}`);
      const data = res?.data ?? {};
      setUsers(asList(data.users ?? data));
      setTotal(data.total ?? (data.users ? data.users.length : 0));
    } catch {
      setUsers([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const off = subscribe('tick', () => { load(); });
    return off;
  }, [load, subscribe]);

  return { users, total, loading, setUsers, setTotal, refresh: load, t };
}
