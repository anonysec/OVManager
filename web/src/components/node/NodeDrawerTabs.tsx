import { useState } from 'react';
import { useTranslation } from 'react-i18next';

export default function NodeDrawerTabs({ children }: any) {
  const { t } = useTranslation();
  const [tab, setTab] = useState('status');
  return (
    <div className="node-drawer-tabs">
      <div role="tablist" aria-label={t('nodeDetails', 'Node details')}>
        {['status', 'logs', 'sessions'].map((k) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'is-active' : ''} onClick={() => setTab(k)}>{t(`tab.${k}`, k)}</button>)}
      </div>
      <div role="tabpanel" data-testid={`node-tab-${tab}`}>{children}</div>
    </div>
  );
}
