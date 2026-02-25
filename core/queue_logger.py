import sys
import queue

class QueueLogger:
    def __init__(self, queue):
        self.queue = queue
        self.terminal = sys.stdout

    def write(self, message):
        if message:
            self.queue.put(message)
            # Optional: duplicate to terminal if needed, but in child process likely not
            # self.terminal.write(message) 

    def flush(self):
        pass

def worker_log_wrapper(func, queue, *args, **kwargs):
    """
    Wraps a function execution, redirecting stdout/stderr to a queue.
    """
    sys.stdout = QueueLogger(queue)
    sys.stderr = QueueLogger(queue)
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"Worker Error: {e}")
        raise
    finally:
        # Restore (optional, process ends anyway)
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
