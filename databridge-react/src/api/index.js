const BASE = process.env.REACT_APP_API_URL || '';

async function request(url, options = {}) {
  const res = await fetch(BASE + url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Ошибка запроса');
  }
  return res.json();
}

export const api = {
  // Upload & consolidate
  analyzeFiles: (file1, file2, t1name = '', t2name = '') => {
    const fd = new FormData();
    fd.append('file1', file1);
    fd.append('file2', file2);
    fd.append('table1_name', t1name);
    fd.append('table2_name', t2name);
    return request('/api/consolidate/analyze', { method: 'POST', body: fd });
  },

  executeConsolidation: (table1, table2, joinColumn, joinType, resultName) =>
    request('/api/consolidate/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table1, table2, join_column: joinColumn, join_type: joinType, result_name: resultName }),
    }),

  uploadSingle: (file, tableName = '', sheet = '0') => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('table_name', tableName);
    fd.append('sheet', sheet);
    return request('/api/upload', { method: 'POST', body: fd });
  },

  connectDatabase: (dbType, host, port, database, username, password, connName = '') => {
    const fd = new FormData();
    fd.append('db_type', dbType);
    fd.append('host', host);
    fd.append('port', port);
    fd.append('database', database);
    fd.append('username', username);
    fd.append('password', password);
    fd.append('connection_name', connName);
    return request('/api/connect/database', { method: 'POST', body: fd });
  },

  // Data queries
  getTables: () => request('/api/tables'),
  getColumns: (table) => request(`/api/tables/${table}/columns`),
  queryTable: (table, limit = 1000) => request(`/api/query/${table}?limit=${limit}`),

  // Superset guest token
  getGuestToken: (dashboardId) =>
    request('/api/superset/guest-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dashboard_id: dashboardId }),
    }),

  getDashboards: () => request('/api/superset/dashboards'),
};
