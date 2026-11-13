"""
Telegram Bot Singleton Lock Manager & Process Supervisor
Ensures only ONE single bot instance polls the Telegram updates at any time,
preventing authorization token collision, 409 Conflict errors, and race conditions.
"""
import os
import sys
import time
import json
import logging
import fcntl

logger = logging.getLogger("telegram_singleton")

LOCK_FILE = "/opt/data/telegram_bot.lock" if os.path.exists("/opt/data") else os.path.join(os.getcwd(), "data", "telegram_bot.lock")

class TelegramSingletonLock:
    def __init__(self, lock_path: str = LOCK_FILE):
        self.lock_path = lock_path
        self._fp = None
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)

    def acquire(self) -> bool:
        """
        Attempts to acquire an exclusive non-blocking lock.
        Returns True if acquired, False if another instance is already running.
        """
        try:
            self._fp = open(self.lock_path, "w")
            if sys.platform != "win32":
                fcntl.flock(self._fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            payload = {
                "pid": os.getpid(),
                "acquired_at": time.time(),
                "instance": "ArchonOS_Telegram_Singleton"
            }
            self._fp.seek(0)
            json.dump(payload, self._fp)
            self._fp.flush()
            return True
        except (IOError, OSError):
            if self._fp:
                try:
                    self._fp.close()
                except Exception:
                    pass
            return False

    def release(self):
        """Releases the lock."""
        try:
            if self._fp:
                if sys.platform != "win32":
                    fcntl.flock(self._fp, fcntl.LOCK_UN)
                self._fp.close()
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except Exception as e:
            logger.warning("Error releasing Telegram lock: %s", e)

telegram_lock = TelegramSingletonLock()
