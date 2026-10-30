#!/usr/bin/env python3
"""
SQL-миграция для PostgreSQL: reply_to + attachments.

Запуск:
    python3 migrate_reply_attachments.py
"""
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Подключение: DATABASE_URL из env, или из systemd override.conf
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    # Пробуем прочитать из systemd override.conf
    import subprocess
    try:
        result = subprocess.run(
            ['grep', '-rh', 'DATABASE_URL', '/etc/systemd/system/'],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                DATABASE_URL = line.split('=', 1)[1].strip().strip('"')
                break
    except Exception:
        pass

if not DATABASE_URL:
    print("❌ DATABASE_URL не найден в env и systemd.")
    exit(1)

# Парсим DATABASE_URL
# Формат: postgresql://user:pass@host:port/dbname
from urllib.parse import urlparse, unquote
parsed = urlparse(DATABASE_URL)

conn = psycopg2.connect(
    dbname=parsed.path.lstrip('/'),
    user=parsed.username,
    password=parsed.password,
    host=parsed.hostname or 'localhost',
    port=parsed.port or 5432,
    connect_timeout=10,
)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()

SQL = """
DO $$
BEGIN
    -- ---- File.project_id: NOT NULL → NULLABLE ----
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file'
          AND column_name = 'project_id'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE file ALTER COLUMN project_id DROP NOT NULL;
    END IF;

    -- ---- File.message_id ----
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file' AND column_name = 'message_id'
    ) THEN
        ALTER TABLE file ADD COLUMN message_id INTEGER;
        ALTER TABLE file ADD CONSTRAINT fk_file_message
            FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE;
        CREATE INDEX ix_file_message_id ON file(message_id);
    END IF;

    -- ---- File.support_message_id ----
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file' AND column_name = 'support_message_id'
    ) THEN
        ALTER TABLE file ADD COLUMN support_message_id INTEGER;
        ALTER TABLE file ADD CONSTRAINT fk_file_support_message
            FOREIGN KEY (support_message_id) REFERENCES support_message(id) ON DELETE CASCADE;
        CREATE INDEX ix_file_support_message_id ON file(support_message_id);
    END IF;

    -- ---- Message.reply_to_id ----
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'message' AND column_name = 'reply_to_id'
    ) THEN
        ALTER TABLE message ADD COLUMN reply_to_id INTEGER;
        ALTER TABLE message ADD CONSTRAINT fk_message_reply_to
            FOREIGN KEY (reply_to_id) REFERENCES message(id) ON DELETE SET NULL;
        CREATE INDEX ix_message_reply_to_id ON message(reply_to_id);
    END IF;

    -- ---- SupportMessage.reply_to_id ----
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'support_message' AND column_name = 'reply_to_id'
    ) THEN
        ALTER TABLE support_message ADD COLUMN reply_to_id INTEGER;
        ALTER TABLE support_message ADD CONSTRAINT fk_support_message_reply_to
            FOREIGN KEY (reply_to_id) REFERENCES support_message(id) ON DELETE SET NULL;
        CREATE INDEX ix_support_message_reply_to_id ON support_message(reply_to_id);
    END IF;
END
$$;
"""

print("🚀 Запуск миграции...")
try:
    cur.execute(SQL)
    print("✅ Миграция выполнена успешно.")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    exit(1)
finally:
    cur.close()
    conn.close()
    print("🔌 Соединение закрыто.")
