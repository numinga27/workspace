from urllib.parse import quote
from flask import request, make_response, redirect, url_for, flash

from extensions import WEASYPRINT_AVAILABLE

if WEASYPRINT_AVAILABLE:
    from weasyprint import HTML


def _ascii_fallback(filename):
    """Строит ASCII-безопасный fallback для имени файла.
    Транслит кириллицы → латиница + замена не-ASCII на '_'."""
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya',
    }
    result = []
    for ch in filename:
        if ch in translit_map:
            result.append(translit_map[ch])
        elif ord(ch) < 128:
            result.append(ch)
        else:
            result.append('_')
    return ''.join(result)


def _build_content_disposition(filename):
    """Формирует корректный заголовок Content-Disposition с поддержкой UTF-8.
    Использует RFC 5987: filename= (ASCII) + filename*=UTF-8''<urlencoded>"""
    ascii_name = _ascii_fallback(filename)
    utf8_encoded = quote(filename, safe='')
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_encoded}"


def generate_pdf_response(html_content, filename):
    if not WEASYPRINT_AVAILABLE:
        flash('WeasyPrint не установлен.', 'danger')
        return redirect(request.referrer or url_for('dashboard.dashboard'))

    pdf_bytes = HTML(string=html_content, base_url=request.url_root).write_pdf()

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = _build_content_disposition(filename)
    return response