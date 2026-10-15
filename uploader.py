import os
import json
import time
from pathlib import Path
from typing import Optional, Any
import requests
import urllib3
from PyQt6.QtCore import QThread, pyqtSignal

# Подавляем предупреждения при работе с локальными самоподписанными HTTPS-сертификатами
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UploadWorker(QThread):
    progress = pyqtSignal(int, str)       # rec_id, status_text
    finished = pyqtSignal(int, bool, str) # rec_id, success, message

    def __init__(
        self,
        rec_id: int,
        audio_path: str,
        json_path: str,
        upload_url: str,
        max_retries: int = 5,
        verify_ssl: bool = False,
        db: Optional[Any] = None
    ):
        super().__init__()
        self.rec_id = rec_id
        self.audio_path = audio_path
        self.json_path = json_path
        self.max_retries = max(1, max_retries)
        self.verify_ssl = verify_ssl
        self.db = db
        self._is_stopped = False

        # Автоматическое определение и нормализация протокола (HTTP / HTTPS)
        raw_url = upload_url.strip()
        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            # Если протокол не указан явно:
            if ":443" in raw_url or "https" in raw_url.lower():
                self.upload_url = "https://" + raw_url
            else:
                self.upload_url = "http://" + raw_url
        else:
            self.upload_url = raw_url

        self.is_https = self.upload_url.lower().startswith("https://")

    def stop(self) -> None:
        """Безопасная отмена фоновой отправки при закрытии приложения."""
        self._is_stopped = True

    def run(self):
        protocol_tag = "HTTPS" if self.is_https else "HTTP"
        print(f"[Uploader] Старт выгрузки на {self.upload_url} [Протокол: {protocol_tag}]")

        if not self.upload_url or not self.upload_url.startswith("http"):
            self.finished.emit(self.rec_id, False, "Не задан корректный URL для отправки")
            return

        audio_file = Path(self.audio_path)
        if not audio_file.is_file():
            self.finished.emit(self.rec_id, False, f"Аудиофайл не найден: {audio_file.name}")
            return

        try:
            with open(audio_file, "rb") as fa:
                audio_bytes = fa.read()
        except Exception as e:
            self.finished.emit(self.rec_id, False, f"Ошибка чтения аудиофайла: {e}")
            return

        # Надежное определение пути к JSON файлу
        json_file = Path(self.json_path) if self.json_path else audio_file.with_suffix(".json")
        if not json_file.is_file():
            fallback_json = audio_file.with_suffix(".json")
            if fallback_json.is_file():
                json_file = fallback_json

        json_content = ""
        json_data = {}
        if json_file.is_file():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    json_content = f.read()
                    json_data = json.loads(json_content)
            except Exception as e:
                print(f"[Uploader] Ошибка чтения json файла: {e}")

        # Если JSON пустой или файл не найден, восстанавливаем метаданные из SQLite БД
        if (not json_content or not json_data) and self.rec_id:
            try:
                from database import Database
                db = self.db or Database()
                rec = db.get_recording(self.rec_id)
                if rec and rec.get("metadata_json"):
                    json_content = rec["metadata_json"]
                    try:
                        json_data = json.loads(json_content)
                    except Exception:
                        pass
                    print(f"[Uploader] Метаданные JSON успешно восстановлены из БД для записи #{self.rec_id}")
                    # Сохраняем файл на диск рядом с аудио
                    try:
                        target_json = audio_file.with_suffix(".json")
                        with open(target_json, "w", encoding="utf-8") as f:
                            f.write(json_content)
                        json_file = target_json
                    except Exception:
                        pass
            except Exception as ex:
                print(f"[Uploader] Ошибка извлечения метаданных из БД: {ex}")

        # Если даже в БД не было метаданных, формируем базовый JSON
        if not json_data:
            json_data = {
                "id": f"rec_{self.rec_id}",
                "title": audio_file.stem,
                "recording": {
                    "filename": audio_file.name,
                    "file_size": len(audio_bytes)
                }
            }
            json_content = json.dumps(json_data, ensure_ascii=False, indent=2)

        json_bytes = json_content.encode("utf-8")
        json_filename = json_file.name if (json_file and json_file.is_file()) else f"{audio_file.stem}.json"

        # Мультипарт файлы: отправляем и аудиозапись, и JSON-файл (как в старых версиях)
        files = {
            "audio": (audio_file.name, audio_bytes, "audio/webm"),
            "file": (audio_file.name, audio_bytes, "audio/webm"),
            "json": (json_filename, json_bytes, "application/json"),
            "json_file": (json_filename, json_bytes, "application/json"),
        }

        # Тело запроса (Form Data): также передаем JSON строкой в body для вебхуков
        data = {
            "json": json_content,
            "metadata": json_content,
            "data": json_content,
            "payload": json_content,
            "id": str(json_data.get("id", "")),
            "session_id": str(json_data.get("id", "")),
            "title": str(json_data.get("title", "")),
            "date": str(json_data.get("date", "")),
            "duration": str(json_data.get("recording", {}).get("duration", 0)),
            "file_size": str(len(audio_bytes)),
            "participants": json.dumps(json_data.get("participants", []), ensure_ascii=False)
                if isinstance(json_data.get("participants"), list)
                else str(json_data.get("participants", "")),
            "agenda": json.dumps(json_data.get("agenda", []), ensure_ascii=False)
                if isinstance(json_data.get("agenda"), list)
                else str(json_data.get("agenda", "")),
            "recording": json.dumps(json_data.get("recording", {}), ensure_ascii=False)
                if isinstance(json_data.get("recording"), dict)
                else str(json_data.get("recording", ""))
        }

        # Дополнительно передаем все остальные поля из исходного JSON на верхний уровень form-data
        for k, v in json_data.items():
            if k not in data:
                if isinstance(v, (dict, list)):
                    data[k] = json.dumps(v, ensure_ascii=False)
                else:
                    data[k] = str(v)

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            if self._is_stopped:
                return

            try:
                self.progress.emit(self.rec_id, f"Отправка {protocol_tag} ({attempt}/{self.max_retries})...")
                
                # Для локальных сетей (192.168.x, 10.x, localhost) публичные сертификаты неприменимы
                is_lan = any(x in self.upload_url.lower() for x in ("127.0.0.1", "localhost", "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", ".local"))
                current_verify = False if is_lan else self.verify_ssl

                # Оптимизация для локальной сети:
                # 1. Быстрый connect-таймаут (5с) чтобы не виснуть, если LAN-хост выключен, и щедрый read-таймаут (120с) для передачи больших файлов
                timeout_val = (5, 120) if is_lan else (10, 60)
                
                # 2. В локальной сети отключаем системные прокси (trust_env=False), чтобы Windows VPN/прокси не перехватывал локальные IP (192.168.x.x)
                session = requests.Session()
                if is_lan:
                    session.trust_env = False

                response = None
                try:
                    response = session.post(
                        self.upload_url,
                        files=files,
                        data=data,
                        timeout=timeout_val,
                        verify=current_verify
                    )
                except requests.exceptions.SSLError as ssl_err:
                    print(f"[Uploader] Обнаружен самоподписанный SSL сертификат в локальной сети: {ssl_err}. Повтор без проверки сертификата...")
                    self.progress.emit(self.rec_id, f"HTTPS (самоподписанный SSL, попытка {attempt})...")
                    self.verify_ssl = False
                    response = session.post(
                        self.upload_url,
                        files=files,
                        data=data,
                        timeout=timeout_val,
                        verify=False
                    )
                finally:
                    session.close()
                
                if response is not None:
                    if 200 <= response.status_code < 300:
                        response.close()
                        self.finished.emit(self.rec_id, True, f"Успешно отправлено ({protocol_tag})")
                        return
                    else:
                        last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                        response.close()
            except Exception as e:
                last_error = str(e)
                print(f"[Uploader] Попытка {attempt}/{self.max_retries} завершилась с ошибкой: {e}")

            if attempt < self.max_retries:
                # Нарастающий интервал ожидания: 2с, 4с, 6с, 8с...
                # Спим короткими тактами с быстрой реакцией на отмену
                backoff = 2.0 * attempt
                steps = int(backoff * 10)
                for _ in range(steps):
                    if self._is_stopped:
                        return
                    time.sleep(0.1)

        if not self._is_stopped:
            self.finished.emit(self.rec_id, False, f"Ошибка сети ({protocol_tag}): {last_error}")
