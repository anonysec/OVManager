/**
 * WorldMap — node atlas.
 *
 * Loaded lazily by ServerStats. This module owns the only imports of d3-geo,
 * topojson-client and world-atlas (~105 kB of TopoJSON alone), which together
 * were over half of the dashboard chunk. Splitting them out means the KPI
 * cards, tables and security panel paint without waiting on map geometry the
 * user may never scroll to.
 */
import { useState, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FiGlobe, FiActivity } from 'react-icons/fi';
import { geoEquirectangular, geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import worldAtlas from 'world-atlas/countries-110m.json';
import { nodeMeta } from '../../utils/geo.js';
import FlagIcon from '../../utils/geo.jsx';
import { getPanelBase } from '../../utils/panelUrl';

const WorldMap = ({ nodes, nodeStatus }) => {
  const { t } = useTranslation();
  // Equirectangular, full world framed inside the viewBox (no top/bottom clipping).
  // Memoized: it only depends on constants, so markers re-project only when
  // nodes/nodeStatus actually change — not on every hover/tooltip re-render.
  const projection = useMemo(() => geoEquirectangular().scale(106).translate([334, 167]), []);
  const pathGen = useMemo(() => geoPath(projection), [projection]);
  const land = useMemo(() => feature(worldAtlas, worldAtlas.objects.countries), []);
  const borders = useMemo(() => mesh(worldAtlas, worldAtlas.objects.countries, (a, b) => a !== b), []);
  const [hoverCountry, setHoverCountry] = useState(null);
  const [activeNode, setActiveNode] = useState(null);
  const [tooltip, setTooltip] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const viewportRef = useRef(null);
  const clamp = (z) => Math.max(1, Math.min(4, z));

  const markers = useMemo(() => nodes
    .map((node) => {
      const m = nodeMeta(node);
      const projected = m.coords ? projection(m.coords) : null;
      if (!projected) return null;
      const st = nodeStatus[node.id] || {};
      const online = node.status && (st.reachable === true || (st.reachable === undefined && st.session_diagnostics?.live_count != null && st.node_info !== undefined));
      return { node, meta: m, x: projected[0], y: projected[1], st, online };
    })
    .filter(Boolean), [nodes, nodeStatus, projection]);

  // Atlas summary strip
  const atlasStats = useMemo(() => {
    const countries = new Set(markers.map((mk) => mk.meta.flagCode).filter(Boolean));
    const online = markers.filter((mk) => mk.online).length;
    const latencies = markers.map((mk) => Number(mk.st?.latency_ms)).filter(Number.isFinite);
    const avg = latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : 0;
    return { countries: countries.size, online, total: markers.length, avgLatency: avg };
  }, [markers]);

  // Drag-to-pan: the viewport is scrollable when zoomed in. Dragging state is
  // a useState (not a ref) so the cursor style updates on the same render.
  const [dragging, setDragging] = useState(false);
  const dragStartRef = useRef(null);
  const onPointerDown = (e) => {
    dragStartRef.current = { x: e.clientX, y: e.clientY, sl: viewportRef.current?.scrollLeft || 0, st: viewportRef.current?.scrollTop || 0 };
    setDragging(true);
  };
  const onPointerMove = (e) => {
    const vp = viewportRef.current;
    const start = dragStartRef.current;
    if (!vp || !start) return;
    if (Math.abs(e.clientX - start.x) + Math.abs(e.clientY - start.y) < 3) return;
    vp.scrollLeft = start.sl - (e.clientX - start.x);
    vp.scrollTop = start.st - (e.clientY - start.y);
    e.preventDefault();
  };
  const stopDrag = () => { dragStartRef.current = null; setDragging(false); };

  // Wheel zoom around the cursor. React attaches `wheel` as a passive listener
  // at the root (so preventDefault() is ignored), therefore we bind a native
  // listener with { passive: false } to stop the page from scrolling while the
  // map zooms.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const onWheel = (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const next = clamp(zoom * factor);
      if (next === zoom) return;
      // Keep the point under the cursor fixed while scaling the canvas.
      const rect = vp.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const ratio = next / zoom;
      const newScrollLeft = (vp.scrollLeft + px) * ratio - px;
      const newScrollTop = (vp.scrollTop + py) * ratio - py;
      setZoom(next);
      requestAnimationFrame(() => {
        vp.scrollLeft = newScrollLeft;
        vp.scrollTop = newScrollTop;
      });
    };
    vp.addEventListener('wheel', onWheel, { passive: false });
    return () => vp.removeEventListener('wheel', onWheel);
  }, [zoom]);

  const handleNodeHover = (mk, e) => {
    const rect = viewportRef.current?.getBoundingClientRect();
    setActiveNode(mk);
    // Position relative to the map wrap (which shares the viewport's origin),
    // so the tooltip follows the cursor on screen regardless of pan/zoom.
    setTooltip({
      x: (e.clientX - (rect?.left || 0)) + 14,
      y: (e.clientY - (rect?.top || 0)) - 8,
    });
  };

  const navToNode = (id) => {
    window.location.assign(`${getPanelBase()}/nodes?node=${id}`);
  };

  return (
    <div className="atlas-wrap">
      {/* Summary strip */}
      <div className="atlas-stats">
        <span className="atlas-stat">
          <i className="atlas-dot atlas-dot--online" aria-hidden="true" />
          <strong>{atlasStats.online}</strong>
          <em>{t('statusOnline', 'Online')}</em>
        </span>
        <span className="atlas-stat">
          <i className="atlas-dot atlas-dot--offline" aria-hidden="true" />
          <strong>{atlasStats.total - atlasStats.online}</strong>
          <em>{t('statusOffline', 'Offline')}</em>
        </span>
        <span className="atlas-stat">
          <FiGlobe aria-hidden="true" />
          <strong>{atlasStats.countries}</strong>
          <em>{t('mapCountries', 'Countries')}</em>
        </span>
        <span className="atlas-stat">
          <FiActivity aria-hidden="true" />
          <strong>{atlasStats.avgLatency ? `${Math.round(atlasStats.avgLatency)}ms` : '—'}</strong>
          <em>{t('avgLatency', 'Avg latency')}</em>
        </span>
      </div>

      <div className="map-zoom-wrap">
        <div className="map-zoom-controls" role="group" aria-label="Map zoom controls">
          <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z + 0.25))} aria-label="Zoom in">+
          </button>
          <span className="map-zoom-level" aria-live="polite">{zoom.toFixed(2)}×</span>
          <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z - 0.25))} aria-label="Zoom out">−
          </button>
          {zoom !== 1 && <button type="button" className="map-zoom-btn map-zoom-reset" onClick={() => setZoom(1)} aria-label="Reset zoom">⤢
          </button>}
        </div>

        <div
          className="map-zoom-viewport"
          ref={viewportRef}
          style={{ overflow: zoom > 1 ? 'auto' : 'hidden', cursor: dragging ? 'grabbing' : zoom > 1 ? 'grab' : 'default' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={stopDrag}
          onPointerLeave={stopDrag}
        >
          <div className="map-zoom-canvas" style={{ width: `${100 * zoom}%`, minWidth: '100%' }}>
            <svg className="world-map-real" viewBox="0 0 668 334" preserveAspectRatio="xMidYMid meet"
              style={{ width: '100%', height: 'auto' }}
              role="img" aria-label="World map of node locations"
              onMouseLeave={() => { setHoverCountry(null); setActiveNode(null); }}>
              <defs>
                <radialGradient id="sphereGrad" cx="50%" cy="38%" r="65%">
                  <stop offset="0%" stopColor="#13314a" />
                  <stop offset="60%" stopColor="#0c2236" />
                  <stop offset="100%" stopColor="#081320" />
                </radialGradient>
              </defs>
              <path className="sphere" d={pathGen({ type: 'Sphere' }) || ''} />
              {land.features.map((feat) => (
                <path
                  key={feat.id || feat.properties.name}
                  className="country"
                  d={pathGen(feat) || ''}
                  onMouseOver={() => setHoverCountry(feat.properties.name)}
                  tabIndex={-1}
                  aria-label={feat.properties.name}
                >
                  <title>{feat.properties.name}</title>
                </path>
              ))}
              <path className="country-borders" d={pathGen(borders) || ''} />
              {hoverCountry && (() => {
                const c = pathGen.centroid(land.features.find((f) => f.properties.name === hoverCountry)) || [300, 150];
                return <text x={c[0]} y={c[1]} className="country-label">{hoverCountry}</text>;
              })()}
              {markers.map((mk) => (
                <g
                  key={mk.node.id}
                  className={`map-marker${mk.online ? '' : ' map-marker--offline'}${activeNode?.node.id === mk.node.id ? ' map-marker--active' : ''}`}
                  transform={`translate(${mk.x},${mk.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${mk.node.name} — ${mk.online ? 'online' : 'offline'}`}
                  onMouseMove={(e) => handleNodeHover(mk, e)}
                  onMouseLeave={() => setActiveNode(null)}
                  onClick={() => navToNode(mk.node.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navToNode(mk.node.id); } }}
                >
                  {mk.online && <circle className="pulse" r={6} aria-hidden="true" />}
                  <circle r={mk.online ? 5 : 3.5} className={mk.online ? 'node-online' : 'node-offline'} aria-hidden="true" />
                  <text x={7} y={4} className="node-country-label">{mk.node.name}{mk.meta.approximate ? ' · approx.' : ''}</text>
                </g>
              ))}
            </svg>
          </div>
        </div>

        {/* Hover tooltip */}
        {activeNode && (
          <div
            className="atlas-tooltip"
            style={{ left: tooltip.x, top: tooltip.y }}
            role="tooltip"
          >
            <div className="atlas-tooltip-title">
              <span className={`atlas-tooltip-dot ${activeNode.online ? 'online' : 'offline'}`} aria-hidden="true" />
              <strong>{activeNode.node.name}</strong>
            </div>
            <div className="atlas-tooltip-row">
              <span>{activeNode.meta.flagCode ? `${activeNode.meta.flagCode} · ` : ''}{activeNode.meta.name}</span>
              <b>{activeNode.online ? t('statusOnline', 'Online') : t('statusOffline', 'Offline')}</b>
            </div>
            <div className="atlas-tooltip-grid">
              <span>{t('th_conns', 'Conns')}<b>{Number(activeNode.st?.session_diagnostics?.live_count || 0)}</b></span>
              <span>{t('th_cpu', 'CPU')}<b>{Number.isFinite(Number(activeNode.st?.node_info?.cpu_usage)) ? `${Number(activeNode.st?.node_info?.cpu_usage).toFixed(0)}%` : '—'}</b></span>
              <span>{t('avgLatency', 'Latency')}<b>{Number.isFinite(Number(activeNode.st?.latency_ms)) ? `${Math.round(Number(activeNode.st?.latency_ms))}ms` : '—'}</b></span>
            </div>
            <div className="atlas-tooltip-hint">{t('clickToManageNode', 'Click to manage node')}</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default WorldMap;
