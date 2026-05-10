import React, { useState, useContext, useEffect } from 'react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { AppContext } from '../App';
import { api } from '../api';

const COLORS = ['#4361ee', '#2dd4a0', '#f5a623', '#f04438', '#7b8cde', '#a78bfa', '#34d399', '#fb923c'];

const CHART_TYPES = [
  { id: 'bar',     icon: '📊', label: 'Bar Chart',  hint: 'Сравнение' },
  { id: 'line',    icon: '📈', label: 'Line Chart', hint: 'Динамика' },
  { id: 'pie',     icon: '🥧', label: 'Pie Chart',  hint: 'Доли' },
  { id: 'scatter', icon: '🔵', label: 'Scatter',    hint: 'Корреляция' },
  { id: 'table',   icon: '📋', label: 'Таблица',    hint: 'Все данные' },
];

export default function ChartsPage() {
  const { consolidationResult } = useContext(AppContext);

  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [columns, setColumns] = useState([]);
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  const [chartType, setChartType] = useState('bar');
  const [xCol, setXCol] = useState('');
  const [yCol, setYCol] = useState('');
  const [groupCol, setGroupCol] = useState('');

  // Load tables list on mount
  useEffect(() => {
    api.getTables().then(d => {
      setTables(d.tables || []);
      // Auto-select consolidated table if exists
      if (consolidationResult?.result_view) {
        setSelectedTable(consolidationResult.result_view);
      }
    }).catch(() => {});
  }, [consolidationResult]);

  // Load columns when table changes
  useEffect(() => {
    if (!selectedTable) return;
    setLoading(true);
    Promise.all([
      api.getColumns(selectedTable),
      api.queryTable(selectedTable, 500),
    ]).then(([colsData, rowsData]) => {
      const cols = colsData.columns || [];
      setColumns(cols);
      setData(rowsData.rows || []);
      // Auto-pick columns
      const numCols = cols.filter(c => ['integer','numeric','double precision','bigint','real','decimal'].includes(c.type));
      const strCols = cols.filter(c => !['integer','numeric','double precision','bigint','real','decimal'].includes(c.type));
      if (strCols.length) setXCol(strCols[0].name);
      if (numCols.length) setYCol(numCols[0].name);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [selectedTable]);

  const numericCols = columns.filter(c =>
    ['integer','numeric','double precision','bigint','real','decimal','float'].some(t => c.type?.includes(t))
  );
  const allCols = columns;

  function renderChart() {
    if (!data.length || !xCol || !yCol) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 360, color: 'var(--text3)', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 32 }}>📊</div>
          <div style={{ fontSize: 13 }}>Выберите таблицу и колонки</div>
        </div>
      );
    }

    const tickStyle = { fill: 'var(--text2)', fontSize: 10, fontFamily: 'var(--mono)' };
    const gridStyle = { stroke: 'var(--border)', strokeDasharray: '3 3' };

    if (chartType === 'bar') return (
      <ResponsiveContainer width="100%" height={380}>
        <BarChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 60 }}>
          <CartesianGrid {...gridStyle} />
          <XAxis dataKey={xCol} tick={{ ...tickStyle, angle: -35, textAnchor: 'end' }} interval={0} />
          <YAxis tick={tickStyle} />
          <Tooltip contentStyle={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey={yCol} fill={COLORS[0]} radius={[4, 4, 0, 0]} />
          {groupCol && <Bar dataKey={groupCol} fill={COLORS[1]} radius={[4, 4, 0, 0]} />}
        </BarChart>
      </ResponsiveContainer>
    );

    if (chartType === 'line') return (
      <ResponsiveContainer width="100%" height={380}>
        <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 60 }}>
          <CartesianGrid {...gridStyle} />
          <XAxis dataKey={xCol} tick={{ ...tickStyle, angle: -35, textAnchor: 'end' }} interval={0} />
          <YAxis tick={tickStyle} />
          <Tooltip contentStyle={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line type="monotone" dataKey={yCol} stroke={COLORS[0]} strokeWidth={2} dot={{ r: 3 }} />
          {groupCol && <Line type="monotone" dataKey={groupCol} stroke={COLORS[1]} strokeWidth={2} dot={{ r: 3 }} />}
        </LineChart>
      </ResponsiveContainer>
    );

    if (chartType === 'pie') {
      const agg = {};
      data.forEach(row => {
        const key = row[xCol] ?? 'N/A';
        agg[key] = (agg[key] || 0) + (parseFloat(row[yCol]) || 0);
      });
      const pieData = Object.entries(agg).map(([name, value]) => ({ name, value: +value.toFixed(2) }));
      return (
        <ResponsiveContainer width="100%" height={380}>
          <PieChart>
            <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={140} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              labelLine={false}>
              {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </PieChart>
        </ResponsiveContainer>
      );
    }

    if (chartType === 'scatter') return (
      <ResponsiveContainer width="100%" height={380}>
        <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
          <CartesianGrid {...gridStyle} />
          <XAxis dataKey={xCol} name={xCol} tick={tickStyle} />
          <YAxis dataKey={yCol} name={yCol} tick={tickStyle} />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} contentStyle={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }} />
          <Scatter data={data} fill={COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    );

    if (chartType === 'table') return (
      <div className="data-table-wrap" style={{ maxHeight: 400 }}>
        <table className="data-table">
          <thead>
            <tr>{columns.map(c => <th key={c.name}>{c.name}</th>)}</tr>
          </thead>
          <tbody>
            {data.slice(0, 200).map((row, i) => (
              <tr key={i}>{columns.map(c => <td key={c.name}>{row[c.name] ?? '—'}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {data.length > 200 && <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 10px', fontFamily: 'var(--mono)' }}>показано 200 из {data.length} строк</div>}
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Построение чартов</div>
        <div className="page-sub">Выберите таблицу, тип чарта и колонки — визуализация обновится мгновенно</div>
      </div>

      <div className="chart-builder">
        {/* Left panel: controls */}
        <div className="chart-controls">

          {/* Table selector */}
          <div className="card">
            <div className="card-title">Источник данных</div>
            <div className="field">
              <label>Таблица / VIEW</label>
              <select value={selectedTable} onChange={e => setSelectedTable(e.target.value)}>
                <option value="">— выберите —</option>
                {tables.map(t => (
                  <option key={t.name} value={t.name}>
                    {t.name === consolidationResult?.result_view ? '⭐ ' : ''}{t.name}
                  </option>
                ))}
              </select>
            </div>
            {selectedTable && (
              <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
                {data.length} строк · {columns.length} колонок
              </div>
            )}
          </div>

          {/* Chart type */}
          <div className="card">
            <div className="card-title">Тип чарта</div>
            <div className="chart-type-grid">
              {CHART_TYPES.map(ct => (
                <button key={ct.id} className={`chart-type-btn ${chartType === ct.id ? 'active' : ''}`} onClick={() => setChartType(ct.id)}>
                  <div className="chart-type-icon">{ct.icon}</div>
                  <div style={{ fontSize: 10, fontWeight: 700 }}>{ct.label}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{ct.hint}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Column selectors */}
          {chartType !== 'table' && (
            <div className="card">
              <div className="card-title">Колонки</div>
              <div className="field" style={{ marginBottom: 10 }}>
                <label>{chartType === 'scatter' ? 'Ось X' : 'Категория (X)'}</label>
                <select value={xCol} onChange={e => setXCol(e.target.value)}>
                  <option value="">— выберите —</option>
                  {allCols.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
              </div>
              <div className="field" style={{ marginBottom: 10 }}>
                <label>{chartType === 'scatter' ? 'Ось Y' : 'Значение (Y)'}</label>
                <select value={yCol} onChange={e => setYCol(e.target.value)}>
                  <option value="">— выберите —</option>
                  {(chartType === 'scatter' ? allCols : numericCols.length ? numericCols : allCols).map(c => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              </div>
              {['bar', 'line'].includes(chartType) && (
                <div className="field">
                  <label>Доп. серия (необязательно)</label>
                  <select value={groupCol} onChange={e => setGroupCol(e.target.value)}>
                    <option value="">— нет —</option>
                    {numericCols.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: chart */}
        <div className="chart-area">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 380 }}>
              <span className="spinner" style={{ width: 24, height: 24, borderWidth: 3 }} />
            </div>
          ) : (
            <>
              {selectedTable && (
                <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text2)' }}>
                    {selectedTable}
                  </span>
                  {xCol && yCol && (
                    <span className="chip green">{xCol} × {yCol}</span>
                  )}
                </div>
              )}
              {renderChart()}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
