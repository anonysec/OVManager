import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiShield } from 'react-icons/fi';
import apiClient from '../../services/api';
import ErrorState from '../../components/ui/ErrorState';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import { useLive } from '../../context/LiveContext';

const SecurityTab = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [secHours, setSecHours] = useState(24);
  const [sec, setSec] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadSecurity = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await apiClient.get(`/security/summary?hours=${secHours}`);
      setSec(res.data?.data || null);
    } catch {
      setError(t('failedToLoad', 'Failed to load data'));
    } finally {
      setLoading(false);
    }
  }, [secHours, t]);

  useEffect(() => { loadSecurity(); }, [loadSecurity, refreshTick]);

  return (
    <div className="settings-section">
      {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={loadSecurity} />}
      {!error && (
        <div className="setting-card">
          <div className="setting-card-header"><FiShield /> {t('securityCard', 'Security Summary')}</div>
          <div className="setting-card-body">
            {loading ? (
              <PanelSkeleton lines={4} label={t('loading', 'Loading security summary')} />
            ) : (
              <>
                <div className="card-actions" style={{ marginBottom: 12 }}>
                  <label style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, alignSelf: 'center' }}>
                    {t('securityDesc', 'Hours')}:
                  </label>
                  {[4, 8, 12, 24, 48].map((h) => (
                    <button
                      key={h}
                      type="button"
                      className={`btn btn-sm ${secHours === h ? '' : 'btn-secondary'}`}
                      onClick={() => setSecHours(h)}
                      aria-pressed={secHours === h}
                    >
                      {h}h
                    </button>
                  ))}
                </div>
                {sec ? (
                  <>
                    <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                      <div className="metric-mini">
                        <div className="metric-label">{t('authErrors', 'Auth Errors')}</div>
                        <div className={`metric-value ${sec.auth_errors > 0 ? 'danger' : ''}`}>{sec.auth_errors || 0}</div>
                      </div>
                      <div className="metric-mini">
                        <div className="metric-label">{t('rejects', 'Rejects')}</div>
                        <div className={`metric-value ${sec.rejects > 0 ? 'danger' : ''}`}>{sec.rejects || 0}</div>
                      </div>
                      <div className="metric-mini">
                        <div className="metric-label">{t('staleMarkers', 'Stale')}</div>
                        <div className={`metric-value ${sec.stale_markers > 0 ? 'danger' : ''}`}>{sec.stale_markers || 0}</div>
                      </div>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
                      {t('securityDesc', 'Last')} {secHours} {t('hours', 'hours')}
                    </p>
                  </>
                ) : (
                  <p style={{ fontSize: 13, color: 'var(--muted)' }}>{t('noData', 'No security data available')}</p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SecurityTab;
