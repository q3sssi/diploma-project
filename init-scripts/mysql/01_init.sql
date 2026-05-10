ALTER DATABASE hr_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE hr_db;

CREATE TABLE IF NOT EXISTS departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location VARCHAR(100)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS employees (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    department_id INT,
    position VARCHAR(100),
    salary DECIMAL(10, 2),
    hire_date DATE,
    region VARCHAR(50),
    FOREIGN KEY (department_id) REFERENCES departments(id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO departments (name, location) VALUES
  ('Продажи', 'Москва'),
  ('IT', 'СПб'),
  ('HR', 'Москва'),
  ('Логистика', 'Новосибирск');

INSERT INTO employees (full_name, department_id, position, salary, hire_date, region) VALUES
  ('Иванов Алексей', 1, 'Менеджер по продажам', 85000, '2021-03-01', 'Москва'),
  ('Петрова Мария', 2, 'Backend-разработчик', 130000, '2020-06-15', 'СПб'),
  ('Сидоров Дмитрий', 1, 'Старший менеджер', 105000, '2019-11-20', 'Москва'),
  ('Козлова Анна', 3, 'HR-специалист', 70000, '2022-01-10', 'Москва'),
  ('Новиков Игорь', 4, 'Логист', 65000, '2021-08-05', 'Новосибирск'),
  ('Морозова Елена', 2, 'Frontend-разработчик', 115000, '2020-09-01', 'СПб'),
  ('Волков Кирилл', 1, 'Менеджер по продажам', 78000, '2023-02-14', 'Казань');