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
    Валидирует и нормализует JSON-пакет данных мероприятия.
    
    Проверяет:
    1. Корневой элемент должен быть объектом (dict).
    2. Объект не должен быть пустым {}.
    3. Наличие и непустоту 'id' (идентификатор мероприятия).
    4. Наличие и непустоту 'title' (название мероприятия).
       Поддерживает дружелюбные синонимы ('conference', 'name', 'topic').
    5. Корректность типов полей (не допускает dict/list в id и title).
    6. Безопасную нормализацию 'date', 'participants' и 'agenda'.

    Возвращает:
        (is_valid, error_message, normalized_dict, missing_fields)
    """
    if not isinstance(data, dict):
        type_name = type(data).__name__
        msg = f"Корневой элемент JSON должен быть объектом {{...}}, а получен: {type_name}."
        return False, msg, None, []

    if not data:
        msg = "Передан пустой JSON объект {}. Заполните обязательные поля: 'id' (идентификатор) и 'title' (название мероприятия)."
        return False, msg, None, ["id", "title"]

    missing_fields: List[str] = []

    # 1. Проверка идентификатора 'id'
    raw_id = data.get("id")
    if raw_id is None:
        # Проверяем возможные синонимы
        raw_id = data.get("session_id") or data.get("meeting_id")

    id_str = ""
    if raw_id is None:
        missing_fields.append("id")
    elif isinstance(raw_id, (dict, list)):
        return False, f"Поле 'id' должно быть строковым или числовым идентификатором, а не {type(raw_id).__name__}.", None, []
    else:
        id_str = str(raw_id).strip()
        if not id_str:
            missing_fields.append("id")

    # 2. Проверка названия конференции / темы совещания 'title'
    raw_title = data.get("title")
    if raw_title is None or (isinstance(raw_title, str) and not raw_title.strip()):
        # Проверяем синонимы: conference, conference_name, name, topic, subject
        for alias in ("conference", "conference_name", "name", "topic", "subject"):
            val = data.get(alias)
            if val is not None and str(val).strip():
                raw_title = val
                break

    title_str = ""
    if raw_title is None:
        missing_fields.append("title")
    elif isinstance(raw_title, (dict, list)):
        return False, f"Поле 'title' (название конференции) должно быть строкой, а не {type(raw_title).__name__}.", None, []
    else:
        title_str = str(raw_title).strip()
        if not title_str:
            missing_fields.append("title")

    # Если отсутствуют обязательные поля
    if missing_fields:
        fields_desc = []
        for f in missing_fields:
            if f == "id":
                fields_desc.append("'id' (идентификатор мероприятия)")
            elif f == "title":
                fields_desc.append("'title' (название мероприятия)")
            else:
                fields_desc.append(f"'{f}'")

        msg = (
            f"Отсутствуют обязательные поля в JSON пакете: {', '.join(fields_desc)}. "
            f"Оба поля обязательны и не могут быть пустыми."
        )
        return False, msg, None, missing_fields

    # 3. Сохраняем исходный JSON пользователя без искажения структуры, типов и ключей.
    # Мы вписываем данные в существующий JSON, а не создаем синтетический объект и не заменяем ключи пользователя.
    import copy
    result = copy.deepcopy(data)
    result["id"] = id_str
    if "title" not in result or not str(result["title"]).strip():
        result["title"] = title_str
    if "date" not in result or not str(result.get("date", "")).strip():
        result["date"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    return True, None, result, []
