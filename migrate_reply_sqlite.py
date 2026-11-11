#!/usr/bin/env python3
"""
SQLite-миграция для добавления reply_to_id в таблицу message.

Запуск на сервере:
    cd /var/www/workspace && python3 migrate_reply_sqlite.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'app.db')

if not os.path.exists(DB_PATH):
    # Пробуем альтернативные пути
    alt_paths = [
        'instance/app.db',
        'app.db',
        'workspace.db',
        'instance/database.db',
    ]
    for p in alt_paths:
        if os.path.exists(p):
            DB_PATH = p
            break

print(f"📂 База данных: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print("❌ Файл базы данных не найден.")
    exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Проверяем, есть ли колонка
cursor.execute("PRAGMA table_info(message)")
columns = [row[1] for row in cursor.fetchall()]

if 'reply_to_id' in columns:
    print("✅ Колонка reply_to_id уже существует в таблице message")
else:
    print("➕ Добавляю колонку reply_to_id...")
    cursor.execute("ALTER TABLE message ADD COLUMN reply_to_id INTEGER")
    print("✅ Колонка добавлена")

    # Создаём индекс (SQLite не поддерживает CREATE INDEX IF NOT EXISTS до версии 3.3.0,
    # но современные версии поддерживают)
    try:
        cursor.execute("CREATE INDEX ix_message_reply_to_id ON message(reply_to_id)")
        print("✅ Индекс создан")
    except sqlite3.OperationalError as e:
        if "already exists" in str(e):
            print("ℹ️ Индекс уже существует")
        else:
            print(f"⚠️ Ошибка создания индекса: {e}")

conn.commit()
conn.close()
print("✅ Миграция завершена")
