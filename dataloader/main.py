from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import psycopg2
import requests
import io
import os
import re
import sqlparse
from sqlparse.sql import Values

app = FastAPI(title="DataBridge API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "pguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "pgpassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "sales_db")
SUPERSET_URL = os.getenv("SUPERSET_URL", "http://superset:8088")
SUPERSET_USER = os.getenv("SUPERSET_USER", "admin")
SUPERSET_PASSWORD = os.getenv("SUPERSET_PASSWORD", "admin")

TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z',
    'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh',
    'Щ':'Sch','Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya',
}

def transliterate(t): return ''.join(TRANSLIT.get(c, c) for c in t)

def clean_name(name):
    n = transliterate(str(name))
    n = re.sub(r'[^a-zA-Z0-9_]', '_', n)
    n = re.sub(r'_+', '_', n).strip('_').lower()
    if not n or n[0].isdigit(): n = 'col_' + n
    return n or 'column'

def clean_columns(columns):
    result, seen = [], {}
    for col in columns:
        c = clean_name(col)
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 0
        result.append(c)
    return result

def clean_table_name(filename):
    n = clean_name(os.path.splitext(filename)[0])
    return n[:50] or 'table'

def get_engine():
    from sqlalchemy import create_engine
    return create_engine(
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

def df_to_postgres(df, table_name):
    """
    Загружает DataFrame в PostgreSQL.
    Если таблица уже используется во VIEW — сначала удаляем зависимые VIEW,
    затем пересоздаём таблицу, затем восстанавливаем VIEW.
    """
    engine = get_engine()
    conn = pg_connect()
    try:
        cur = conn.cursor()

        # Находим все VIEW которые зависят от этой таблицы
        cur.execute("""
            SELECT DISTINCT v.table_name
            FROM information_schema.view_column_usage v
            WHERE v.table_name != %s
              AND v.view_name IN (
                SELECT table_name FROM information_schema.views
                WHERE table_schema = 'public'
              )
              AND v.table_name = %s
        """, (table_name, table_name))

        # Правильный запрос — ищем VIEW которые ссылаются на нашу таблицу
        cur.execute("""
            SELECT table_name, view_definition
            FROM information_schema.views
            WHERE table_schema = 'public'
              AND view_definition ILIKE %s
        """, (f'%"{table_name}"%',))
        dependent_views = cur.fetchall()

        # Дропаем зависимые VIEW
        for view_name, view_def in dependent_views:
            cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')

        conn.commit()
    finally:
        conn.close()

    # Теперь безопасно перезаписываем таблицу
    df.to_sql(table_name, engine, if_exists='replace', index=False, method='multi', chunksize=500)
    engine.dispose()

    # Восстанавливаем VIEW
    if dependent_views:
        conn2 = pg_connect()
        try:
            cur2 = conn2.cursor()
            for view_name, view_def in dependent_views:
                cur2.execute(f'CREATE OR REPLACE VIEW "{view_name}" AS {view_def}')
            conn2.commit()
        finally:
            conn2.close()

def read_uploaded(content, filename, sheet=0):
    if filename.endswith('.csv'):
        try: return pd.read_csv(io.BytesIO(content), encoding='utf-8')
        except UnicodeDecodeError: return pd.read_csv(io.BytesIO(content), encoding='cp1251')
    elif filename.endswith(('.xlsx', '.xls')):
        try: sheet = int(sheet)
        except: pass
        return pd.read_excel(io.BytesIO(content), sheet_name=sheet)
    elif filename.endswith('.sql'):
        return read_sql_file(content)
    raise HTTPException(400, f"Неподдерживаемый формат: {filename}")

def _unquote(s: str) -> str:
    """Strip surrounding quotes (single, double, backtick) from a token."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ('"', "'", '`') and s[-1] == s[0]:
        return s[1:-1]
    return s

def _parse_value_token(token: str):
    """Convert a raw SQL token string to a Python value."""
    t = token.strip()
    if t.upper() in ('NULL', 'DEFAULT'):
        return None
    # Boolean literals
    if t.upper() == 'TRUE':
        return True
    if t.upper() == 'FALSE':
        return False
    # Quoted string
    if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
        return t[1:-1].replace("''", "'").replace("\\'", "'")
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return t[1:-1].replace('""', '"')
    # Numeric
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t  # fallback: return as-is

def _split_values_list(s: str) -> list:
    """
    Split a comma-separated VALUES list respecting parentheses and quotes.
    Input example: "1, 'hello', NULL, (1+2)"
    Returns list of raw token strings.
    """
    tokens = []
    depth = 0
    current = []
    in_single = False
    in_double = False
    i = 0
    while i < len(s):
        ch = s[i]
        # Toggle quote states (simple – doesn't handle escaped quotes perfectly but good enough)
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if not in_single and not in_double:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ',' and depth == 0:
                tokens.append(''.join(current).strip())
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    if current:
        tokens.append(''.join(current).strip())
    return tokens

def _extract_row_groups(values_clause: str) -> list[str]:
    """
    Extract individual (…) row groups from a VALUES clause string.
    Handles multi-row inserts like: (1,'a'), (2,'b'), …
    """
    groups = []
    depth = 0
    start = None
    in_single = False
    in_double = False
    for i, ch in enumerate(values_clause):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if in_single or in_double:
            continue
        if ch == '(' and depth == 0:
            depth = 1
            start = i + 1
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(values_clause[start:i])
                start = None
    return groups

def read_sql_file(content: bytes) -> dict[str, pd.DataFrame]:
    """
    Parse a SQL dump file and return a dict of {table_name: DataFrame}.

    Handles:
    - CREATE TABLE statements (for column names)
    - INSERT INTO … VALUES … (single and multi-row)
    - MySQL-style backtick quoting
    - Standard double-quote and single-quote identifiers
    - Comments (-- and /* */)
    - Encoding: UTF-8 with cp1251 fallback
    """
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        text = content.decode('cp1251')

    # Strip block comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Strip line comments
    text = re.sub(r'--[^\n]*', '', text)

    # ── 1. Parse CREATE TABLE for column names ──────────────────────────
    table_columns: dict[str, list[str]] = {}

    # Pattern: CREATE TABLE [IF NOT EXISTS] `name` | "name" | name ( … )
    create_pattern = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
        r'([`"\[]?[\w\u0400-\u04FF]+[`"\]]?)'   # table name (ASCII + Cyrillic)
        r'\s*\((.*?)\)\s*(?:ENGINE|DEFAULT|;|$)',
        re.IGNORECASE | re.DOTALL,
    )

    for m in create_pattern.finditer(text):
        tname = clean_name(_unquote(m.group(1)))
        body = m.group(2)
        cols = []
        for line in body.split('\n'):
            line = line.strip().rstrip(',')
            if not line:
                continue
            # Skip constraints / indexes
            upper = line.upper()
            if any(upper.startswith(kw) for kw in (
                'PRIMARY', 'UNIQUE', 'KEY', 'INDEX', 'CONSTRAINT',
                'FOREIGN', 'CHECK', 'FULLTEXT', 'SPATIAL',
            )):
                continue
            # First token is the column name
            col_match = re.match(r'^([`"\[]?[\w\u0400-\u04FF]+[`"\]]?)', line)
            if col_match:
                cols.append(clean_name(_unquote(col_match.group(1))))
        if cols:
            table_columns[tname] = cols

    # ── 2. Parse INSERT statements ──────────────────────────────────────
    table_rows: dict[str, list] = {}
    table_explicit_cols: dict[str, list[str]] = {}

    # Regex to capture: INSERT INTO <table> [( col_list )] VALUES ...;
    insert_pattern = re.compile(
        r'INSERT\s+INTO\s+([`"\[]?[\w\u0400-\u04FF]+[`"\]]?)'
        r'(?:\s*\(([^)]+)\))?\s*VALUES\s*(.*?)(?=;|\Z)',
        re.IGNORECASE | re.DOTALL,
    )

    for m in insert_pattern.finditer(text):
        tname = clean_name(_unquote(m.group(1)))
        explicit_cols_raw = m.group(2)
        values_str = m.group(3).strip()

        # Explicit column list
        if explicit_cols_raw:
            ecols = [clean_name(_unquote(c.strip())) for c in explicit_cols_raw.split(',')]
            table_explicit_cols.setdefault(tname, ecols)

        # Extract all row groups (…)
        row_groups = _extract_row_groups(values_str)
        if tname not in table_rows:
            table_rows[tname] = []

        for group in row_groups:
            raw_tokens = _split_values_list(group)
            row = [_parse_value_token(t) for t in raw_tokens]
            table_rows[tname].append(row)

    # ── 3. Build DataFrames ─────────────────────────────────────────────
    if not table_rows:
        raise HTTPException(400, "SQL-файл не содержит INSERT-данных. Убедитесь, что файл является дампом с INSERT INTO … VALUES …")

    result: dict[str, pd.DataFrame] = {}

    for tname, rows in table_rows.items():
        # Determine columns: explicit > CREATE TABLE > auto-generated
        if tname in table_explicit_cols:
            cols = table_explicit_cols[tname]
        elif tname in table_columns:
            cols = table_columns[tname]
        else:
            # Auto-generate col_1, col_2, …
            max_len = max(len(r) for r in rows)
            cols = [f'col_{i+1}' for i in range(max_len)]

        # Pad / trim rows to match column count
        ncols = len(cols)
        padded = []
        for row in rows:
            if len(row) < ncols:
                row = row + [None] * (ncols - len(row))
            elif len(row) > ncols:
                row = row[:ncols]
            padded.append(row)

        df = pd.DataFrame(padded, columns=cols)
        result[tname] = df

    return result

def pg_connect():
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD
    )

def superset_token():
    r = requests.post(f"{SUPERSET_URL}/api/v1/security/login",
        json={"username": SUPERSET_USER, "password": SUPERSET_PASSWORD, "provider": "db"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def superset_db_id(token):
    r = requests.get(f"{SUPERSET_URL}/api/v1/database/",
        headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    for db in r.json().get("result", []):
        if "postgresql" in db.get("sqlalchemy_uri","") or "trino" in db.get("sqlalchemy_uri",""):
            return db["id"]
    raise HTTPException(404, "Не найдено подключение PostgreSQL/Trino в Superset")

def register_in_superset(token, table_name):
    db_id = superset_db_id(token)
    r = requests.post(f"{SUPERSET_URL}/api/v1/dataset/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"database": db_id, "schema": "public", "table_name": table_name}, timeout=15)
    if r.status_code not in (200, 201, 422): r.raise_for_status()

def get_table_columns(table_name):
    conn = pg_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position
    """, (table_name,))
    rows = cur.fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1]} for r in rows]

# ── API ───────────────────────────────────────────────

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    table_name: str = Form(default=""),
    sheet: str = Form(default="0"),
):
    content = await file.read()

    # SQL files may return multiple tables
    if file.filename.endswith('.sql'):
        dfs = read_sql_file(content)
        if not dfs:
            raise HTTPException(400, "SQL-файл не содержит данных")

        loaded = []
        for raw_tname, df in dfs.items():
            if df.empty:
                continue
            # If user provided a custom name and there's only one table, use it
            tname = (clean_name(table_name.strip()) or raw_tname)[:50] if len(dfs) == 1 and table_name.strip() else raw_tname
            df.columns = clean_columns(df.columns)
            df_to_postgres(df, tname)
            loaded.append({"table": tname, "rows": len(df), "columns": list(df.columns)})

        return {
            "status": "ok",
            "sql_tables_loaded": len(loaded),
            "tables": loaded,
            # Keep backward-compat fields using first table
            "table": loaded[0]["table"],
            "rows": loaded[0]["rows"],
            "columns": loaded[0]["columns"],
        }

    df = read_uploaded(content, file.filename, sheet)
    if df.empty: raise HTTPException(400, "Файл пустой")
    tname = table_name.strip() or clean_table_name(file.filename)
    df.columns = clean_columns(df.columns)
    df_to_postgres(df, tname)
    return {"status": "ok", "table": tname, "rows": len(df), "columns": list(df.columns)}

@app.post("/api/consolidate/analyze")
async def analyze(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...),
    table1_name: str = Form(default=""),
    table2_name: str = Form(default=""),
    sheet1: str = Form(default="0"),
    sheet2: str = Form(default="0"),
):
    c1, c2 = await file1.read(), await file2.read()

    # ── Handle SQL files (may contain multiple tables; use first one) ──
    def load_file(content, filename, sheet, name_override):
        if filename.endswith('.sql'):
            dfs = read_sql_file(content)
            if not dfs:
                raise HTTPException(400, f"SQL-файл {filename} не содержит данных")
            # Load all tables from the SQL dump to postgres, return the first
            for raw_tname, df in dfs.items():
                if not df.empty:
                    tname = (clean_name(name_override.strip()) or raw_tname)[:50] if len(dfs) == 1 and name_override.strip() else raw_tname
                    df.columns = clean_columns(df.columns)
                    df_to_postgres(df, tname)
            first_name = list(dfs.keys())[0]
            first_df = dfs[first_name]
            first_df.columns = clean_columns(first_df.columns)
            tname_out = (clean_name(name_override.strip()) or first_name)[:50] if len(dfs) == 1 and name_override.strip() else first_name
            return first_df, tname_out
        else:
            df = read_uploaded(content, filename, sheet)
            tname = name_override.strip() or clean_table_name(filename)
            df.columns = clean_columns(df.columns)
            return df, tname

    df1, t1 = load_file(c1, file1.filename, sheet1, table1_name)
    df2, t2 = load_file(c2, file2.filename, sheet2, table2_name)

    if df1.empty or df2.empty: raise HTTPException(400, "Один из файлов пустой")
    if t1 == t2: t2 += "_2"

    df_to_postgres(df1, t1)
    df_to_postgres(df2, t2)

    common = sorted(set(df1.columns) & set(df2.columns))

    def score(col):
        if col in ('id','region','city','date','category','type','code'): return 0
        if any(k in col for k in ('id','key','code','region','city')): return 1
        return 2

    suggestions = sorted(common, key=score)

    return {
        "status": "ok",
        "table1": {"name": t1, "columns": list(df1.columns), "rows": len(df1)},
        "table2": {"name": t2, "columns": list(df2.columns), "rows": len(df2)},
        "common_columns": common,
        "suggested_join_column": suggestions[0] if suggestions else None,
        "join_suggestions": suggestions[:5],
    }

@app.post("/api/consolidate/execute")
async def execute(body: dict):
    table1 = body.get("table1")
    table2 = body.get("table2")
    join_column = body.get("join_column")
    join_type = body.get("join_type", "LEFT").upper()
    result_name = clean_name(body.get("result_name") or f"view_{table1}_{table2}")[:50]

    if not all([table1, table2, join_column]):
        raise HTTPException(400, "Нужны: table1, table2, join_column")

    cols1 = get_table_columns(table1)
    cols2 = get_table_columns(table2)
    col1_names = {c["name"] for c in cols1}

    select_parts = [f'    a."{c["name"]}"' for c in cols1]
    for c in cols2:
        if c["name"] == join_column: continue
        alias = f'b_{c["name"]}' if c["name"] in col1_names else c["name"]
        select_parts.append(f'    b."{c["name"]}" AS "{alias}"')

    view_sql = (
        f'CREATE OR REPLACE VIEW "{result_name}" AS\n'
        f'SELECT\n' + ',\n'.join(select_parts) + '\n'
        f'FROM "{table1}" a\n'
        f'{join_type} JOIN "{table2}" b ON a."{join_column}" = b."{join_column}";'
    )

    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(view_sql)
        conn.commit()
        cur.execute(f'SELECT COUNT(*) FROM "{result_name}"')
        row_count = cur.fetchone()[0]
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Ошибка VIEW: {e}")
    finally:
        conn.close()

    superset_ok = "недоступен"
    try:
        token = superset_token()
        register_in_superset(token, result_name)
        superset_ok = "зарегистрирован в Superset ✓"
    except Exception as e:
        superset_ok = f"VIEW создан, Superset: {e}"

    return {
        "status": "ok",
        "result_view": result_name,
        "rows": row_count,
        "join_type": join_type,
        "join_column": join_column,
        "sql": view_sql,
        "superset": superset_ok,
        "superset_url": f"{SUPERSET_URL}/tablemodelview/list/",
    }

@app.post("/api/connect/database")
async def connect_db(
    db_type: str = Form(...),
    host: str = Form(...),
    port: str = Form(...),
    database: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    connection_name: str = Form(default=""),
):
    if db_type not in ("postgresql", "mysql"):
        raise HTTPException(400, "Поддерживаются: postgresql, mysql")
    conn_name = clean_name(connection_name or f"{db_type}_{database}")[:50]
    if db_type == "postgresql":
        uri = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
    else:
        uri = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
    try:
        token = superset_token()
        r = requests.post(f"{SUPERSET_URL}/api/v1/database/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"database_name": conn_name, "sqlalchemy_uri": uri, "expose_in_sqllab": True}, timeout=15)
        status = "уже существует" if r.status_code == 422 else "добавлено в Superset ✓"
    except Exception as e:
        status = f"ошибка: {e}"
    return {"status": "ok", "connection_name": conn_name, "superset": status}

@app.get("/api/tables")
def list_tables():
    try:
        conn = pg_connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name,
                   pg_size_pretty(pg_total_relation_size(quote_ident(table_name))),
                   obj_description(quote_ident(table_name)::regclass, 'pg_class')
            FROM information_schema.tables
            WHERE table_schema='public' ORDER BY table_name
        """)
        rows = cur.fetchall()
        conn.close()
        return {"tables": [{"name": r[0], "size": r[1], "type": "view" if r[2] else "table"} for r in rows]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/tables/{table_name}/columns")
def columns(table_name: str):
    return {"columns": get_table_columns(table_name)}

@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

app.mount("/static", StaticFiles(directory="/app/static"), name="static")
