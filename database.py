import sqlite3
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

from config import APP_DATA_DIR

DB_FILE = APP_DATA_DIR / "recordings.db"

STATUS_SENT = "Отправлено"
STATUS_NOT_SENT = "Не отправлено"
STATUS_IN_PROGRESS = "В процессе"

class Database:
    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self._conn = None
        self._lock = threading.RLock()
        self.init_db()

    def _get_connection_obj(self):
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    @contextmanager
    def _get_connection(self):
        with self._lock:
            try:
                yield self._get_connection_obj()
            except Exception:
                if self._conn:
                    self._conn.rollback()
                raise

    def init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    title TEXT NOT NULL,
                    participants TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration REAL DEFAULT 0.0,
                    filepath TEXT NOT NULL,
                    json_filepath TEXT DEFAULT '',
                    file_size INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Не отправлено',
                    metadata_json TEXT
                )
            """)
            conn.commit()

            # Ensure columns exist for already existing databases
            cursor.execute("PRAGMA table_info(recordings)")
            columns = [row[1] for row in cursor.fetchall()]
            if "participants" not in columns:
                cursor.execute("ALTER TABLE recordings ADD COLUMN participants TEXT DEFAULT ''")
                conn.commit()
            if "json_filepath" not in columns:
                cursor.execute("ALTER TABLE recordings ADD COLUMN json_filepath TEXT DEFAULT ''")
                conn.commit()

            # Normalize any legacy status values and reset stuck IN_PROGRESS
            cursor.execute("UPDATE recordings SET status = 'Не отправлено' WHERE status IN ('Локально', 'Ошибка')")
            cursor.execute("UPDATE recordings SET status = ? WHERE status = ?", (STATUS_NOT_SENT, STATUS_IN_PROGRESS))
            conn.commit()

    def add_recording(
        self,
        filepath: str,
        title: str = "Аудиозапись",
        participants: str = "",
        session_id: Optional[str] = None,
        duration: float = 0.0,
        file_size: int = 0,
        status: str = STATUS_IN_PROGRESS,
        metadata: Optional[Dict[str, Any]] = None,
        json_filepath: Optional[str] = None
    ) -> int:
        metadata_dict = metadata or {}
        if participants and "participants" not in metadata_dict:
            metadata_dict["participants"] = participants
        metadata_str = json.dumps(metadata_dict, ensure_ascii=False)
        j_path = json_filepath or str(Path(filepath).with_suffix(".json"))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO recordings (session_id, title, participants, duration, filepath, json_filepath, file_size, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id or f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                title,
                participants,
                duration,
                filepath,
                j_path,
                file_size,
                status,
                metadata_str
            ))
            conn.commit()
            return cursor.lastrowid

    def update_recording(
        self,
        rec_id: int,
        title: Optional[str] = None,
        duration: Optional[float] = None,
        file_size: Optional[int] = None,
        status: Optional[str] = None,
        json_filepath: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if duration is not None:
            updates.append("duration = ?")
            params.append(duration)
        if file_size is not None:
            updates.append("file_size = ?")
            params.append(file_size)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if json_filepath is not None:
            updates.append("json_filepath = ?")
            params.append(json_filepath)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        
        if not updates:
            return

        params.append(rec_id)
        sql = f"UPDATE recordings SET {', '.join(updates)} WHERE id = ?"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()

    def get_all_recordings(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Ограничиваем выборку последних 200 записей для защиты ОЗУ и UI от переполнения
            cursor.execute("SELECT * FROM recordings ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_recording(self, rec_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_recording(self, rec_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
            conn.commit()

    def purge_old_recordings(self, max_days: int) -> List[str]:
        """
        Deletes database rows older than max_days and returns list of filepaths to delete.
        Called on app startup and before starting a new recording session.
        """
        if max_days <= 0:
            return []

        cutoff_date = datetime.now() - timedelta(days=max_days)
        deleted_files = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, filepath, json_filepath FROM recordings WHERE created_at < ? AND status != ?",
                (cutoff_date.strftime("%Y-%m-%d %H:%M:%S"), STATUS_IN_PROGRESS)
            )
            rows = cursor.fetchall()
            ids_to_del = []
            for row in rows:
                ids_to_del.append(row["id"])
                if row["filepath"]:
                    deleted_files.append(row["filepath"])
                if row["json_filepath"]:
                    deleted_files.append(row["json_filepath"])

            if ids_to_del:
                placeholders = ",".join("?" * len(ids_to_del))
                cursor.execute(f"DELETE FROM recordings WHERE id IN ({placeholders})", ids_to_del)
                conn.commit()

        # Delete physical files (.webm and .json) safely
        for fp in set(deleted_files):
            try:
                p = Path(fp)
                if p.exists() and p.is_file():
                    p.unlink()
                p_json = p.with_suffix(".json")
                if p_json.exists() and p_json.is_file():
                    p_json.unlink()
            except Exception as e:
                with open("app_errors.log", "a", encoding="utf-8") as err_log:
                    err_log.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [DB] Error removing old file {fp}: {e}\n")
                print(f"[DB] Error removing old file {fp}: {e}")

        return deleted_files
