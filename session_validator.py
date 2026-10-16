import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


EXAMPLE_SESSION_PAYLOAD = {
    "id": "мероприятие_312",
    "title": "Обсуждение архитектуры проекта",
    "date": "28/09/2026 12:15",
    "participants": [
        "Иванов И.И.",
        "Петров П.П."
    ],
    "agenda": [
        {
            "question": "Утверждение ТЗ на разработку аудиорекордера",
            "assignee": "Сидоров С.С.",
            "position": "Ведущий программист",
            "department": "Отдел разработки ПО"
        }
    ]
}


def validate_session_data(data: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], List[str]]:
    """
    Валидирует JSON-пакет данных мероприятия на пригодность.
    
    Тест на пригодность:
    1. Корневой элемент должен быть объектом (dict).
    2. Объект не должен быть пустым {}.
    3. Обязательное наличие непустых полей 'id' и 'title'.
       Если полей нет — "JSON не тот".
    4. Поля не синтезируются и не добавляются (исходный JSON не модифицируется).

    Возвращает:
        (is_valid, error_message, raw_data_copy, missing_fields)
    """
    if not isinstance(data, dict):
        type_name = type(data).__name__
        msg = f"JSON не тот: корневой элемент должен быть объектом {{...}}, а получен: {type_name}."
        return False, msg, None, []

    if not data:
        msg = "JSON не тот: передан пустой JSON объект. Обязательны поля 'id' и 'title'."
        return False, msg, None, ["id", "title"]

    missing_fields: List[str] = []

    # 1. Проверка идентификатора 'id'
    raw_id = data.get("id")
    if raw_id is None:
        missing_fields.append("id")
    elif isinstance(raw_id, (dict, list)):
        return False, f"JSON не тот: поле 'id' не должно быть {type(raw_id).__name__}.", None, []
    elif not str(raw_id).strip():
        missing_fields.append("id")

    # 2. Проверка названия мероприятия 'title'
    raw_title = data.get("title")
    if raw_title is None:
        missing_fields.append("title")
    elif isinstance(raw_title, (dict, list)):
        return False, f"JSON не тот: поле 'title' не должно быть {type(raw_title).__name__}.", None, []
    elif not str(raw_title).strip():
        missing_fields.append("title")

    # Если отсутствуют обязательные поля
    if missing_fields:
        fields_desc = ", ".join(f"'{f}'" for f in missing_fields)
        msg = f"JSON не тот: отсутствуют обязательные поля {fields_desc}."
        return False, msg, None, missing_fields

    # Тест на пригодность успешно пройден.
    # Мы не добавляем и не меняем поля пользователя, сохраняя структуру 1:1.
    import copy
    return True, None, copy.deepcopy(data), []

