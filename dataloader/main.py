"""
DataBridge API — v2
Архитектура: Adapter Pattern для источников данных.
Все источники (CSV, Excel, PostgreSQL, MySQL) унифицированы через DataSource.
"""

from __future__ import annotations

import io
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd
import psycopg2
import requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ─────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ─────────────────────────────────────────────────────────────────────────────

POSTGRES_HOST     = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT     = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER     = os.getenv("POSTGRES_USER", "pguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "pgpassword")
POSTGRES_DB       = os.getenv("POSTGRES_DB", "sales_db")
SUPERSET_URL      = os.getenv("SUPERSET_URL", "http://superset:8088")
SUPERSET_USER     = os.getenv("SUPERSET_USER", "admin")
SUPERSET_PASSWORD = os.getenv("SUPERSET_PASSWORD", "admin")

SQL_CONNECT_TIMEOUT = 10   # секунды
SQL_QUERY_TIMEOUT   = 30   # секунды

# ─────────────────────────────────────────────────────────────────────────────
# Утилиты транслитерации / именования
# ─────────────────────────────────────────────────────────────────────────────

_TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z',
    'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','У':'U','Ф':'F','Х':'Kh','Ц':'Ts','Ч':'Ch','Ш':'Sh',
    'Щ':'Sch','Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya',
}

def _transliterate(t: str) -> str:
    return ''.join(_TRANSLIT.get(c, c) for c in t)

def clean_name(name: str) -> str:
    n = _transliterate(str(name))
    n = re.sub(r'[^a-zA-Z0-9_]', '_', n)
    n = re.sub(r'_+', '_', n).strip('_').lower()
    if not n or n[0].isdigit():
        n = 'col_' + n
    return n or 'column'

def clean_columns(columns) -> list[str]:
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

def clean_table_name(filename: str) -> str:
    n = clean_name(os.path.splitext(filename)[0])
    return n[:50] or 'table'

# ─────────────────────────────────────────────────────────────────────────────
# Abstraction Layer: DataSource адаптеры
# ─────────────────────────────────────────────────────────────────────────────

class DataSource(ABC):
    """Базовый адаптер источника данных.
    Любой источник должен уметь отдать DataFrame с нормализованными колонками.
    """

    @abstractmethod
    def load(self) -> pd.DataFrame:
        """Загружает данные и возвращает DataFrame."""

    @property
    @abstractmethod
    def suggested_name(self) -> str:
        """Предлагаемое имя таблицы для хранения."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Человекочитаемое имя источника для UI."""


class FileDataSource(DataSource):
    """Адаптер для CSV и Excel файлов."""

    def __init__(self, content: bytes, filename: str, sheet=0):
        self._content  = content
        self._filename = filename
        self._sheet    = sheet

    def load(self) -> pd.DataFrame:
        fn = self._filename.lower()
        if fn.endswith('.csv'):
            try:
                df = pd.read_csv(io.BytesIO(self._content), encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(self._content), encoding='cp1251')
        elif fn.endswith(('.xlsx', '.xls')):
            try:
                sheet = int(self._sheet)
            except (TypeError, ValueError):
                sheet = self._sheet
            df = pd.read_excel(io.BytesIO(self._content), sheet_name=sheet)
        else:
            raise HTTPException(400, f"Неподдерживаемый формат файла: {self._filename}")

        if df.empty:
            raise HTTPException(400, f"Файл пустой: {self._filename}")

        df.columns = clean_columns(df.columns)
        return df

    @property
    def suggested_name(self) -> str:
        return clean_table_name(self._filename)

    @property
    def display_name(self) -> str:
        return self._filename


class SQLDataSource(DataSource):
    """Адаптер для PostgreSQL и MySQL источников.

    Подключается к внешней БД, считывает указанную таблицу/запрос
    и возвращает DataFrame — точно так же, как FileDataSource.
    """

    SUPPORTED = ('postgresql', 'mysql')

    def __init__(
        self,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        table_name: str,
        custom_query: Optional[str] = None,
    ):
        if db_type not in self.SUPPORTED:
            raise HTTPException(400, f"Поддерживаются: {', '.join(self.SUPPORTED)}")

        self.db_type      = db_type
        self.host         = host
        self.port         = port
        self.database     = database
        self.username     = username
        self.password     = password
        self.table_name   = table_name
        self.custom_query = custom_query

    # ── Строка подключения ──────────────────────────────────────────────────

    def _sqlalchemy_uri(self) -> str:
        if self.db_type == 'postgresql':
            return (
                f"postgresql+psycopg2://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        return (
            f"mysql+pymysql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    # ── Загрузка данных ─────────────────────────────────────────────────────

    def load(self) -> pd.DataFrame:
        from sqlalchemy import create_engine, text

        uri = self._sqlalchemy_uri()
        connect_args: dict = {}

        if self.db_type == 'postgresql':
            connect_args = {
                "connect_timeout": SQL_CONNECT_TIMEOUT,
                "options": f"-c statement_timeout={SQL_QUERY_TIMEOUT * 1000}",
            }
        elif self.db_type == 'mysql':
            connect_args = {
                "connect_timeout": SQL_CONNECT_TIMEOUT,
                "read_timeout": SQL_QUERY_TIMEOUT,
            }

        try:
            engine = create_engine(uri, connect_args=connect_args)
            query  = self.custom_query or f'SELECT * FROM "{self.table_name}"'
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn)
            engine.dispose()
        except Exception as e:
            _classify_sql_error(e)

        if df.empty:
            raise HTTPException(400, f"Таблица пустая: {self.table_name}")

        df.columns = clean_columns(df.columns)
        return df

    @property
    def suggested_name(self) -> str:
        return clean_name(f"{self.db_type}_{self.database}_{self.table_name}")[:50]

    @property
    def display_name(self) -> str:
        return f"{self.db_type}://{self.host}/{self.database}.{self.table_name}"

    # ── Вспомогательные методы ──────────────────────────────────────────────

    @classmethod
    def get_tables(
        cls,
        db_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> list[dict]:
        """Возвращает список таблиц из внешней БД."""
        from sqlalchemy import create_engine, inspect

        src = cls(db_type, host, port, database, username, password, table_name='_probe')
        uri = src._sqlalchemy_uri()

        connect_args: dict = {}
        if db_type == 'postgresql':
            connect_args = {"connect_timeout": SQL_CONNECT_TIMEOUT}
        elif db_type == 'mysql':
            connect_args = {"connect_timeout": SQL_CONNECT_TIMEOUT}

        try:
            engine = create_engine(uri, connect_args=connect_args)
            insp   = inspect(engine)
            tables = []
            for schema in insp.get_schema_names():
                if schema in ('information_schema', 'performance_schema', 'sys', 'pg_catalog'):
                    continue
                for tbl in insp.get_table_names(schema=schema):
                    tables.append({"schema": schema, "name": tbl})
            engine.dispose()
        except Exception as e:
            _classify_sql_error(e)

        return tables


def _classify_sql_error(e: Exception) -> None:
    """Преобразует технические ошибки подключения в понятные HTTP-ответы."""
    msg = str(e).lower()
    if 'connection refused' in msg or 'could not connect' in msg:
        raise HTTPException(503, f"Не удалось подключиться к БД: хост недоступен. Проверьте host/port.")
    if 'password authentication' in msg or 'access denied' in msg:
        raise HTTPException(401, "Ошибка аутентификации: неверный логин или пароль.")
    if 'does not exist' in msg or 'unknown database' in msg:
        raise HTTPException(404, f"База данных не найдена. Проверьте имя базы.")
    if 'timeout' in msg:
        raise HTTPException(504, f"Превышено время ожидания подключения ({SQL_CONNECT_TIMEOUT}с).")
    raise HTTPException(500, f"Ошибка подключения к БД: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL — внутреннее хранилище
# ─────────────────────────────────────────────────────────────────────────────

def pg_connect():
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )

def get_engine():
    from sqlalchemy import create_engine
    return create_engine(
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

def df_to_postgres(df: pd.DataFrame, table_name: str) -> None:
    """Загружает DataFrame во внутренний PostgreSQL.
    Если таблица используется во VIEW — сохраняет VIEW и восстанавливает их после.
    """
    engine = get_engine()
    conn   = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT table_name, view_definition
               FROM information_schema.views
               WHERE table_schema = 'public' AND view_definition ILIKE %s""",
            (f'%"{table_name}"%',),
        )
        dependent_views = cur.fetchall()
        for view_name, _ in dependent_views:
            cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')
        conn.commit()
    finally:
        conn.close()

    df.to_sql(table_name, engine, if_exists='replace', index=False, method='multi', chunksize=500)
    engine.dispose()

    if dependent_views:
        conn2 = pg_connect()
        try:
            cur2 = conn2.cursor()
            for view_name, view_def in dependent_views:
                cur2.execute(f'CREATE OR REPLACE VIEW "{view_name}" AS {view_def}')
            conn2.commit()
        finally:
            conn2.close()

def get_table_columns(table_name: str) -> list[dict]:
    conn = pg_connect()
    cur  = conn.cursor()
    cur.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position""",
        (table_name,),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1]} for r in rows]

def get_client_ip(request: Request) -> str:
    for header in ("X-Forwarded-For", "X-Real-IP"):
        val = request.headers.get(header)
        if val:
            return val.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# Superset
# ─────────────────────────────────────────────────────────────────────────────

def superset_token() -> str:
    r = requests.post(
        f"{SUPERSET_URL}/api/v1/security/login",
        json={"username": SUPERSET_USER, "password": SUPERSET_PASSWORD, "provider": "db"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def superset_db_id(token: str) -> int:
    r = requests.get(
        f"{SUPERSET_URL}/api/v1/database/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    databases = r.json().get("result", [])
    for db in databases:
        uri  = db.get("sqlalchemy_uri", "") or ""
        name = db.get("database_name", "") or ""
        if "postgresql" in uri or "trino" in uri or "postgres" in name.lower():
            return db["id"]
    if len(databases) == 1:
        return databases[0]["id"]
    raise HTTPException(404, "Не найдено подключение PostgreSQL/Trino в Superset")

def register_in_superset(token: str, table_name: str) -> None:
    db_id = superset_db_id(token)
    r = requests.post(
        f"{SUPERSET_URL}/api/v1/dataset/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"database": db_id, "schema": "public", "table_name": table_name},
        timeout=15,
    )
    if r.status_code not in (200, 201, 422):
        r.raise_for_status()

# ─────────────────────────────────────────────────────────────────────────────
# consolidation_log
# ─────────────────────────────────────────────────────────────────────────────

def ensure_consolidation_log() -> None:
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
            CREATE INDEX IF NOT EXISTS idx_cl_created_at  ON consolidation_log (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cl_result_view ON consolidation_log (result_view);
            CREATE INDEX IF NOT EXISTS idx_cl_status      ON consolidation_log (status);
        """)
        for col, typedef in [
            ("source1_filename", "VARCHAR(255)"),
            ("source2_filename", "VARCHAR(255)"),
        ]:
            cur.execute(f"ALTER TABLE consolidation_log ADD COLUMN IF NOT EXISTS {col} {typedef}")
        conn.commit()
    finally:
        conn.close()


def collect_extended_meta(table1: str, table2: str, join_column: str) -> dict:
    meta: dict = {
        "result_size_bytes": None, "result_size_pretty": None,
        "source1_row_count": None, "source2_row_count": None,
        "matched_row_count": None, "match_percent": None,
    }
    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT pg_total_relation_size(quote_ident(%s)) + pg_total_relation_size(quote_ident(%s)),
                   pg_size_pretty(pg_total_relation_size(quote_ident(%s)) + pg_total_relation_size(quote_ident(%s)))
        """, (table1, table2, table1, table2))
        row = cur.fetchone()
        if row:
            meta["result_size_bytes"]  = row[0]
            meta["result_size_pretty"] = row[1]

        cur.execute(f'SELECT COUNT(*) FROM "{table1}"')
        meta["source1_row_count"] = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(*) FROM "{table2}"')
        meta["source2_row_count"] = cur.fetchone()[0]

        cur.execute(f"""
            SELECT COUNT(*) FROM "{table1}" a
            INNER JOIN "{table2}" b ON a."{join_column}" = b."{join_column}"
        """)
        matched = cur.fetchone()[0]
        meta["matched_row_count"] = matched
        if meta["source1_row_count"]:
            meta["match_percent"] = round(matched / meta["source1_row_count"] * 100, 2)
    except Exception:
        pass
    finally:
        conn.close()
    return meta


def write_consolidation_log(**kwargs) -> None:
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
                result_size_bytes, result_size_pretty, duration_ms,
                source1_row_count, source2_row_count,
                matched_row_count, match_percent,
                initiated_by_ip, initiated_by_host,
                status, error_message, superset_status,
                source1_filename, source2_filename
            ) VALUES (
                %(source_table_1)s, %(source_table_2)s, 'public',
                %(join_column)s, %(join_type)s,
                %(result_view)s, 'public',
                %(row_count)s, %(columns_count)s, %(sql_text)s,
                %(result_size_bytes)s, %(result_size_pretty)s, %(duration_ms)s,
                %(source1_row_count)s, %(source2_row_count)s,
                %(matched_row_count)s, %(match_percent)s,
                %(initiated_by_ip)s, %(initiated_by_host)s,
                %(status)s, %(error_message)s, %(superset_status)s,
                %(source1_filename)s, %(source2_filename)s
            )
        """, {
            "source_table_1": kwargs.get("source_table_1"),
            "source_table_2": kwargs.get("source_table_2"),
            "join_column":    kwargs.get("join_column"),
            "join_type":      kwargs.get("join_type"),
            "result_view":    kwargs.get("result_view"),
            "row_count":      kwargs.get("row_count"),
            "columns_count":  kwargs.get("columns_count"),
            "sql_text":       kwargs.get("sql_text"),
            "result_size_bytes":  kwargs.get("result_size_bytes"),
            "result_size_pretty": kwargs.get("result_size_pretty"),
            "duration_ms":        kwargs.get("duration_ms"),
            "source1_row_count":  kwargs.get("source1_row_count"),
            "source2_row_count":  kwargs.get("source2_row_count"),
            "matched_row_count":  kwargs.get("matched_row_count"),
            "match_percent":      kwargs.get("match_percent"),
            "initiated_by_ip":    kwargs.get("initiated_by_ip"),
            "initiated_by_host":  kwargs.get("initiated_by_host"),
            "status":         kwargs.get("status", "success"),
            "error_message":  kwargs.get("error_message"),
            "superset_status": kwargs.get("superset_status"),
            "source1_filename": kwargs.get("source1_filename"),
            "source2_filename": kwargs.get("source2_filename"),
        })
        conn.commit()
    finally:
        conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI приложение
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="DataBridge API v2")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2"}

# ─────────────────────────────────────────────────────────────────────────────
# SQL источники: probe / list tables / import
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/sql/probe")
async def sql_probe(
    db_type:  str = Form(...),
    host:     str = Form(...),
    port:     str = Form(...),
    database: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    """Проверяет подключение и возвращает список таблиц внешней БД."""
    try:
        port_int = int(port)
    except ValueError:
        raise HTTPException(400, "Порт должен быть числом")

    tables = SQLDataSource.get_tables(db_type, host, port_int, database, username, password)
    return {
        "status": "ok",
        "db_type": db_type,
        "host": host,
        "database": database,
        "tables": tables,
        "table_count": len(tables),
    }


@app.post("/api/sql/import")
async def sql_import(
    db_type:    str = Form(...),
    host:       str = Form(...),
    port:       str = Form(...),
    database:   str = Form(...),
    username:   str = Form(...),
    password:   str = Form(...),
    table_name: str = Form(...),
    dest_name:  str = Form(default=""),
):
    """Импортирует таблицу из внешней БД во внутренний PostgreSQL."""
    try:
        port_int = int(port)
    except ValueError:
        raise HTTPException(400, "Порт должен быть числом")

    source    = SQLDataSource(db_type, host, port_int, database, username, password, table_name)
    df        = source.load()
    dest      = dest_name.strip() or source.suggested_name
    dest      = clean_name(dest)[:50]

    df_to_postgres(df, dest)

    superset_status = "недоступен"
    try:
        token = superset_token()
        register_in_superset(token, dest)
        superset_status = "зарегистрирован"
    except Exception as e:
        superset_status = str(e)

    return {
        "status": "ok",
        "source": source.display_name,
        "dest_table": dest,
        "rows": len(df),
        "columns": list(df.columns),
        "superset": superset_status,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Консолидация: analyze + execute
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/consolidate/analyze")
async def analyze(
    file1:       UploadFile = File(...),
    file2:       UploadFile = File(...),
    table1_name: str = Form(default=""),
    table2_name: str = Form(default=""),
    sheet1:      str = Form(default="0"),
    sheet2:      str = Form(default="0"),
):
    """Загружает два файловых источника и анализирует общие колонки."""
    c1, c2 = await file1.read(), await file2.read()

    src1 = FileDataSource(c1, file1.filename, sheet1)
    src2 = FileDataSource(c2, file2.filename, sheet2)

    df1 = src1.load()
    df2 = src2.load()

    t1 = clean_name(table1_name.strip() or src1.suggested_name)[:50]
    t2 = clean_name(table2_name.strip() or src2.suggested_name)[:50]
    if t1 == t2:
        t2 += "_2"

    df_to_postgres(df1, t1)
    df_to_postgres(df2, t2)

    return _build_analyze_response(t1, t2, df1, df2, file1.filename, file2.filename)


@app.post("/api/consolidate/analyze-mixed")
async def analyze_mixed(request: Request):
    """
    Анализирует источники смешанного типа (файлы + SQL).
    Принимает multipart/form-data с JSON-описанием источников.

    Поля формы:
      sources  — JSON-массив дескрипторов источников
      file_0, file_1, … — загружаемые файлы (если тип == 'file')

    Дескриптор источника:
      { "type": "file", "file_key": "file_0", "table_name": "..." }
      { "type": "sql",  "db_type": "postgresql", "host": ...,
        "port": ..., "database": ..., "username": ...,
        "password": ..., "table_name": ..., "dest_name": "..." }
    """
    import json
    from fastapi import UploadFile

    form = await request.form()

    try:
        sources_raw = json.loads(form.get("sources", "[]"))
    except json.JSONDecodeError:
        raise HTTPException(400, "Поле 'sources' должно быть валидным JSON")

    if len(sources_raw) < 2:
        raise HTTPException(400, "Нужно минимум два источника")

    loaded: list[tuple[str, pd.DataFrame, str]] = []  # (table_name, df, display_name)

    for i, src_desc in enumerate(sources_raw):
        src_type = src_desc.get("type")

        if src_type == "file":
            file_key = src_desc.get("file_key", f"file_{i}")
            upload: UploadFile = form.get(file_key)
            if upload is None:
                raise HTTPException(400, f"Файл '{file_key}' не найден в форме")
            content = await upload.read()
            sheet   = src_desc.get("sheet", 0)
            src     = FileDataSource(content, upload.filename, sheet)
            df      = src.load()
            tname   = clean_name(src_desc.get("table_name") or src.suggested_name)[:50]
            display = upload.filename

        elif src_type == "sql":
            try:
                port_int = int(src_desc.get("port", 5432))
            except (ValueError, TypeError):
                raise HTTPException(400, f"Источник {i}: порт должен быть числом")
            src = SQLDataSource(
                db_type=src_desc["db_type"],
                host=src_desc["host"],
                port=port_int,
                database=src_desc["database"],
                username=src_desc["username"],
                password=src_desc["password"],
                table_name=src_desc["table_name"],
            )
            df      = src.load()
            tname   = clean_name(src_desc.get("dest_name") or src.suggested_name)[:50]
            display = src.display_name

        else:
            raise HTTPException(400, f"Источник {i}: неизвестный тип '{src_type}'")

        # Гарантируем уникальность имён
        existing_names = [n for n, _, _ in loaded]
        suffix = 2
        original = tname
        while tname in existing_names:
            tname = f"{original}_{suffix}"
            suffix += 1

        df_to_postgres(df, tname)
        loaded.append((tname, df, display))

    t1, df1, disp1 = loaded[0]
    t2, df2, disp2 = loaded[1]

    return _build_analyze_response(t1, t2, df1, df2, disp1, disp2)


def _build_analyze_response(
    t1: str, t2: str,
    df1: pd.DataFrame, df2: pd.DataFrame,
    disp1: str, disp2: str,
) -> dict:
    common = sorted(set(df1.columns) & set(df2.columns))

    def score(col: str) -> int:
        if col in ('id', 'region', 'city', 'date', 'category', 'type', 'code'):
            return 0
        if any(k in col for k in ('id', 'key', 'code', 'region', 'city')):
            return 1
        return 2

    suggestions = sorted(common, key=score)
    return {
        "status": "ok",
        "table1": {"name": t1, "columns": list(df1.columns), "rows": len(df1), "filename": disp1},
        "table2": {"name": t2, "columns": list(df2.columns), "rows": len(df2), "filename": disp2},
        "common_columns": common,
        "suggested_join_column": suggestions[0] if suggestions else None,
        "join_suggestions": suggestions[:5],
    }


@app.post("/api/consolidate/execute")
async def execute(body: dict, request: Request):
    table1   = body.get("table1")
    table2   = body.get("table2")
    join_col = body.get("join_column")
    join_type = body.get("join_type", "LEFT").upper()
    result_name = clean_name(body.get("result_name") or f"view_{table1}_{table2}")[:50]
    source1_filename = body.get("source1_filename")
    source2_filename = body.get("source2_filename")

    if not all([table1, table2, join_col]):
        raise HTTPException(400, "Нужны: table1, table2, join_column")

    client_ip   = get_client_ip(request)
    client_host = request.headers.get("Host", "unknown")

    cols1      = get_table_columns(table1)
    cols2      = get_table_columns(table2)
    col1_names = {c["name"] for c in cols1}

    select_parts = [f'    a."{c["name"]}"' for c in cols1]
    for c in cols2:
        if c["name"] == join_col:
            continue
        alias = f'b_{c["name"]}' if c["name"] in col1_names else c["name"]
        select_parts.append(f'    b."{c["name"]}" AS "{alias}"')

    view_sql = (
        f'CREATE OR REPLACE VIEW "{result_name}" AS\n'
        f'SELECT\n' + ',\n'.join(select_parts) + '\n'
        f'FROM "{table1}" a\n'
        f'{join_type} JOIN "{table2}" b ON a."{join_col}" = b."{join_col}";'
    )

    row_count  = None
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
            join_column=join_col, join_type=join_type,
            result_view=result_name, row_count=None, columns_count=None,
            sql_text=view_sql, duration_ms=duration_ms,
            initiated_by_ip=client_ip, initiated_by_host=client_host,
            status="error", error_message=str(e),
            source1_filename=source1_filename, source2_filename=source2_filename,
        )
        raise HTTPException(500, f"Ошибка создания VIEW: {e}")
    finally:
        conn.close()

    duration_ms = int((time.monotonic() - started_at) * 1000)
    ext = collect_extended_meta(table1, table2, join_col)

    superset_ok = "недоступен"
    try:
        token = superset_token()
        register_in_superset(token, result_name)
        superset_ok = "зарегистрирован"
    except Exception as e:
        superset_ok = str(e)

    write_consolidation_log(
        source_table_1=table1, source_table_2=table2,
        join_column=join_col, join_type=join_type,
        result_view=result_name, row_count=row_count,
        columns_count=len(select_parts), sql_text=view_sql,
        duration_ms=duration_ms,
        result_size_bytes=ext["result_size_bytes"],
        result_size_pretty=ext["result_size_pretty"],
        source1_row_count=ext["source1_row_count"],
        source2_row_count=ext["source2_row_count"],
        matched_row_count=ext["matched_row_count"],
        match_percent=ext["match_percent"],
        initiated_by_ip=client_ip, initiated_by_host=client_host,
        status="success", superset_status=superset_ok,
        source1_filename=source1_filename, source2_filename=source2_filename,
    )

    return {
        "status": "ok",
        "result_view": result_name,
        "rows": row_count,
        "join_type": join_type,
        "join_column": join_col,
        "sql": view_sql,
        "superset": superset_ok,
        "superset_url": f"{SUPERSET_URL}/tablemodelview/list/",
        "duration_ms": duration_ms,
        "match_percent": float(ext["match_percent"]) if ext["match_percent"] is not None else None,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Таблицы: список + удаление
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/tables")
def list_tables():
    try:
        conn = pg_connect()
        cur  = conn.cursor()
        # Таблицы
        cur.execute("""
            SELECT table_name,
                   pg_size_pretty(pg_total_relation_size(quote_ident(table_name))),
                   'table'
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY table_name
        """)
        rows = list(cur.fetchall())
        # Представления (VIEW)
        cur.execute("""
            SELECT table_name,
                   '—',
                   'view'
            FROM information_schema.views
            WHERE table_schema='public'
            ORDER BY table_name
        """)
        rows += list(cur.fetchall())
        conn.close()
        return {"tables": [{"name": r[0], "size": r[1], "type": r[2]} for r in rows]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/tables/{table_name}")
def delete_table(table_name: str):
    """Удаляет таблицу или VIEW из внутреннего PostgreSQL."""
    # Защита от случайного удаления системных таблиц
    protected = {'consolidation_log', 'products', 'orders'}
    if table_name in protected:
        raise HTTPException(403, f"Таблица '{table_name}' защищена от удаления.")

    conn = pg_connect()
    try:
        cur = conn.cursor()
        # Определяем — это таблица или VIEW
        cur.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s",
            (table_name,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Таблица '{table_name}' не найдена.")

        if row[0] == 'VIEW':
            cur.execute(f'DROP VIEW IF EXISTS "{table_name}" CASCADE')
        else:
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')

        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Ошибка удаления: {e}")
    finally:
        conn.close()

    return {"status": "ok", "deleted": table_name}


@app.get("/api/tables/{table_name}/columns")
def columns(table_name: str):
    return {"columns": get_table_columns(table_name)}

# ─────────────────────────────────────────────────────────────────────────────
# Внешнее подключение БД (регистрация в Superset)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/connect/database")
async def connect_db(
    db_type:         str = Form(...),
    host:            str = Form(...),
    port:            str = Form(...),
    database:        str = Form(...),
    username:        str = Form(...),
    password:        str = Form(...),
    connection_name: str = Form(default=""),
):
    if db_type not in ("postgresql", "mysql"):
        raise HTTPException(400, "Поддерживаются: postgresql, mysql")

    conn_name = clean_name(connection_name or f"{db_type}_{database}")[:50]
    uri = (
        f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
        if db_type == "postgresql"
        else f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
    )

    try:
        token = superset_token()
        r = requests.post(
            f"{SUPERSET_URL}/api/v1/database/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"database_name": conn_name, "sqlalchemy_uri": uri, "expose_in_sqllab": True},
            timeout=15,
        )
        status = "уже существует" if r.status_code == 422 else "добавлено в Superset"
    except Exception as e:
        status = f"ошибка: {e}"

    return {"status": "ok", "connection_name": conn_name, "superset": status}

# ─────────────────────────────────────────────────────────────────────────────
# История консолидаций
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/consolidation/history")
def consolidation_history(limit: int = 50):
    ensure_consolidation_log()
    conn = pg_connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, source_table_1, source_table_2, source_schema,
                   join_column, join_type, result_view, result_schema,
                   row_count, columns_count, sql_text,
                   result_size_bytes, result_size_pretty, duration_ms,
                   source1_row_count, source2_row_count,
                   matched_row_count, match_percent,
                   initiated_by_ip, initiated_by_host,
                   status, error_message, created_at, superset_status,
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

# ─────────────────────────────────────────────────────────────────────────────
# Static / index
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

app.mount("/static", StaticFiles(directory="/app/static"), name="static")
