#!/usr/bin/env python3
"""Миграция: reply_to + attachments для PostgreSQL."""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

conn = psycopg2.connect(
    dbname='workspace_db',
    user='workspace_user',
    password='workspace123',
    host='localhost',
    port=5432,
)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()

SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file' AND column_name = 'project_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE file ALTER COLUMN project_id DROP NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file' AND column_name = 'message_id'
    ) THEN
        ALTER TABLE file ADD COLUMN message_id INTEGER;
        ALTER TABLE file ADD CONSTRAINT fk_file_message
            FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE;
        CREATE INDEX ix_file_message_id ON file(message_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'file' AND column_name = 'support_message_id'
    ) THEN
        ALTER TABLE file ADD COLUMN support_message_id INTEGER;
        ALTER TABLE file ADD CONSTRAINT fk_file_support_message
            FOREIGN KEY (support_message_id) REFERENCES support_message(id) ON DELETE CASCADE;
        CREATE INDEX ix_file_support_message_id ON file(support_message_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'message' AND column_name = 'reply_to_id'
    ) THEN
        ALTER TABLE message ADD COLUMN reply_to_id INTEGER;
        ALTER TABLE message ADD CONSTRAINT fk_message_reply_to
            FOREIGN KEY (reply_to_id) REFERENCES message(id) ON DELETE SET NULL;
        CREATE INDEX ix_message_reply_to_id ON message(reply_to_id);
    END IF;

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

print('🚀 Запуск миграции...')
cur.execute(SQL)
print('✅ Миграция выполнена успешно.')
cur.close()
conn.close()
print('🔌 Соединение закрыто.')
