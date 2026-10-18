import queue
import threading


class EventBus:
    def __init__(self, maxsize=100):
        self.maxsize = maxsize
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=self.maxsize)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event, data):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            while True:
                try:
                    q.put_nowait((event, data))
                    break
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
