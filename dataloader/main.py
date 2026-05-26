from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import psycopg2
import requests
import io
import os
import re
import time

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
        # Ищем VIEW которые ссылаются на нашу таблицу
        cur.execute("""
            SELECT table_name, view_definition
            FROM information_schema.views
            WHERE table_schema = 'public'
              AND view_definition ILIKE %s
        """, (f'%"{table_name}"%',))
        dependent_views = cur.fetchall()

        for view_name, _ in dependent_views:
            cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')
        conn.commit()
    finally:
        conn.close()

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
    raise HTTPException(400, f"Неподдерживаемый формат: {filename}")

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
    databases = r.json().get("result", [])
    for db in databases:
        uri = db.get("sqlalchemy_uri", "") or ""
        name = db.get("database_name", "") or ""
        if "postgresql" in uri or "trino" in uri or "postgres" in name.lower():
            return db["id"]
    if len(databases) == 1:
        return databases[0]["id"]
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

def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ── Метаданные консолидации ───────────────────────────────────────────────────

def ensure_consolidation_log():
    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS consolidation_log (
                id                  SERIAL PRIMARY KEY,
                source_table_1      VARCHAR(100) NOT NULL,
                source_table_2      VARCHAR(100) NOT NULL,
                source_schema       VARCHAR(50)  NOT NULL DEFAULT 'public',
                join_column         VARCHAR(100) NOT NULL,
                join_type           VARCHAR(20)  NOT NULL,
                result_view         VARCHAR(100) NOT NULL,
                result_schema       VARCHAR(50)  NOT NULL DEFAULT 'public',
                row_count           INTEGER,
                columns_count       INTEGER,
                sql_text            TEXT,
                result_size_bytes   BIGINT,
                result_size_pretty  VARCHAR(20),
                duration_ms         INTEGER,
                source1_row_count   INTEGER,
                source2_row_count   INTEGER,
                matched_row_count   INTEGER,
                match_percent       NUMERIC(5,2),
                initiated_by_ip     VARCHAR(45),
                initiated_by_host   VARCHAR(255),
                status              VARCHAR(20)  NOT NULL DEFAULT 'success',
                error_message       TEXT,
                created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
                superset_status     VARCHAR(100),
                source1_filename    VARCHAR(255),
                source2_filename    VARCHAR(255)
            );
            CREATE INDEX IF NOT EXISTS idx_consolidation_log_created_at
                ON consolidation_log (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_consolidation_log_result_view
                ON consolidation_log (result_view);
            CREATE INDEX IF NOT EXISTS idx_consolidation_log_status
                ON consolidation_log (status);
        """)
        # Добавляем колонки если таблица уже существует без них
        for col, typedef in [
            ("source1_filename", "VARCHAR(255)"),
            ("source2_filename", "VARCHAR(255)"),
        ]:
            cur.execute(f"""
                ALTER TABLE consolidation_log
                ADD COLUMN IF NOT EXISTS {col} {typedef}
            """)
        conn.commit()
    finally:
        conn.close()


def collect_extended_meta(table1: str, table2: str, join_column: str) -> dict:
    meta = {
        "result_size_bytes": None,
        "result_size_pretty": None,
        "source1_row_count": None,
        "source2_row_count": None,
        "matched_row_count": None,
        "match_percent": None,
    }
    conn = pg_connect()
    try:
        cur = conn.cursor()

        # Суммарный размер исходных таблиц (VIEW физически не хранит данные)
        cur.execute("""
            SELECT pg_total_relation_size(quote_ident(%s)) + pg_total_relation_size(quote_ident(%s)),
                   pg_size_pretty(pg_total_relation_size(quote_ident(%s)) + pg_total_relation_size(quote_ident(%s)))
        """, (table1, table2, table1, table2))
        row = cur.fetchone()
        if row:
            meta["result_size_bytes"] = row[0]
            meta["result_size_pretty"] = row[1]

        cur.execute(f'SELECT COUNT(*) FROM "{table1}"')
        meta["source1_row_count"] = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(*) FROM "{table2}"')
        meta["source2_row_count"] = cur.fetchone()[0]

        cur.execute(f"""
            SELECT COUNT(*)
            FROM "{table1}" a
            INNER JOIN "{table2}" b ON a."{join_column}" = b."{join_column}"
        """)
        matched = cur.fetchone()[0]
        meta["matched_row_count"] = matched

        if meta["source1_row_count"] and meta["source1_row_count"] > 0:
            meta["match_percent"] = round(matched / meta["source1_row_count"] * 100, 2)

    except Exception:
        pass
    finally:
        conn.close()
    return meta


def write_consolidation_log(
    source_table_1: str,
    source_table_2: str,
    join_column: str,
    join_type: str,
    result_view: str,
    row_count,
    columns_count,
    sql_text: str,
    duration_ms: int = None,
    result_size_bytes: int = None,
    result_size_pretty: str = None,
    source1_row_count: int = None,
    source2_row_count: int = None,
    matched_row_count: int = None,
    match_percent=None,
    initiated_by_ip: str = None,
    initiated_by_host: str = None,
    status: str = "success",
    error_message: str = None,
    superset_status: str = None,
    source1_filename: str = None,
    source2_filename: str = None,
):
    ensure_consolidation_log()
    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO consolidation_log (
                source_table_1, source_table_2, source_schema,
                join_column, join_type,
                result_view, result_schema,
                row_count, columns_count, sql_text,
                result_size_bytes, result_size_pretty,
                duration_ms,
                source1_row_count, source2_row_count,
                matched_row_count, match_percent,
                initiated_by_ip, initiated_by_host,
                status, error_message, superset_status,
                source1_filename, source2_filename
            ) VALUES (
                %s, %s, 'public',
                %s, %s,
                %s, 'public',
                %s, %s, %s,
                %s, %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s
            )
        """, (
            source_table_1, source_table_2,
            join_column, join_type,
            result_view,
            row_count, columns_count, sql_text,
            result_size_bytes, result_size_pretty,
            duration_ms,
            source1_row_count, source2_row_count,
            matched_row_count, match_percent,
            initiated_by_ip, initiated_by_host,
            status, error_message, superset_status,
            source1_filename, source2_filename,
        ))
        conn.commit()
    finally:
        conn.close()


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
    df1 = read_uploaded(c1, file1.filename, sheet1)
    df2 = read_uploaded(c2, file2.filename, sheet2)
    if df1.empty or df2.empty: raise HTTPException(400, "Один из файлов пустой")

    t1 = table1_name.strip() or clean_table_name(file1.filename)
    t2 = table2_name.strip() or clean_table_name(file2.filename)
    if t1 == t2: t2 += "_2"

    df1.columns = clean_columns(df1.columns)
    df2.columns = clean_columns(df2.columns)

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
        "table1": {"name": t1, "columns": list(df1.columns), "rows": len(df1), "filename": file1.filename},
        "table2": {"name": t2, "columns": list(df2.columns), "rows": len(df2), "filename": file2.filename},
        "common_columns": common,
        "suggested_join_column": suggestions[0] if suggestions else None,
        "join_suggestions": suggestions[:5],
    }

@app.post("/api/consolidate/execute")
async def execute(body: dict, request: Request):
    table1 = body.get("table1")
    table2 = body.get("table2")
    join_column = body.get("join_column")
    join_type = body.get("join_type", "LEFT").upper()
    result_name = clean_name(body.get("result_name") or f"view_{table1}_{table2}")[:50]
    source1_filename = body.get("source1_filename")
    source2_filename = body.get("source2_filename")

    if not all([table1, table2, join_column]):
        raise HTTPException(400, "Нужны: table1, table2, join_column")

    client_ip = get_client_ip(request)
    client_host = request.headers.get("Host", "unknown")

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

    columns_count = len(select_parts)
    row_count = None
    started_at = time.monotonic()

    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(view_sql)
        conn.commit()
        cur.execute(f'SELECT COUNT(*) FROM "{result_name}"')
        row_count = cur.fetchone()[0]
    except Exception as e:
        conn.rollback()
        duration_ms = int((time.monotonic() - started_at) * 1000)
        write_consolidation_log(
            source_table_1=table1, source_table_2=table2,
            join_column=join_column, join_type=join_type,
            result_view=result_name,
            row_count=None, columns_count=None,
            sql_text=view_sql,
            duration_ms=duration_ms,
            initiated_by_ip=client_ip,
            initiated_by_host=client_host,
            status="error",
            error_message=str(e),
            source1_filename=source1_filename,
            source2_filename=source2_filename,
        )
        raise HTTPException(500, f"Ошибка VIEW: {e}")
    finally:
        conn.close()

    duration_ms = int((time.monotonic() - started_at) * 1000)

    ext = collect_extended_meta(table1, table2, join_column)

    superset_ok = "недоступен"
    try:
        token = superset_token()
        register_in_superset(token, result_name)
        superset_ok = "зарегистрирован"
    except Exception as e:
        superset_ok = str(e)

    write_consolidation_log(
        source_table_1=table1, source_table_2=table2,
        join_column=join_column, join_type=join_type,
        result_view=result_name,
        row_count=row_count,
        columns_count=columns_count,
        sql_text=view_sql,
        duration_ms=duration_ms,
        result_size_bytes=ext["result_size_bytes"],
        result_size_pretty=ext["result_size_pretty"],
        source1_row_count=ext["source1_row_count"],
        source2_row_count=ext["source2_row_count"],
        matched_row_count=ext["matched_row_count"],
        match_percent=ext["match_percent"],
        initiated_by_ip=client_ip,
        initiated_by_host=client_host,
        status="success",
        superset_status=superset_ok,
        source1_filename=source1_filename,
        source2_filename=source2_filename,
    )

    return {
        "status": "ok",
        "result_view": result_name,
        "rows": row_count,
        "join_type": join_type,
        "join_column": join_column,
        "sql": view_sql,
        "superset": superset_ok,
        "superset_url": f"{SUPERSET_URL}/tablemodelview/list/",
        "duration_ms": duration_ms,
        "match_percent": float(ext["match_percent"]) if ext["match_percent"] is not None else None,
    }


@app.get("/api/consolidation/history")
def consolidation_history(limit: int = 50):
    ensure_consolidation_log()
    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                id, source_table_1, source_table_2, source_schema,
                join_column, join_type,
                result_view, result_schema,
                row_count, columns_count, sql_text,
                result_size_bytes, result_size_pretty,
                duration_ms,
                source1_row_count, source2_row_count,
                matched_row_count, match_percent,
                initiated_by_ip, initiated_by_host,
                status, error_message,
                created_at, superset_status,
                source1_filename, source2_filename
            FROM consolidation_log
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    finally:
        conn.close()

    records = []
    for row in rows:
        rec = dict(zip(cols, row))
        if rec.get("created_at"):
            rec["created_at"] = rec["created_at"].isoformat()
        if rec.get("match_percent") is not None:
            rec["match_percent"] = float(rec["match_percent"])
        records.append(rec)

    return {"history": records, "total": len(records)}


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
        status = "уже существует" if r.status_code == 422 else "добавлено в Superset"
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