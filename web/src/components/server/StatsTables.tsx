export default function StatsTables({ nodes, t }: any) {
  return (
    <table className="dt-table">
      <thead><tr><th>{t('node', 'Node')}</th><th>{t('status', 'Status')}</th><th>{t('latency', 'Latency')}</th></tr></thead>
      <tbody>{nodes.map((n: any) => <tr key={n.id || n.name} data-testid={`node-row-${n.name}`}><td><span className="dt-cell-main">{n.name}</span></td><td>{n.status ? 'online' : 'offline'}</td><td>{n.latency_ms ?? '—'}</td></tr>)}</tbody>
    </table>
  );
}
