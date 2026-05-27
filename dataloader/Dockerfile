FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn==0.29.0 \
    pandas==2.2.2 \
    openpyxl==3.1.2 \
    psycopg2-binary==2.9.9 \
    sqlalchemy==2.0.30 \
    pymysql==1.1.0 \
    requests==2.31.0 \
    python-multipart==0.0.9 \
    sqlparse==0.5.0 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY main.py .
COPY static/ ./static/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
