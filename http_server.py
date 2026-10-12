import json
import threading
from typing import Callable, Optional, Dict, Any, List, Tuple
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler

from session_validator import validate_session_data, EXAMPLE_SESSION_PAYLOAD


class DictaphoneHTTPHandler(BaseHTTPRequestHandler):
    server: 'HTTPServerWrapper'

    def log_message(self, format, *args):
        # Отключаем дефолтный шум в консоли
        pass

    def _send_json_response(self, status_code: int, data: Dict[str, Any]):
        data["status_code"] = status_code
        if "code" not in data:
            data["code"] = status_code
        response_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        # Поддержка CORS preflight запросов
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        normalized_path = self.path.split("?")[0].rstrip("/").lower()
        if not normalized_path:
            normalized_path = "/"

        if normalized_path in ("/", "/api"):
            self._send_json_response(200, {
                "status": "ok",
                "code": 200,
                "message": "ready",
                "service": "dictaphone",
                "endpoints": {
                    "POST /start": "start",
                    "GET /stop": "stop",
                    "GET /status": "status",
                    "GET /show": "show"
                }
            })
            return

        if normalized_path in ("/status", "/api/status"):
            is_rec = self.server.wrapper.is_recording_func()
            self._send_json_response(200, {
                "status": "ok",
                "code": 200,
                "is_recording": is_rec,
                "message": "recording" if is_rec else "idle"
            })
            return

        if normalized_path in ("/stop", "/api/stop"):
            is_currently_recording = self.server.wrapper.is_recording_func()
            if self.server.wrapper.on_stop_requested:
                self.server.wrapper.on_stop_requested()
            print("[REST API] Stop command received (GET /stop)")
            self._send_json_response(200, {
                "status": "ok",
                "code": 200,
                "is_recording": False,
                "was_recording": is_currently_recording,
                "message": "stopped" if is_currently_recording else "idle"
            })
            return

        if normalized_path in ("/show", "/api/show"):
            if self.server.wrapper.on_show_requested:
                self.server.wrapper.on_show_requested()
            print("[REST API] Show command received (GET /show)")
            self._send_json_response(200, {
                "status": "ok",
                "code": 200,
                "message": "shown"
            })
            return

        self._send_json_response(404, {
            "status": "error",
            "code": 404,
            "error": "NOT_FOUND",
            "message": "not_found"
        })

    def do_POST(self):
        try:
            normalized_path = self.path.split("?")[0].rstrip("/").lower()
            if not normalized_path:
                normalized_path = "/"

            # Поддержка остановки записи через POST /stop
            if normalized_path in ("/stop", "/api/stop"):
                is_currently_recording = self.server.wrapper.is_recording_func()
                if self.server.wrapper.on_stop_requested:
                    self.server.wrapper.on_stop_requested()
                print("[REST API] Stop command received (POST /stop)")
                self._send_json_response(200, {
                    "status": "ok",
                    "code": 200,
                    "is_recording": False,
                    "was_recording": is_currently_recording,
                    "message": "stopped" if is_currently_recording else "idle"
                })
                return

            # Поддержка разворачивания окна через POST /show
            if normalized_path in ("/show", "/api/show"):
                if self.server.wrapper.on_show_requested:
                    self.server.wrapper.on_show_requested()
                print("[REST API] Show command received (POST /show)")
                self._send_json_response(200, {
                    "status": "ok",
                    "code": 200,
                    "message": "shown"
                })
                return

            # Проверяем допустимость маршрута для старта сессии ДО парсинга тела
            is_start_path = normalized_path in ("/", "/start", "/api/start", "/session", "/api/session", "/meeting", "/api/meeting")
            if not is_start_path:
                self._send_json_response(404, {
                    "status": "error",
                    "code": 404,
                    "error": "NOT_FOUND",
                    "message": "not_found"
                })
                return

            # Безопасное чтение заголовка Content-Length
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "INVALID_CONTENT_LENGTH",
                    "message": "invalid"
                })
                return

            if content_length <= 0:
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "EMPTY_BODY",
                    "message": "empty_body",
                    "example": EXAMPLE_SESSION_PAYLOAD
                })
                return

            # Защита от избыточно больших пакетов (лимит 10 МБ)
            if content_length > 10 * 1024 * 1024:
                self._send_json_response(413, {
                    "status": "error",
                    "code": 413,
                    "error": "PAYLOAD_TOO_LARGE",
                    "message": "payload_too_large"
                })
                return

            body = self.rfile.read(content_length)
            if not body or not body.strip():
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "EMPTY_BODY",
                    "message": "empty_body"
                })
                return

            # Разбор тела запроса
            try:
                data = json.loads(body.decode("utf-8"))
            except UnicodeDecodeError:
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "ENCODING_ERROR",
                    "message": "invalid_json"
                })
                return
            except json.JSONDecodeError:
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "INVALID_JSON",
                    "message": "invalid_json"
                })
                return

            # Проверка типа JSON
            if not isinstance(data, dict):
                self._send_json_response(400, {
                    "status": "error",
                    "code": 400,
                    "error": "INVALID_PAYLOAD",
                    "message": "invalid"
                })
                return

            # Поддержка управления командами через тело {"command": "stop"} или {"command": "show"}
            if data.get("command") == "stop" or data.get("action") == "stop":
                is_currently_recording = self.server.wrapper.is_recording_func()
                if self.server.wrapper.on_stop_requested:
                    self.server.wrapper.on_stop_requested()
                print("[REST API] Stop command received from JSON body")
                self._send_json_response(200, {
                    "status": "ok",
                    "code": 200,
                    "is_recording": False,
                    "was_recording": is_currently_recording,
                    "message": "stopped" if is_currently_recording else "idle"
                })
                return

            if data.get("command") == "show" or data.get("action") == "show":
                if self.server.wrapper.on_show_requested:
                    self.server.wrapper.on_show_requested()
                print("[REST API] Show command received from JSON body")
                self._send_json_response(200, {
                    "status": "ok",
                    "code": 200,
                    "message": "shown"
                })
                return

            # Валидация данных сессии
            is_valid, err_msg, normalized_data, missing_fields = validate_session_data(data)

            if not is_valid:
                status_code = 422 if (not data or missing_fields) else 400
                err_code = "MISSING_REQUIRED_FIELDS" if missing_fields else "INVALID_PAYLOAD"
                self._send_json_response(status_code, {
                    "status": "error",
                    "code": status_code,
                    "error": err_code,
                    "missing_fields": missing_fields,
                    "message": "invalid"
                })
                return

            # Проверка занятости (уже идет запись)
            if self.server.wrapper.is_recording_func():
                print("[REST API] Request rejected: recorder busy")
                self._send_json_response(409, {
                    "status": "error",
                    "code": 409,
                    "error": "RECORDER_BUSY",
                    "active_recording": True,
                    "message": "busy"
                })
                return

            print(f"[REST API] New session: id='{normalized_data['id']}', title='{normalized_data['title']}'")
            
            # Запуск записи в приложении через callback
            if self.server.wrapper.on_session_received:
                self.server.wrapper.on_session_received(normalized_data)

            # Ответ 200 OK при успешном старте
            self._send_json_response(200, {
                "status": "ok",
                "code": 200,
                "message": "started",
                "id": normalized_data["id"],
                "title": normalized_data["title"],
                "date": normalized_data["date"],
                "participants_count": len(normalized_data.get("participants", [])),
                "agenda_count": len(normalized_data.get("agenda", []))
            })
            return

        except Exception as e:
            print(f"[REST API] Internal server error: {e}")
            self._send_json_response(500, {
                "status": "error",
                "code": 500,
                "error": "INTERNAL_SERVER_ERROR",
                "message": "error"
            })

    def do_PUT(self):
        self._send_method_not_allowed()

    def do_DELETE(self):
        self._send_method_not_allowed()

    def do_PATCH(self):
        self._send_method_not_allowed()

    def _send_method_not_allowed(self):
        self._send_json_response(405, {
            "status": "error",
            "code": 405,
            "error": "METHOD_NOT_ALLOWED",
            "message": "not_allowed"
        })


class HTTPServerWrapper(ThreadingHTTPServer):
    wrapper: 'RESTServer'
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, wrapper: 'RESTServer'):
        self.wrapper = wrapper
        super().__init__(server_address, RequestHandlerClass)


class RESTServer:
    """
    Легковесный многопоточный HTTP REST сервер для управления диктофоном.
    - POST /start  : передать JSON метаданных совещания и начать запись -> {"status": "ok", "message": "started", ...}
    - GET / POST /stop : остановить текущую запись -> {"status": "ok", "message": "stopped" | "idle", ...}
    - GET  /status : проверить статус записи -> {"status": "ok", "message": "recording" | "idle", ...}
    - GET / POST /show : развернуть окно диктофона из трея -> {"status": "ok", "message": "shown"}
    """
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        on_session_received: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_stop_requested: Optional[Callable[[], None]] = None,
        on_show_requested: Optional[Callable[[], None]] = None,
        is_recording_func: Optional[Callable[[], bool]] = None
    ):
        self.host = host
        self.port = port
        self.on_session_received = on_session_received
        self.on_stop_requested = on_stop_requested
        self.on_show_requested = on_show_requested
        self.is_recording_func = is_recording_func or (lambda: False)

        self._server: Optional[HTTPServerWrapper] = None
        self._thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self) -> bool:
        if self.is_running:
            return True

        ready_event = threading.Event()
        start_error = []

        def run_server():
            try:
                server_address = (self.host, self.port)
                self._server = HTTPServerWrapper(server_address, DictaphoneHTTPHandler, self)
                self.is_running = True
                ready_event.set()
                print(f"[REST Server] HTTP сервер успешно запущен на http://{self.host}:{self.port}")
                self._server.serve_forever()
            except Exception as e:
                start_error.append(str(e))
                ready_event.set()
            finally:
                self.is_running = False

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        ready_event.wait(timeout=3.0)

        if start_error:
            print(f"[REST Server] Ошибка запуска HTTP сервера: {start_error[0]}")
            return False

        return self.is_running

    def stop(self) -> None:
        if not self.is_running and not self._server:
            return
        self.is_running = False
        if self._server:
            try:
                srv = self._server
                self._server = None
                shutdown_thread = threading.Thread(target=srv.shutdown, daemon=True)
                shutdown_thread.start()
                shutdown_thread.join(timeout=2.0)
                srv.server_close()
            except Exception as e:
                print(f"[REST Server] Ошибка остановки сервера: {e}")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
        print("[REST Server] HTTP сервер остановлен")
