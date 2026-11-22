#!/bin/bash
# Деплой видеоконференций на сервер
# Запуск: bash deploy_video.sh

SERVER="root@136.234.79.6"
SSH_KEY="-i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

echo "=== Деплой видеоконференций ==="

# 1. Деплой Python файлов
echo ""
echo "📤 Деплой Python файлов..."
scp $SSH_KEY blueprints/video.py $SERVER:/var/www/workspace/blueprints/video.py
scp $SSH_KEY services/push.py $SERVER:/var/www/workspace/services/push.py

# 2. Деплой JS и HTML
echo ""
echo "📤 Деплой JS и HTML..."
scp $SSH_KEY static/js/video_conference.js $SERVER:/var/www/workspace/static/js/video_conference.js
scp $SSH_KEY templates/video_conference.html $SERVER:/var/www/workspace/templates/video_conference.html

# 3. Проверка файлов
echo ""
echo "🔍 Проверка файлов..."
ssh $SSH_KEY $SERVER "wc -l /var/www/workspace/blueprints/video.py /var/www/workspace/services/push.py /var/www/workspace/static/js/video_conference.js /var/www/workspace/templates/video_conference.html"

# 4. Перезапуск
echo ""
echo "🔄 Перезапуск сервиса..."
ssh $SSH_KEY $SERVER "pkill -9 gunicorn 2>/dev/null; sleep 5; systemctl start workspace.service; sleep 3; systemctl is-active workspace.service"

# 5. Проверка логов
echo ""
echo "📋 Последние ошибки:"
ssh $SSH_KEY $SERVER "tail -20 /var/log/workspace/error.log 2>/dev/null || echo 'Нет логов'"

echo ""
echo "=== Деплой завершён ==="
