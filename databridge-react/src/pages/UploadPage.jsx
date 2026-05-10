import React, { useState, useContext, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppContext } from '../App';
import { api } from '../api';

const STEPS = ['Источники данных', 'Настройка JOIN', 'Результат'];

export default function UploadPage() {
  const { setConsolidationResult } = useContext(AppContext);
  const navigate = useNavigate();

  const [step, setStep] = useState(0);
  const [mode, setMode] = useState('files'); // 'files' | 'db'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Files state
  const [file1, setFile1] = useState(null);
  const [file2, setFile2] = useState(null);
  const [t1name, setT1name] = useState('');
  const [t2name, setT2name] = useState('');

  // DB state
  const [dbType, setDbType] = useState('postgresql');
  const [dbHost, setDbHost] = useState('');
  const [dbPort, setDbPort] = useState('5432');
  const [dbName, setDbName] = useState('');
  const [dbUser, setDbUser] = useState('');
  const [dbPass, setDbPass] = useState('');
  const [dbConn, setDbConn] = useState('');

  // Analysis result
  const [analysis, setAnalysis] = useState(null);
  const [joinCol, setJoinCol] = useState('');
  const [joinType, setJoinType] = useState('LEFT');
  const [resultName, setResultName] = useState('');

  const f1ref = useRef(); const f2ref = useRef();

  function fmtSize(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(1) + ' MB';
  }

  async function handleAnalyze() {
    if (!file1 || !file2) { setError('Выберите оба файла'); return; }
    setLoading(true); setError('');
    try {
      const data = await api.analyzeFiles(file1, file2, t1name, t2name);
      setAnalysis(data);
      setJoinCol(data.suggested_join_column || data.common_columns[0] || '');
      setResultName(`consolidated_${data.table1.name}_${data.table2.name}`.slice(0, 50));
      setStep(1);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function handleConnectDB() {
    if (!dbHost || !dbPort || !dbName || !dbUser) { setError('Заполните все поля'); return; }
    setLoading(true); setError('');
    try {
      await api.connectDatabase(dbType, dbHost, dbPort, dbName, dbUser, dbPass, dbConn);
      setError(''); alert('Подключение добавлено в Superset! Перейдите на вкладку "Дашборды Superset"');
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function handleExecute() {
    if (!joinCol) { setError('Выберите колонку для JOIN'); return; }
    setLoading(true); setError('');
    try {
      const result = await api.executeConsolidation(
        analysis.table1.name, analysis.table2.name, joinCol, joinType, resultName
      );
      setConsolidationResult(result);
      setStep(2);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  function handleDrop(e, setter) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) setter(f);
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Загрузка и консолидация данных</div>
        <div className="page-sub">Загрузите два источника, выберите ключ объединения — система создаст единый набор данных</div>
      </div>

      {/* Steps */}
      <div className="steps">
        {STEPS.map((s, i) => (
          <div className="step" key={i}>
            <div className={`step-circle ${i < step ? 'done' : i === step ? 'active' : ''}`}>
              {i < step ? '✓' : i + 1}
            </div>
            <span className={`step-label ${i === step ? 'active' : ''}`}>{s}</span>
          </div>
        ))}
      </div>

      {/* ── STEP 0: Sources ── */}
      {step === 0 && (
        <>
          {/* Mode selector */}
          <div className="card" style={{ padding: '6px', marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              {[['files', '📄 Файлы CSV / Excel'], ['db', '🗄 Подключить БД']].map(([m, label]) => (
                <button key={m}
                  onClick={() => setMode(m)}
                  style={{
                    flex: 1, padding: '9px', border: 'none', borderRadius: 8,
                    background: mode === m ? 'var(--accent)' : 'transparent',
                    color: mode === m ? '#fff' : 'var(--text2)',
                    font: '600 13px var(--sans)', cursor: 'pointer', transition: 'all .15s'
                  }}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'files' ? (
            <div className="card">
              <div className="card-title">Загрузите два файла <span className="chip">Шаг 1 из 3</span></div>

              <div className="drop-grid">
                {[
                  { label: 'Первый источник', file: file1, setter: setFile1, ref: f1ref, num: '1' },
                  { label: 'Второй источник', file: file2, setter: setFile2, ref: f2ref, num: '2' },
                ].map(({ label, file, setter, ref, num }) => (
                  <div
                    key={num}
                    className={`drop-zone ${file ? 'loaded' : ''}`}
                    onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }}
                    onDragLeave={e => e.currentTarget.classList.remove('drag-over')}
                    onDrop={e => { e.currentTarget.classList.remove('drag-over'); handleDrop(e, setter); }}
                  >
                    <div className="drop-num">{num}</div>
                    <input
                      ref={ref} type="file" accept=".csv,.xlsx,.xls"
                      onChange={e => setter(e.target.files[0])}
                    />
                    <div className="drop-icon">{file ? '✅' : '📄'}</div>
                    <div className="drop-label">{label}</div>
                    {file
                      ? <div className="drop-file">{file.name} ({fmtSize(file.size)})</div>
                      : <div className="drop-hint">CSV, XLSX, XLS</div>
                    }
                  </div>
                ))}
              </div>

              <div className="form-row">
                <div className="field">
                  <label>Название таблицы 1 (необязательно)</label>
                  <input value={t1name} onChange={e => setT1name(e.target.value)} placeholder="по умолчанию — имя файла" />
                </div>
                <div className="field">
                  <label>Название таблицы 2 (необязательно)</label>
                  <input value={t2name} onChange={e => setT2name(e.target.value)} placeholder="по умолчанию — имя файла" />
                </div>
              </div>

              {error && <div className="alert error">{error}</div>}

              <button
                className="btn btn-primary btn-full" style={{ marginTop: 8 }}
                onClick={handleAnalyze} disabled={loading || !file1 || !file2}
              >
                {loading ? <span className="spinner" /> : '🔍'}
                {loading ? 'Анализируем...' : 'Загрузить и найти общие колонки'}
              </button>
            </div>
          ) : (
            <div className="card">
              <div className="card-title">Подключить внешнюю БД <span className="chip">PostgreSQL / MySQL</span></div>
              <div className="form-row">
                <div className="field">
                  <label>Тип БД</label>
                  <select value={dbType} onChange={e => { setDbType(e.target.value); setDbPort(e.target.value === 'postgresql' ? '5432' : '3306'); }}>
                    <option value="postgresql">PostgreSQL</option>
                    <option value="mysql">MySQL</option>
                  </select>
                </div>
                <div className="field">
                  <label>Название подключения</label>
                  <input value={dbConn} onChange={e => setDbConn(e.target.value)} placeholder="my_database" />
                </div>
              </div>
              <div className="form-row triple">
                <div className="field">
                  <label>Хост</label>
                  <input value={dbHost} onChange={e => setDbHost(e.target.value)} placeholder="localhost" />
                </div>
                <div className="field">
                  <label>Порт</label>
                  <input value={dbPort} onChange={e => setDbPort(e.target.value)} />
                </div>
                <div className="field">
                  <label>База данных</label>
                  <input value={dbName} onChange={e => setDbName(e.target.value)} placeholder="mydb" />
                </div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Пользователь</label>
                  <input value={dbUser} onChange={e => setDbUser(e.target.value)} />
                </div>
                <div className="field">
                  <label>Пароль</label>
                  <input type="password" value={dbPass} onChange={e => setDbPass(e.target.value)} />
                </div>
              </div>
              {error && <div className="alert error">{error}</div>}
              <button className="btn btn-primary btn-full" style={{ marginTop: 8 }} onClick={handleConnectDB} disabled={loading}>
                {loading ? <span className="spinner" /> : '🔌'}
                {loading ? 'Подключаем...' : 'Подключить и добавить в Superset'}
              </button>
            </div>
          )}
        </>
      )}

      {/* ── STEP 1: JOIN config ── */}
      {step === 1 && analysis && (
        <div className="card">
          <div className="card-title">
            Настройка объединения <span className="chip">Шаг 2 из 3</span>
            <button className="btn btn-ghost" style={{ marginLeft: 'auto', padding: '4px 12px', fontSize: 11 }} onClick={() => setStep(0)}>← Назад</button>
          </div>

          {/* Tables info */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 40px 1fr', gap: 12, marginBottom: 16, alignItems: 'center' }}>
            <div style={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text2)', marginBottom: 8 }}>
                📄 {analysis.table1.name} · {analysis.table1.rows} строк
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {analysis.table1.columns.map(c => (
                  <span key={c} style={{
                    padding: '2px 7px', borderRadius: 4, fontSize: 10, fontFamily: 'var(--mono)',
                    background: analysis.common_columns.includes(c) ? 'rgba(67,97,238,.2)' : 'var(--s3)',
                    color: analysis.common_columns.includes(c) ? 'var(--accent2)' : 'var(--text3)',
                    border: analysis.common_columns.includes(c) ? '1px solid rgba(67,97,238,.3)' : '1px solid var(--border)',
                  }}>{c}</span>
                ))}
              </div>
            </div>

            <div style={{ textAlign: 'center', fontSize: 20, color: 'var(--text3)' }}>⟷</div>

            <div style={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text2)', marginBottom: 8 }}>
                📄 {analysis.table2.name} · {analysis.table2.rows} строк
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {analysis.table2.columns.map(c => (
                  <span key={c} style={{
                    padding: '2px 7px', borderRadius: 4, fontSize: 10, fontFamily: 'var(--mono)',
                    background: analysis.common_columns.includes(c) ? 'rgba(67,97,238,.2)' : 'var(--s3)',
                    color: analysis.common_columns.includes(c) ? 'var(--accent2)' : 'var(--text3)',
                    border: analysis.common_columns.includes(c) ? '1px solid rgba(67,97,238,.3)' : '1px solid var(--border)',
                  }}>{c}</span>
                ))}
              </div>
            </div>
          </div>

          {/* Common columns */}
          {analysis.common_columns.length > 0 ? (
            <>
              <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 8 }}>
                Общие колонки — выберите ключ для объединения:
              </div>
              <div className="common-cols">
                {analysis.common_columns.map(c => (
                  <span key={c}
                    className={`col-tag ${joinCol === c ? 'selected' : ''}`}
                    onClick={() => setJoinCol(c)}>
                    {c === analysis.suggested_join_column ? '✦ ' : ''}{c}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div className="alert info">Общих колонок не найдено. Выберите колонки вручную или используйте CROSS JOIN.</div>
          )}

          {/* JOIN type */}
          <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text3)', marginBottom: 8, marginTop: 14 }}>
            ТИП ОБЪЕДИНЕНИЯ
          </div>
          <div className="join-types">
            {[['LEFT', 'LEFT JOIN', 'все из таблицы 1'], ['INNER', 'INNER JOIN', 'только совпадения'], ['FULL OUTER', 'FULL JOIN', 'все записи']].map(([v, label, hint]) => (
              <button key={v} className={`join-btn ${joinType === v ? 'active' : ''}`} onClick={() => setJoinType(v)}>
                <div>{label}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{hint}</div>
              </button>
            ))}
          </div>

          {/* Result name */}
          <div className="form-row" style={{ marginTop: 4 }}>
            <div className="field">
              <label>Название результирующей таблицы</label>
              <input value={resultName} onChange={e => setResultName(e.target.value)} />
            </div>
          </div>

          {error && <div className="alert error">{error}</div>}

          <button className="btn btn-primary btn-full" style={{ marginTop: 8 }} onClick={handleExecute} disabled={loading}>
            {loading ? <span className="spinner" /> : '⚡'}
            {loading ? 'Консолидируем...' : 'Выполнить консолидацию'}
          </button>
        </div>
      )}

      {/* ── STEP 2: Result ── */}
      {step === 2 && (
        <div className="card">
          <div className="alert success" style={{ marginTop: 0, marginBottom: 16 }}>
            ✓ Консолидация выполнена успешно
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 20 }}>
            {[
              ['Строк в результате', analysis?.table1?.rows + analysis?.table2?.rows],
              ['Тип JOIN', joinType],
              ['Ключ объединения', joinCol],
            ].map(([label, val]) => (
              <div key={label} style={{ background: 'var(--s2)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'var(--mono)' }}>{val}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, textTransform: 'uppercase', letterSpacing: '.5px' }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => navigate('/charts')}>
              📊 Построить чарты
            </button>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => navigate('/superset')}>
              🗂 Открыть в Superset
            </button>
            <button className="btn btn-ghost" onClick={() => { setStep(0); setAnalysis(null); setFile1(null); setFile2(null); }}>
              + Новая консолидация
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
