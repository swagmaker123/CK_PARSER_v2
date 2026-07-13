import datetime
import json
import os
import time
import uuid


class JsonCache:
    def __init__(self, path, root_key, log_fn=None):
        self.path = path
        self.root_key = root_key
        self.log_fn = log_fn

    def _empty(self):
        return {self.root_key: {}}

    def load(self):
        if not os.path.isfile(self.path):
            return self._empty()

        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            if self.log_fn is not None:
                self.log_fn("warning", "Битый кэш, начинаем заново: %s", e)
            return self._empty()

        if self.root_key not in data or not isinstance(data[self.root_key], dict):
            return self._empty()

        return data

    def save(self, cache):
        """Атомарная запись: tmp → replace. С ретраями на Windows Errno 22 / lock."""
        dirname = os.path.dirname(self.path) or "."
        os.makedirs(dirname, exist_ok=True)

        tmp_path = os.path.join(
            dirname,
            f".{os.path.basename(self.path)}.{uuid.uuid4().hex}.tmp",
        )
        last_error = None

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            for attempt in range(1, 6):
                try:
                    os.replace(tmp_path, self.path)
                    return
                except OSError as e:
                    last_error = e
                    # Windows: Errno 22 / PermissionError при lock антивирусом / индексером
                    if self.log_fn is not None:
                        self.log_fn(
                            "warning",
                            "Не удалось заменить кэш (попытка %s/5): %s",
                            attempt,
                            e,
                        )
                    time.sleep(0.15 * attempt)

            raise OSError(
                f"Не удалось сохранить кэш после ретраев: {self.path}"
            ) from last_error
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def get(self, cache, key):
        return cache[self.root_key].get(key)

    def set_entry(self, cache, key, items, links_count=0, status="processed"):
        cache[self.root_key][key] = {
            "date": key,
            "processed_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "links_found": links_count,
            "items": items,
        }
        self.save(cache)

    def trim(self, cache, keep_fn):
        cache[self.root_key] = {
            key: value
            for key, value in cache[self.root_key].items()
            if keep_fn(key)
        }
