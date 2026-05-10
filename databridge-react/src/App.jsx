import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import UploadPage from './pages/UploadPage';
import ChartsPage from './pages/ChartsPage';
import SupersetPage from './pages/SupersetPage';
import './App.css';

export const AppContext = React.createContext(null);

export default function App() {
  const [consolidationResult, setConsolidationResult] = useState(null);

  return (
    <AppContext.Provider value={{ consolidationResult, setConsolidationResult }}>
      <BrowserRouter>
        <div className="app">
          <nav className="sidebar">
            <div className="sidebar-brand">
              <div className="brand-icon">⬡</div>
              <div>
                <div className="brand-name">DataBridge</div>
                <div className="brand-sub">v1.0</div>
              </div>
            </div>

            <div className="nav-section">
              <div className="nav-label">Данные</div>
              <NavLink to="/" className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}>
                <span className="nav-icon">⬆</span> Загрузка и консолидация
              </NavLink>
              <NavLink to="/charts" className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}>
                <span className="nav-icon">📊</span> Построить чарты
              </NavLink>
              <NavLink to="/superset" className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}>
                <span className="nav-icon">🗂</span> Дашборды Superset
              </NavLink>
            </div>

            {consolidationResult && (
              <div className="sidebar-status">
                <div className="status-dot" />
                <div>
                  <div className="status-title">Данные готовы</div>
                  <div className="status-sub">{consolidationResult.result_view}</div>
                  <div className="status-sub">{consolidationResult.rows?.toLocaleString()} строк</div>
                </div>
              </div>
            )}

            <div className="sidebar-footer">
              <a href="http://localhost:8088" target="_blank" rel="noreferrer" className="footer-link">
                ↗ Открыть Superset
              </a>
              <a href="http://localhost:8089" target="_blank" rel="noreferrer" className="footer-link">
                ↗ Открыть Airflow
              </a>
            </div>
          </nav>

          <main className="main-content">
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/charts" element={<ChartsPage />} />
              <Route path="/superset" element={<SupersetPage />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </AppContext.Provider>
  );
}
