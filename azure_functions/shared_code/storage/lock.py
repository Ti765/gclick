import os
import time
from pathlib import Path


class FileLock:
    """Lock simples baseado em arquivo para evitar execuções concorrentes.

    Uso:
        from storage.lock import FileLock
        with FileLock('storage/notification.lock', timeout=30):
            # seção crítica
    """

    def __init__(self, path: str | os.PathLike, timeout: int = 30, poll_interval: float = 0.2):
        self.lock_path = Path(path)
        self.timeout = timeout
        self.poll_interval = poll_interval

    def __enter__(self):
        start = time.time()
        while True:
            try:
                # O_CREAT|O_EXCL garante falha se já existir.
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() - start > self.timeout:
                    raise RuntimeError(f"Timeout aguardando lock: {self.lock_path}")
                time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc, tb):
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass