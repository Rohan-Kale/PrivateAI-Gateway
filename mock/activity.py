"""Synchronized execution observations for the test provider only."""
from contextlib import contextmanager
import threading
import time


class Activity:
    def __init__(self):
        self.lock=threading.Lock();self.active=0;self.peak=0;self.calls=0
        self.started=time.time()

    def snapshot(self):
        with self.lock:
            return {"active":self.active,"peak_active":self.peak,"calls":self.calls,"since_unix":self.started}

    def reset(self):
        with self.lock:
            if self.active:return False
            self.peak=self.calls=0;self.started=time.time();return True

    @contextmanager
    def measure(self):
        with self.lock:
            self.active+=1;self.calls+=1;self.peak=max(self.peak,self.active)
        try:yield
        finally:
            with self.lock:self.active-=1
