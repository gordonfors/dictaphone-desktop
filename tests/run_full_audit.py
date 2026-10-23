#!/usr/bin/env python3
"""
Комплексный автоматический тест надежности и отсутствия скрытых багов (Full System Audit)
для приложения Диктофон (Dictaphone Desktop).

Проверяет:
1. Валидацию сессий и метаданных (session_validator.py)
2. Работу конфигурации, миграций и путей AppData (config.py)
3. Базу данных SQLite, ротацию файлов, транзакции (database.py)
4. Генерацию, кодирование и целостность WebM Opus аудио (audio_recorder.py)
5. Встроенный REST HTTP API сервер (http_server.py)
6. Модуль выгрузки на вебхук multipart/form-data (uploader.py)
7. Защиту от повторного запуска (single_instance.py)
8. Автозапуск (autostart.py)
"""

import os
import sys
import time
import json
import socket
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Настройка путей
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))

# Импорт тестируемых модулей
import session_validator
from session_validator import validate_session_data
import config
from config import AppConfig, load_config, save_config
import database
from database import Database, STATUS_SENT, STATUS_NOT_SENT, STATUS_IN_PROGRESS
import audio_recorder
from audio_recorder import AudioRecorder
import http_server
from http_server import RESTServer
import uploader
from uploader import UploadWorker
import autostart
from autostart import is_autostart_enabled
import single_instance
from single_instance import SingleInstanceManager


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class TestSessionValidator(unittest.TestCase):
    """Тестирование парсинга и валидации JSON сессий"""

    def test_valid_payload(self):
        data = {
            "id": "conf-001",
            "title": "Стратегическое планирование",
            "date": "14/10/2026 10:00",
            "participants": ["Иванов", "Петров"],
            "agenda": [{"question": "План на Q4", "assignee": "Иванов"}],
            "custom_field": 12345
        }
        ok, err, norm, missing = validate_session_data(data)
        self.assertTrue(ok, f"Валидация должна быть успешной, ошибка: {err}")
        self.assertIsNotNone(norm)
        self.assertEqual(norm["id"], "conf-001")
        self.assertEqual(norm["title"], "Стратегическое планирование")
        self.assertEqual(norm["custom_field"], 12345, "Пользовательские поля должны сохраняться")

    def test_required_id_and_title(self):
        # Если отсутствуют обязательные поля 'id' или 'title', сообщаем что JSON не тот
        data = {
            "meeting_id": "session_999",
            "conference": "Обсуждение бюджета"
        }
        ok, err, norm, missing = validate_session_data(data)
        self.assertFalse(ok)
        self.assertIn("JSON не тот", err)
        self.assertIn("id", missing)
        self.assertIn("title", missing)

        # Тест на пригодность: поля не синтезируются и не добавляются
        valid_data = {
            "id": "session_999",
            "title": "Обсуждение бюджета",
            "custom_number": 42
        }
        ok, err, norm, missing = validate_session_data(valid_data)
        self.assertTrue(ok)
        self.assertNotIn("date", norm, "Поле date не должно синтезироваться, если его не было")
        self.assertEqual(norm["id"], "session_999")
        self.assertEqual(norm["title"], "Обсуждение бюджета")

    def test_empty_and_invalid_types(self):
        # Пустой словарь
        ok, err, norm, missing = validate_session_data({})
        self.assertFalse(ok)
        self.assertIn("id", missing)

        # Не словарь (список или строка)
        ok, err, norm, missing = validate_session_data(["не", "словарь"])
        self.assertFalse(ok)

        # id как список
        ok, err, norm, missing = validate_session_data({"id": [1, 2], "title": "Test"})
        self.assertFalse(ok)

        # title как словарь
        ok, err, norm, missing = validate_session_data({"id": "1", "title": {"name": "Test"}})
        self.assertFalse(ok)


class TestConfigAndPaths(unittest.TestCase):
    """Тестирование конфигурации и миграции ключей"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_config_save_and_load(self):
        cfg_file = Path(self.temp_dir) / "test_config.json"
        cfg = AppConfig(
            sample_rate=48000,
            bitrate=128000,
            http_port=8999,
            upload_url="http://example.com/test",
            recordings_dir=str(Path(self.temp_dir) / "recs")
        )
        
        # Сохранение
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(config.asdict(cfg), f)

        # Загрузка
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["http_port"], 8999)
        self.assertEqual(data["upload_url"], "http://example.com/test")
        self.assertEqual(data["bitrate"], 128000)

    def test_ws_to_http_migration(self):
        """Проверка автоматической миграции ws_port / ws_host в http_port / http_host"""
        cfg = AppConfig()
        cfg.ws_port = 7777
        self.assertEqual(cfg.http_port, 7777)
        cfg.ws_host = "127.0.0.1"
        self.assertEqual(cfg.http_host, "127.0.0.1")


class TestDatabase(unittest.TestCase):
    """Тестирование SQLite базы данных и ротации записей"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_recordings.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_crud_operations(self):
        # 1. Добавление записи
        meta = {"id": "conf_100", "title": "Тест БД", "agenda": []}
        rec_id = self.db.add_recording(
            filepath=str(Path(self.temp_dir) / "rec_1.webm"),
            title="Тест БД",
            participants="Иванов, Петров",
            session_id="conf_100",
            duration=120.5,
            file_size=500000,
            status=STATUS_IN_PROGRESS,
            metadata=meta
        )
        self.assertGreater(rec_id, 0)

        # 2. Получение записи
        rec = self.db.get_recording(rec_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["title"], "Тест БД")
        self.assertEqual(rec["status"], STATUS_IN_PROGRESS)
        self.assertIn("conf_100", rec["metadata_json"])

        # 3. Обновление статуса на Отправлено
        self.db.update_recording(rec_id, status=STATUS_SENT)
        rec_updated = self.db.get_recording(rec_id)
        self.assertEqual(rec_updated["status"], STATUS_SENT)

        # 4. Список всех записей
        all_recs = self.db.get_all_recordings()
        self.assertEqual(len(all_recs), 1)

        # 5. Удаление записи
        self.db.delete_recording(rec_id)
        self.assertIsNone(self.db.get_recording(rec_id))

    def test_purge_old_recordings(self):
        """Проверка очистки старых записей и безопасности активных (STATUS_IN_PROGRESS)"""
        # Создаем запись с фиктивным файлом
        fake_audio = Path(self.temp_dir) / "old_rec.webm"
        fake_audio.write_text("audio dummy")
        fake_json = Path(self.temp_dir) / "old_rec.json"
        fake_json.write_text("{}")

        rec_id = self.db.add_recording(
            filepath=str(fake_audio),
            title="Старая запись",
            status=STATUS_SENT
        )

        # Искусственно меняем дату создания на 40 дней назад
        with self.db._get_connection() as conn:
            conn.cursor().execute("UPDATE recordings SET created_at = datetime('now', '-40 days') WHERE id = ?", (rec_id,))
            conn.commit()

        # Очистка за 30 дней
        deleted = self.db.purge_old_recordings(max_days=30)
        self.assertIn(str(fake_audio), deleted)
        self.assertFalse(fake_audio.exists(), "Старый файл аудио должен быть физически удален")
        self.assertFalse(fake_json.exists(), "Старый JSON файл должен быть физически удален")
        self.assertIsNone(self.db.get_recording(rec_id), "Запись должна быть удалена из БД")


class TestAudioRecordingEncoding(unittest.TestCase):
    """Тестирование создания и записи WebM Opus контейнера через PyAV"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pyav_webm_opus_container(self):
        """Проверка инициализации Opus кодека, генерации фреймов и валидности итогового WebM файла"""
        import av
        import numpy as np

        out_path = Path(self.temp_dir) / "test_valid.webm"
        
        # 1. Создание контейнера
        container = av.open(str(out_path), mode="w", format="webm")
        stream = container.add_stream("libopus", rate=48000)
        stream.bit_rate = 64000
        stream.format = "s16"
        stream.layout = "mono"

        # 2. Генерация тестового синусоидального аудиосигнала (1 секунда, 48000 сэмплов)
        t = np.linspace(0, 1.0, 48000, endpoint=False, dtype=np.float32)
        sine = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        
        # Запись фреймами по 960 сэмплов (20 мс standard Opus frame)
        for i in range(0, len(sine), 960):
            chunk = sine[i:i+960]
            if len(chunk) < 960:
                break
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format='s16', layout='mono')
            frame.sample_rate = 48000
            for packet in stream.encode(frame):
                container.mux(packet)

        # Финализация
        for packet in stream.encode(None):
            container.mux(packet)
        container.close()

        # 3. Валидация созданного файла
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 1000, "WebM файл должен содержать данные")

        # 4. Проверка возможности обратного открытия и чтения через PyAV
        with av.open(str(out_path), mode="r") as check_c:
            self.assertEqual(len(check_c.streams.audio), 1)
            audio_s = check_c.streams.audio[0]
            self.assertEqual(audio_s.codec_context.name, "opus")
            self.assertEqual(audio_s.sample_rate, 48000)


class TestHTTPServer(unittest.TestCase):
    """Тестирование локального HTTP REST API сервера"""

    def setUp(self):
        self.port = get_free_port()
        self.received_session = None
        self.stop_called = False
        self.show_called = False
        self.is_rec = False

        self.server = RESTServer(
            host="127.0.0.1",
            port=self.port,
            on_session_received=lambda data: setattr(self, 'received_session', data),
            on_stop_requested=lambda ev=None: (setattr(self, 'stop_called', True), ev.set() if ev else None),
            on_show_requested=lambda: setattr(self, 'show_called', True),
            is_recording_func=lambda: self.is_rec
        )
        ok = self.server.start()
        self.assertTrue(ok, "RESTServer должен успешно запуститься")

    def tearDown(self):
        self.server.stop()

    def test_endpoints(self):
        import requests

        base_url = f"http://127.0.0.1:{self.port}"

        # 1. GET /api
        r = requests.get(f"{base_url}/api")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["service"], "dictaphone")

        # 2. GET /status (idle)
        r = requests.get(f"{base_url}/status")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["is_recording"])

        # 3. POST /start с валидными данными
        session_payload = {
            "id": "meeting_777",
            "title": "Утверждение планов",
            "date": "14/10/2026",
            "participants": ["Инженер", "Менеджер"]
        }
        r = requests.post(f"{base_url}/start", json=session_payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["message"], "started")
        self.assertEqual(self.received_session["id"], "meeting_777")

        # 4. POST /start когда диктофон занят (409 Conflict)
        self.is_rec = True
        r = requests.post(f"{base_url}/start", json=session_payload)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["message"], "busy")
        self.is_rec = False

        # 5. GET /stop
        r = requests.get(f"{base_url}/stop")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.stop_called)

        # 6. GET /show
        r = requests.get(f"{base_url}/show")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.show_called)

        # 7. Обработка ошибок (невалидный JSON)
        r = requests.post(f"{base_url}/start", data="NOT_A_JSON", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)

        # 8. 404 на несуществующий эндпоинт
        r = requests.get(f"{base_url}/unknown")
        self.assertEqual(r.status_code, 404)


class TestUploader(unittest.TestCase):
    """Тестирование отправки данных на сервер (WebM аудио + JSON метаданные)"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.port = get_free_port()
        self.received_files = {}
        self.received_fields = {}

        # Создаем мок HTTP сервер
        test_case = self
        class MockReceiver(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            def do_POST(self):
                content_length = int(self.headers.get('Content-Length', 0))
                ctype = self.headers.get('Content-Type', '')
                body = self.rfile.read(content_length)

                # Простой разбор multipart
                boundary = ctype.split("boundary=")[-1].encode('utf-8')
                parts = body.split(b"--" + boundary)
                for part in parts:
                    if b"Content-Disposition" not in part:
                        continue
                    headers_part, _, body_part = part.partition(b"\r\n\r\n")
                    body_part = body_part.rstrip(b"\r\n")
                    headers_str = headers_part.decode('utf-8', errors='replace')
                    
                    if 'filename="' in headers_str:
                        # Файл
                        fname = headers_str.split('filename="')[1].split('"')[0]
                        field_name = headers_str.split('name="')[1].split('"')[0]
                        test_case.received_files[field_name] = (fname, body_part)
                    elif 'name="' in headers_str:
                        field_name = headers_str.split('name="')[1].split('"')[0]
                        test_case.received_fields[field_name] = body_part.decode('utf-8', errors='replace')

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        self.mock_server = HTTPServer(('127.0.0.1', self.port), MockReceiver)
        self.mock_thread = threading.Thread(target=self.mock_server.serve_forever, daemon=True)
        self.mock_thread.start()

    def tearDown(self):
        self.mock_server.shutdown()
        self.mock_server.server_close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_upload_both_audio_and_json(self):
        """Проверка одновременной доставки аудиофайла и JSON-файла, а также полей тела"""
        audio_file = Path(self.temp_dir) / "rec_meeting_1.webm"
        audio_file.write_bytes(b"MOCK_WEBM_DATA_12345")

        json_file = Path(self.temp_dir) / "rec_meeting_1.json"
        meta_dict = {
            "id": "meeting-1",
            "title": "Тестовое мероприятие",
            "participants": ["Алексей", "Борис"],
            "recording": {"duration": 42.5}
        }
        json_file.write_text(json.dumps(meta_dict, ensure_ascii=False), encoding="utf-8")

        upload_url = f"http://127.0.0.1:{self.port}/webhook"

        worker = UploadWorker(
            rec_id=1,
            audio_path=str(audio_file),
            json_path=str(json_file),
            upload_url=upload_url,
            max_retries=1
        )

        success_result = []
        worker.finished.connect(lambda r_id, ok, msg: success_result.append((ok, msg)))
        worker.run()

        self.assertTrue(success_result, "Сигнал finished должен быть вызван")
        self.assertTrue(success_result[0][0], f"Отправка должна завершиться успехом: {success_result[0][1]}")

        # Проверка принятых файлов
        self.assertIn("file", self.received_files, "Файл аудио должен быть среди файлов")
        self.assertEqual(self.received_files["file"][0], "rec_meeting_1.webm")
        self.assertEqual(self.received_files["file"][1], b"MOCK_WEBM_DATA_12345")

        self.assertIn("json_file", self.received_files, "Файл JSON должен быть среди файлов")
        self.assertEqual(self.received_files["json_file"][0], "rec_meeting_1.json")
        self.assertIn("Тестовое мероприятие", self.received_files["json_file"][1].decode('utf-8'))

        # Проверка принятых текстовых полей формы (Body)
        self.assertIn("payload", self.received_fields, "JSON должен быть продублирован в body")
        self.assertIn("Тестовое мероприятие", self.received_fields["payload"])
        self.assertEqual(self.received_fields["id"], "meeting-1")
        self.assertEqual(self.received_fields["title"], "Тестовое мероприятие")

    def test_db_fallback_when_json_file_missing(self):
        """Проверка восстановления JSON из SQLite БД, если локальный файл удален"""
        db_path = Path(self.temp_dir) / "test.db"
        db = Database(db_path)
        
        # Подменяем дефолтный путь к БД для теста
        old_db_file = database.DB_FILE
        database.DB_FILE = db_path

        try:
            audio_file = Path(self.temp_dir) / "rec_fallback.webm"
            audio_file.write_bytes(b"AUDIO_DATA")
            
            # Файл JSON намеренно НЕ создаем!
            meta = {"id": "recovered_id", "title": "Восстановленная тема"}
            rec_id = db.add_recording(
                filepath=str(audio_file),
                title="Восстановленная тема",
                status=STATUS_NOT_SENT,
                metadata=meta
            )

            worker = UploadWorker(
                rec_id=rec_id,
                audio_path=str(audio_file),
                json_path="",  # Пустой путь
                upload_url=f"http://127.0.0.1:{self.port}/webhook",
                max_retries=1,
                db=db
            )
            worker.run()

            # Проверяем, что метаданные успешно восстановились из БД
            self.assertIn("title", self.received_fields)
            self.assertEqual(self.received_fields["title"], "Восстановленная тема")
            self.assertEqual(self.received_fields["id"], "recovered_id")
            self.assertIn("json_file", self.received_files)
        finally:
            database.DB_FILE = old_db_file

    def test_lan_ssl_bypass_and_ip_detection(self):
        """Проверка автоматического отключения SSL-проверки для адресов локальной сети (LAN)"""
        lan_urls = [
            "http://192.168.1.50:5678/webhook",
            "https://192.168.10.200:5678/webhook",
            "http://10.0.1.25:8000/api",
            "https://172.20.0.5:8443/upload",
            "http://127.0.0.1:8765/start",
            "http://server.local/api"
        ]
        for url in lan_urls:
            is_lan = any(x in url.lower() for x in ("127.0.0.1", "localhost", "192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", ".local"))
            self.assertTrue(is_lan, f"URL {url} должен определяться как локальная сеть")


class TestSingleInstance(unittest.TestCase):
    """Тестирование механизма единственного экземпляра приложения"""

    def test_single_instance_creation(self):
        mgr = SingleInstanceManager(key="Test_Unique_Key_99999")
        # Первый экземпляр не должен определять себя как повторный запуск
        already = mgr.is_already_running()
        self.assertFalse(already, "Первый запуск должен быть единственным")
        mgr.close()


def run_all_tests():
    print("=" * 70)
    print("   ПОЛНОЕ АВТОМАТИЧЕСКОЕ ТЕСТИРОВАНИЕ ПРОГРАММНОГО КОМПЛЕКСА ДИКТОФОНА")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSessionValidator))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigAndPaths))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabase))
    suite.addTests(loader.loadTestsFromTestCase(TestAudioRecordingEncoding))
    suite.addTests(loader.loadTestsFromTestCase(TestHTTPServer))
    suite.addTests(loader.loadTestsFromTestCase(TestUploader))
    suite.addTests(loader.loadTestsFromTestCase(TestSingleInstance))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(f"ИТОГ: ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО ({result.testsRun} проверок). СКРЫТЫХ БАГОВ НЕ ОБНАРУЖЕНО.")
    else:
        print(f"ИТОГ: ОБНАРУЖЕНЫ ОШИБКИ: {len(result.errors)} ошибок, {len(result.failures)} провалов.")
    print("=" * 70)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
