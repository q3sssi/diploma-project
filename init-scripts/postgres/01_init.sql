-- Создаём дополнительные базы для Airflow и Superset
-- (sales_db уже создана через POSTGRES_DB в docker-compose)

CREATE DATABASE airflow_db;
CREATE DATABASE superset_db;

-- Выдаём права пользователю
GRANT ALL PRIVILEGES ON DATABASE airflow_db TO pguser;
GRANT ALL PRIVILEGES ON DATABASE superset_db TO pguser;

-- Переключаемся на sales_db и создаём тестовые данные
\c sales_db;

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER,
    total_amount DECIMAL(10, 2),
    order_date DATE,
    region VARCHAR(50)
);

INSERT INTO products (name, category, price) VALUES
  ('Ноутбук Dell XPS', 'Электроника', 89999.00),
  ('Мышь Logitech MX', 'Электроника', 5499.00),
  ('Стол офисный', 'Мебель', 12500.00),
  ('Кресло Ergon', 'Мебель', 18900.00),
  ('Монитор Samsung 27"', 'Электроника', 34990.00);

INSERT INTO orders (product_id, quantity, total_amount, order_date, region) VALUES
  (1, 3, 269997.00, '2024-01-15', 'Москва'),
  (2, 10, 54990.00, '2024-01-20', 'СПб'),
  (3, 5, 62500.00, '2024-02-01', 'Москва'),
  (4, 2, 37800.00, '2024-02-10', 'Новосибирск'),
  (5, 4, 139960.00, '2024-03-05', 'Москва'),
  (1, 1, 89999.00, '2024-03-12', 'Казань'),
  (2, 8, 43992.00, '2024-03-15', 'СПб');