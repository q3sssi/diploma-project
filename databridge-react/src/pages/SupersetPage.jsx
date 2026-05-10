import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api';

const SUPERSET_URL = process.env.REACT_APP_SUPERSET_URL || 'http://localhost:8088';

export default function SupersetPage() {
  const [dashboards, setDashboards] = useState([]);
  const [selectedDashboard, setSelectedDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [embedLoading, setEmbedLoading] = useState(false);
  const [error, setError] = useState('');
  const embedRef = useRef(null);
  const mountedRef = useRef(null);

  useEffect(() => {
    setLoading(true);
    api.getDashboards()
      .then(d => setDashboards(d.dashboards || []))
      .catch(() => setDashboards([]))
      .finally(() => setLoading(false));
  }, []);

  async function embedDashboard(dashboard) {
    setSelectedDashboard(dashboard);
    setEmbedLoading(true);
    setError('');

    try {
      // Get guest token from FastAPI
      const tokenData = await api.getGuestToken(dashboard.id);

      // Dynamically import Superset SDK
      const { embedDashboard } = await import('@superset-ui/embedded-sdk');

      // Clear previous embed
      if (mountedRef.current) {
        mountedRef.current.innerHTML = '';
      }

      await embedDashboard({
        id: dashboard.uuid || dashboard.id,
        supersetDomain: SUPERSET_URL,
        mountPoint: mountedRef.current,
        fetchGuestToken: () => tokenData.token,
        dashboardUiConfig: {
          hideTitle: true,
          hideChartControls: false,
          hideTab: false,
          filters: { visible: true, expanded: false },
        },
      });
    } catch (e) {
      setError('Не удалось загрузить дашборд: ' + e.message +
        '. Убедитесь что в Superset включён Embedded Mode (FEATURE_FLAGS.EMBEDDED_SUPERSET = True)');
    } finally {
      setEmbedLoading(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Дашборды Superset</div>
        <div className="page-sub">Встроенные дашборды Superset — полная аналитика прямо в интерфейсе</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16 }}>
        {/* Dashboard list */}
        <div>
          <div className="card">
            <div className="card-title">Мои дашборды</div>

            {loading && (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <span className="spinner" style={{ width: 20, height: 20, borderWidth: 2, margin: 'auto' }} />
              </div>
            )}

            {!loading && dashboards.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'var(--mono)', lineHeight: 1.6 }}>
                Нет дашбордов.<br /><br />
                Создайте дашборд в Superset, затем вернитесь сюда.
                <br /><br />
                <a href={SUPERSET_URL + '/dashboard/list/'} target="_blank" rel="noreferrer"
                  style={{ color: 'var(--accent2)', textDecoration: 'none' }}>
                  → Открыть Superset
                </a>
              </div>
            )}

            {dashboards.map(d => (
              <div key={d.id}
                onClick={() => embedDashboard(d)}
                style={{
                  padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
                  marginBottom: 4, transition: 'all .15s',
                  background: selectedDashboard?.id === d.id ? 'rgba(67,97,238,.12)' : 'transparent',
                  border: selectedDashboard?.id === d.id ? '1px solid rgba(67,97,238,.3)' : '1px solid transparent',
                  color: selectedDashboard?.id === d.id ? 'var(--accent2)' : 'var(--text2)',
                  fontSize: 12, fontWeight: 500,
                }}
              >
                🗂 {d.title || d.dashboard_title || `Dashboard ${d.id}`}
                {d.published && (
                  <span style={{ marginLeft: 6, fontSize: 9, background: 'rgba(45,212,160,.15)', color: 'var(--green)', padding: '1px 5px', borderRadius: 3, fontFamily: 'var(--mono)' }}>
                    pub
                  </span>
                )}
              </div>
            ))}
          </div>

          {/* Quick actions */}
          <div className="card">
            <div className="card-title">Быстрые действия</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                ['/chart/list/', '📊 Создать чарт'],
                ['/dashboard/new/', '➕ Новый дашборд'],
                ['/tablemodelview/list/', '📋 Datasets'],
                ['/sqllab/', '💻 SQL Lab'],
              ].map(([path, label]) => (
                <a key={path}
                  href={SUPERSET_URL + path} target="_blank" rel="noreferrer"
                  style={{
                    display: 'block', padding: '8px 10px', borderRadius: 7,
                    background: 'var(--s2)', border: '1px solid var(--border)',
                    color: 'var(--text2)', textDecoration: 'none',
                    fontSize: 12, transition: 'all .15s',
                  }}
                  onMouseOver={e => e.currentTarget.style.borderColor = 'var(--accent2)'}
                  onMouseOut={e => e.currentTarget.style.borderColor = 'var(--border)'}
                >
                  {label}
                </a>
              ))}
            </div>
          </div>
        </div>

        {/* Embedded area */}
        <div>
          {!selectedDashboard ? (
            <div style={{
              background: 'var(--s1)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', height: 600,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 12,
            }}>
              <div style={{ fontSize: 48 }}>🗂</div>
              <div style={{ fontSize: 14, color: 'var(--text2)', fontWeight: 600 }}>Выберите дашборд слева</div>
              <div style={{ fontSize: 12, color: 'var(--text3)' }}>Он откроется прямо здесь без перехода в Superset</div>
            </div>
          ) : (
            <div className="superset-wrap">
              <div style={{
                padding: '12px 16px', background: 'var(--s2)',
                borderBottom: '1px solid var(--border)',
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>
                  {selectedDashboard.title || selectedDashboard.dashboard_title}
                </span>
                <span className="chip">Embedded Superset</span>
                {embedLoading && <span className="spinner" style={{ width: 14, height: 14 }} />}
                <a href={SUPERSET_URL + '/superset/dashboard/' + selectedDashboard.id + '/'}
                  target="_blank" rel="noreferrer"
                  style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--accent2)', textDecoration: 'none' }}>
                  ↗ Открыть полностью
                </a>
              </div>

              {error && (
                <div className="alert error" style={{ margin: 16 }}>{error}</div>
              )}

              <div
                ref={mountedRef}
                style={{ width: '100%', height: 560 }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
