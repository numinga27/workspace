"""Сервис вложений: скриншоты в чат и поддержку.

Хранит в UPLOAD_FOLDER с UUID-именем, отдаёт через send_from_directory
с проверкой прав. Whitelist расширений.
"""
import os
import uuid
import mimetypes

from flask import current_app
from werkzeug.utils import secure_filename

from extensions import db
from models import File, FileAccess, User

ALLOWED_EXT = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
    '.pdf', '.txt', '.zip', '.rar', '.7z',
    '.doc', '.docx', '.xls', '.xlsx',
}
MAX_FILE_SIZE = 8 * 1024 * 1024        # 8 MB на файл
MAX_FILES_PER_MESSAGE = 5


def is_allowed(filename: str) -> bool:
    return os.path.splitext(filename or '')[1].lower() in ALLOWED_EXT


def save_attachment(upload, *, uploaded_by: int, project_id=None,
                    message_id=None, support_message_id=None,
                    is_private=False, recipient_ids=None):
    """Сохраняет один файл. НЕ коммитит. Возвращает File или None."""
    if not upload or not upload.filename:
        return None
    if not is_allowed(upload.filename):
        return None

    original_name = secure_filename(upload.filename) or 'file'
    ext = os.path.splitext(original_name)[1].lower()
    stored_name = f'{uuid.uuid4().hex}{ext}'
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)

    upload.save(path)
    size = os.path.getsize(path)
    if size > MAX_FILE_SIZE:
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    mime, _ = mimetypes.guess_type(original_name)
    # Fallback: определяем по расширению вручную
    if not mime:
        ext = os.path.splitext(original_name)[1].lower()
        image_exts = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                      '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp'}
        mime = image_exts.get(ext, 'application/octet-stream')
    f = File(
        original_name=upload.filename,
        stored_name=stored_name,
        file_size=size,
        file_type=mime,
        project_id=project_id,
        message_id=message_id,
        support_message_id=support_message_id,
        uploaded_by=uploaded_by,
        is_private=is_private,
    )
    db.session.add(f)
    db.session.flush()

    if is_private and recipient_ids:
        for raw_uid in recipient_ids:
            try:
                uid = int(raw_uid)
            except (TypeError, ValueError):
                continue
            if uid == uploaded_by:
                continue
            db.session.add(FileAccess(file_id=f.id, user_id=uid))
    return f


def can_view_attachment(file: File, user: User) -> bool:
    """Права на вложение чата/поддержки."""
    if not user or not file:
        return False

    # Приватность (если File.is_private)
    if file.is_private and not file.is_visible_to(user):
        return False

    if file.message_id:
        from utils import check_project_access
        return check_project_access(file.project_id)

    if file.support_message_id:
        if user.role == 'admin':
            return True
        msg = file.support_message
        return bool(msg and msg.ticket and msg.ticket.user_id == user.id)

    # Обычный файл проекта
    if file.project_id:
        from utils import check_project_access
        return check_project_access(file.project_id)
    return False
