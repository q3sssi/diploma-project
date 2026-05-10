from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.hooks.base import BaseHook
from datetime import datetime, timedelta
import logging
 
# ── Настройки DAG ──────────────────────────────────────
default_args = {
    'owner': 'diploma',
    'depends_on_past': False,
    'email_on_failure': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}
 
dag = DAG(
    'etl_consolidation_pipeline',
    default_args=default_args,
    description='ETL: извлечение данных из PostgreSQL и MySQL, консолидация',
    schedule_interval='0 6 * * *',   # каждый день в 06:00
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['etl', 'diploma'],
)
 
# ── Задача 1: Проверка доступности PostgreSQL ──────────
def check_postgres(**context):
    import psycopg2
    conn = psycopg2.connect(
        host='postgres', port=5432,
        dbname='sales_db', user='pguser', password='pgpassword'
    )
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM orders;')
    count = cursor.fetchone()[0]
    conn.close()
    logging.info(f'PostgreSQL OK. Записей в orders: {count}')
    return count
 
# ── Задача 2: Проверка доступности MySQL ───────────────
def check_mysql(**context):
    import pymysql
    conn = pymysql.connect(
        host='mysql', port=3306,
        db='hr_db', user='mysqluser', password='mysqlpassword'
    )
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM employees;')
    count = cursor.fetchone()[0]
    conn.close()
    logging.info(f'MySQL OK. Записей в employees: {count}')
    return count
 
# ── Задача 3: ETL — перенос агрегатов продаж в PostgreSQL
def etl_sales_summary(**context):
    """
    Считаем сводку продаж по регионам из PostgreSQL orders
    и сохраняем результат в отдельную таблицу-витрину.
    """
    import psycopg2
    conn = psycopg2.connect(
        host='postgres', port=5432,
        dbname='sales_db', user='pguser', password='pgpassword'
    )
    cursor = conn.cursor()
 
    # Создаём витрину если нет
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_summary (
            region VARCHAR(50),
            total_orders INTEGER,
            total_revenue DECIMAL(15, 2),
            avg_order_value DECIMAL(10, 2),
            report_date DATE
        );
    """)
 
    # Очищаем за сегодня
    cursor.execute("DELETE FROM sales_summary WHERE report_date = CURRENT_DATE;")
 
    # Вставляем агрегаты
    cursor.execute("""
        INSERT INTO sales_summary
        SELECT
            region,
            COUNT(*) AS total_orders,
            SUM(total_amount) AS total_revenue,
            AVG(total_amount) AS avg_order_value,
            CURRENT_DATE AS report_date
        FROM orders
        GROUP BY region;
    """)
 
    conn.commit()
    conn.close()
    logging.info('ETL sales_summary завершён успешно')
 
# ── Задача 4: Логирование результатов ──────────────────
def log_pipeline_result(**context):
    pg_count = context['ti'].xcom_pull(task_ids='check_postgres')
    my_count = context['ti'].xcom_pull(task_ids='check_mysql')
    logging.info(f'Пайплайн завершён. PostgreSQL orders: {pg_count}, MySQL employees: {my_count}')
 
# ── Определяем задачи ──────────────────────────────────
t1 = PythonOperator(
    task_id='check_postgres',
    python_callable=check_postgres,
    dag=dag,
)
 
t2 = PythonOperator(
    task_id='check_mysql',
    python_callable=check_mysql,
    dag=dag,
)
 
t3 = PythonOperator(
    task_id='etl_sales_summary',
    python_callable=etl_sales_summary,
    dag=dag,
)
 
t4 = PythonOperator(
    task_id='log_result',
    python_callable=log_pipeline_result,
    dag=dag,
)
 
# ── Порядок выполнения ─────────────────────────────────
# t1 и t2 параллельно → t3 → t4
[t1, t2] >> t3 >> t4
