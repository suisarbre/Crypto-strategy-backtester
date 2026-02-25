import sys
from nicegui import ui


class StreamRedirector:
    """Redirects sys.stdout / sys.stderr to both console and a callback."""

    def __init__(self, stream, callback, quiet=False):
        self.stream = stream
        self.callback = callback
        self.quiet = quiet
        self.encoding = getattr(stream, 'encoding', 'utf-8')

    def write(self, message):
        if not self.quiet:
            self.stream.write(message)
            self.stream.flush()
        if message:
            self.callback(message)

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, 'isatty', lambda: False)()

    def fileno(self):
        return self.stream.fileno()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class LogElement(ui.log):
    """
    Styled log panel.
    Automatically caps visible lines and provides colour-coded keywords.
    NiceGUI ui.log wraps a QScrollArea – it MUST have an explicit height
    and labels inside need explicit color for custom dark themes.
    """
    MAX_LINES = 500

    def __init__(self):
        super().__init__(max_lines=self.MAX_LINES)
        self.classes('w-full font-mono text-xs p-2')
        self.style(
            'background: transparent !important;'
            'color: #94a3b8 !important;'
            'line-height: 1.8 !important;'
            'height: 180px !important;'           # QScrollArea needs explicit height
        )

    def push(self, msg, **kwargs):
        """Push a line with explicit color so labels are visible on dark bg."""
        kwargs.setdefault('style', 'color: #94a3b8 !important;')
        try:
            super().push(msg, **kwargs)
        except TypeError:
            # NiceGUI < 2.18 doesn't support style kwarg
            super().push(msg)
