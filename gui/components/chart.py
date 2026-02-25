import json
from nicegui import ui


class ChartElement(ui.element):
    """
    Custom NiceGUI Element wrapping TradingView Lightweight Charts.
    Renders inside a styled container with loading state.
    """

    def __init__(self):
        super().__init__('div')
        self.props(f'id={self.id}')
        self.classes('w-full h-full')
        self.style(
            'min-height: 420px;'
            'background: #0a0e17;'
            'border-radius: 12px;'
            'position: relative;'
        )
        self.on('init', self.init_chart)

    def init_chart(self, e=None):
        """Trigger the global JS function to bind the chart to this div."""
        ui.run_javascript(f'window.initChart("{self.id}")')

    def set_data(self, data):
        ui.run_javascript(f'window.setChartData("{self.id}", {json.dumps(data)})')

    def update_candle(self, candle):
        ui.run_javascript(f'window.updateChart("{self.id}", {json.dumps(candle)})')

    def set_markers(self, markers):
        ui.run_javascript(f'window.setMarkers("{self.id}", {json.dumps(markers)})')
