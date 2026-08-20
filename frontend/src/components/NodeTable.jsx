import { useState, useMemo } from 'react';
import { FiEdit3, FiRefreshCw, FiTrash2, FiDownloadCloud, FiEye, FiChevronDown } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import EmptyState from './ui/EmptyState';
import StatusBadge from './ui/StatusBadge';

function usageClass(value) {
  if (value === undefined || value === null) return '';
  if (value <= 50) return 'good';
  if (value <= 80) return 'warn';
  return 'bad';
}

const NodeTableSkeleton = () => {
  return (
    <div className="table-skeleton">
      <div className="skeleton-header">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="sk-line sk-header" style={{ width: i === 0 ? 200 : i <= 2 ? 160 : i === 3 ? 100 : 120 }} />
        ))}
      </div>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton-row">
          {[...Array(8)].map((_, j) => (
            <div key={j} className="sk-line" style={{ width: j === 0 ? 200 : j <= 2 ? 160 : j === 3 ? 100 : 120 }} />
          ))}
        </div>
      ))}
    </div>
  );
};

const COUNTRY_EMOJI = {
  DE: '🇩🇪', TR: '🇹🇷', FI: '🇫🇮', FR: '🇫🇷', NL: '🇳🇱', US: '🇺🇸', AE: '🇦🇪',
  RU: '🇷🇺', GB: '🇬🇧', CA: '🇨🇦', SG: '🇸🇬', JP: '🇯🇵', IR: '🇮🇷', SE: '🇸🇪',
  CH: '🇨🇭', IT: '🇮🇹', ES: '🇪🇸', PL: '🇵🇱', UA: '🇺🇦', AT: '🇦🇹', BE: '🇧🇪',
  DK: '🇩🇰', NO: '🇳🇴', CZ: '🇨🇿', PT: '🇵🇹', RO: '🇷🇴', GR: '🇬🇷', HU: '🇭🇺',
  IL: '🇮🇱', IN: '🇮🇳', HK: '🇭🇰', KR: '🇰🇷', BR: '🇧🇷', MX: '🇲🇽', AU: '🇦🇺',
  ZA: '🇿🇦', EG: '🇪🇬', KZ: '🇰🇿', GE: '🇬🇪', AZ: '🇦🇿', IQ: '🇮🇶', PK: '🇵🇰',
};

const countryName = (code) => {
  const names = { DE: 'Germany', TR: 'Turkey', FI: 'Finland', FR: 'France', NL: 'Netherlands', US: 'USA', AE: 'UAE', RU: 'Russia', GB: 'UK', CA: 'Canada', SG: 'Singapore', JP: 'Japan', IR: 'Iran', SE: 'Sweden', CH: 'Switzerland', IT: 'Italy', ES: 'Spain', PL: 'Poland', UA: 'Ukraine' };
  return names[code] || code || 'Other';
};

const certDaysLeft = (expiry) => {
  if (!expiry) return null;
  return Math.ceil((new Date(expiry) - new Date()) / 86400000);
};

const NodeTable = ({ nodes, isLoading, nodeInfo = {}, onDelete, onCheckStatus, onEdit, onDownloadAll, onView, density = 'comfortable', grouped = false }) => {
  const { t } = useTranslation();
  const [closedGroups, setClosedGroups] = useState(() => new Set());

  const groups = useMemo(() => {
    if (!grouped) return null;
    const map = {};
    nodes.forEach((n) => {
      const code = (n.country_code || '').toUpperCase() || '?';
      (map[code] = map[code] || []).push(n);
    });
    return Object.entries(map).sort((a, b) => countryName(a[0]).localeCompare(countryName(b[0])));
  }, [nodes, grouped]);

  if (isLoading) return <NodeTableSkeleton />;
  if (!nodes.length) return <EmptyState title={t('noNodes')} description={t('noNodesBody')} />;

  const Row = ({ node }) => {
    const info = nodeInfo[node.id] || {};
    const certDays = certDaysLeft(info.cert_expiry);
    const certTone = certDays === null ? null : certDays < 0 ? 'is-expired' : certDays <= 7 ? 'is-critical' : certDays <= 30 ? 'is-soon' : 'is-ok';
    return (
      <tr key={node.id}>
        <td className="node-name-cell">
          <div className="identity-cell">
            <span className="row-avatar node-avatar">{node.name.slice(0, 2).toUpperCase()}</span>
            <div><strong className="node-name-text">{node.name}</strong><small>#{node.id}</small></div>
          </div>
        </td>
        <td><span className="node-address">{node.address}:{node.port}</span></td>
        <td>{node.protocol}</td>
        <td>{node.ovpn_port}</td>
        <td>
          <StatusBadge status={node.status ? 'online' : 'offline'} label={node.status ? t('active') : t('inactive')} />
          {certTone && (
            <span className={`cert-chip ${certTone}`} title={t('certExpiryHint', 'TLS certificate expiry')}>
              ◈ {certDays < 0 ? t('certExpiredShort', 'expired') : `${certDays}d`}
            </span>
          )}
        </td>
        <td><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></td>
        <td><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></td>
        <td><div className="row-actions">
          <button className="icon-btn" title={t('view', 'View')} aria-label={`${t('view', 'View')} ${node.name}`} onClick={() => onView?.(node)}><FiEye /></button>
          <button className="icon-btn" title={t('check')} aria-label={`${t('check')} ${node.name}`} onClick={() => onCheckStatus(node.id)}><FiRefreshCw /></button>
          <button className="icon-btn" title={t('downloadAll')} aria-label={`${t('downloadAll')} ${node.name}`} onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /></button>
          <button className="icon-btn" title={t('edit')} aria-label={`${t('edit')} ${node.name}`} onClick={() => onEdit(node)}><FiEdit3 /></button>
          <button className="icon-btn danger" title={t('delete')} aria-label={`${t('delete')} ${node.name}`} onClick={() => onDelete(node.id, node.name)}><FiTrash2 /></button>
        </div></td>
      </tr>
    );
  };

  const table = (
    <table className="list-table node-list-table">
      <thead>
        <tr>
          <th>{t('th_node')}</th>
          <th>{t('th_address')}</th>
          <th>{t('th_protocol')}</th>
          <th>{t('th_ovpnPort')}</th>
          <th>{t('th_status')}</th>
          <th>{t('th_cpu')}</th>
          <th>{t('th_ram')}</th>
          <th>{t('th_actions')}</th>
        </tr>
      </thead>
      <tbody>
        {nodes.map((node) => <Row key={node.id} node={node} />)}
      </tbody>
    </table>
  );

  return (
    <div className={`table-container list-table-container${density === 'compact' ? ' table-compact' : ''}`}>
      {!groups ? table : (
        <div className="node-groups">
          {groups.map(([code, list]) => {
            const closed = closedGroups.has(code);
            const flag = COUNTRY_EMOJI[code] || '🌐';
            return (
              <section key={code} className="node-group">
                <button
                  type="button"
                  className={`node-group-head${closed ? '' : ' open'}`}
                  onClick={() => setClosedGroups((s) => {
                    const n = new Set(s);
                    if (n.has(code)) n.delete(code); else n.add(code);
                    return n;
                  })}
                  aria-expanded={!closed}
                >
                  <span className="flag">{flag}</span>
                  {countryName(code)}
                  <span className="count">{list.length}</span>
                  <FiChevronDown className="chev" aria-hidden="true" />
                </button>
                {!closed && (
                  <table className="list-table node-list-table">
                    <thead>
                      <tr>
                        <th>{t('th_node')}</th>
                        <th>{t('th_address')}</th>
                        <th>{t('th_protocol')}</th>
                        <th>{t('th_ovpnPort')}</th>
                        <th>{t('th_status')}</th>
                        <th>{t('th_cpu')}</th>
                        <th>{t('th_ram')}</th>
                        <th>{t('th_actions')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((node) => <Row key={node.id} node={node} />)}
                    </tbody>
                  </table>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default NodeTable;
