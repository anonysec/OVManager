export default function StatsCharts({ metrics, t }: any) {
  const cpu = metrics?.cpu_usage ?? 0;
  const mem = metrics?.memory_usage ?? 0;
  return (
    <div className="stats-charts">
      <div className="stats-chart"><span>{t('cpuUsage', 'CPU')}</span><div className="dt-usage-bar"><i style={{ width: `${cpu}%` }} /></div><span>{cpu}%</span></div>
      <div className="stats-chart"><span>{t('memoryUsage', 'Memory')}</span><div className="dt-usage-bar"><i style={{ width: `${mem}%` }} /></div><span>{mem}%</span></div>
    </div>
  );
}
