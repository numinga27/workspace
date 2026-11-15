#!/bin/bash
set -e

SERVER="root@176.110.16.93"
WORKSPACE="/var/www/workspace"

echo "📦 Deploying chat improvements..."

# Files to deploy
FILES=(
    "templates/project.html"
    "blueprints/chat.py"
    "models.py"
)

for file in "${FILES[@]}"; do
    echo "📤 Uploading $file..."
    scp "$file" "${SERVER}:${WORKSPACE}/$file"
done

echo "🧹 Clearing Python cache..."
ssh "${SERVER}" "cd ${WORKSPACE} && find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true"

echo "🔄 Restarting Gunicorn..."
ssh "${SERVER}": "pkill -9 gunicorn && sleep 2 && systemctl start workspace.service"

echo "✅ Deploy complete!"
