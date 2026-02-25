// ═══════════════════════════════════════════════════════════════════════════════
// Chart Controller – TradingView Lightweight Charts v5
// Modern dark theme with polished visuals
// ═══════════════════════════════════════════════════════════════════════════════

window.initChart = function (id) {
    const container = document.getElementById(id);
    if (!container) return;

    // Loading state
    container.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;
                    gap:10px;color:#64748b;font-family:'Inter',sans-serif;font-size:13px;">
            <svg width="20" height="20" viewBox="0 0 24 24" style="animation:spin 1s linear infinite">
                <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
                <circle cx="12" cy="12" r="10" stroke="#334155" stroke-width="3" fill="none"/>
                <path d="M12 2a10 10 0 0 1 10 10" stroke="#3b82f6" stroke-width="3" fill="none" stroke-linecap="round"/>
            </svg>
            Initializing chart…
        </div>`;

    let attempts = 0;
    const check = setInterval(() => {
        attempts++;
        if (window.LightweightCharts) {
            clearInterval(check);
            container.innerHTML = '';
            _createChart(container);
        } else if (attempts > 60) {
            clearInterval(check);
            container.innerHTML = '<div style="color:#ef4444;text-align:center;padding:40px;">❌ Chart library failed to load</div>';
        }
    }, 100);
};

// ─────────────────────────────────────────────────────────────────────────────
// Internal: create the chart instance
// ─────────────────────────────────────────────────────────────────────────────
function _createChart(container) {
    if (container.chart) return;

    const w = container.clientWidth  || 800;
    const h = container.clientHeight || 500;

    try {
        const chart = LightweightCharts.createChart(container, {
            width: w,
            height: h,
            layout: {
                textColor: '#94a3b8',
                background: { type: 'solid', color: '#0a0e17' },
                fontFamily: "'Inter', sans-serif",
                fontSize: 11,
            },
            grid: {
                vertLines: { color: 'rgba(30,41,59,0.5)' },
                horzLines: { color: 'rgba(30,41,59,0.5)' },
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: '#1e293b',
                barSpacing: 8,
            },
            rightPriceScale: {
                borderColor: '#1e293b',
                scaleMargins: { top: 0.1, bottom: 0.08 },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: 'rgba(59,130,246,0.3)',
                    labelBackgroundColor: '#3b82f6',
                },
                horzLine: {
                    color: 'rgba(59,130,246,0.3)',
                    labelBackgroundColor: '#3b82f6',
                },
            },
            handleScale: { axisPressedMouseMove: true },
            handleScroll: { vertTouchDrag: false },
        });

        // Watermark
        chart.applyOptions({
            watermark: {
                visible: true,
                text: 'TradeBot',
                fontSize: 36,
                color: 'rgba(30,41,59,0.25)',
                fontFamily: "'Inter', sans-serif",
            },
        });

        const series = chart.addSeries(LightweightCharts.CandlestickSeries, {
            upColor:       '#10b981',
            downColor:     '#ef4444',
            borderVisible: false,
            wickUpColor:   '#10b981',
            wickDownColor: '#ef4444',
        });

        // Auto-resize
        new ResizeObserver(entries => {
            if (!entries.length || entries[0].target !== container) return;
            const r = entries[0].contentRect;
            chart.applyOptions({ height: r.height, width: r.width });
        }).observe(container);

        container.chart  = chart;
        container.series = series;

    } catch (e) {
        container.innerHTML = `<div style="color:#ef4444;padding:24px;">❌ Chart error: ${e.message}</div>`;
        console.error('[Chart]', e);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

window.setChartData = function (id, data) {
    const c = document.getElementById(id);
    if (c && c.series) {
        c.series.setData(data);
        c.chart.timeScale().fitContent();
    }
};

window.updateChart = function (id, candle) {
    const c = document.getElementById(id);
    if (c && c.series) c.series.update(candle);
};

window.setMarkers = function (id, markers) {
    const c = document.getElementById(id);
    if (!c || !c.series) {
        console.warn('[Chart] setMarkers: container/series not found', id);
        return;
    }

    try {
        // v5: createSeriesMarkers plugin
        if (typeof LightweightCharts.createSeriesMarkers === 'function') {
            if (c.markersPlugin) {
                if (typeof c.markersPlugin.setMarkers === 'function') {
                    c.markersPlugin.setMarkers(markers);
                }
            } else {
                c.markersPlugin = LightweightCharts.createSeriesMarkers(c.series, markers);
            }
        } else if (typeof c.series.setMarkers === 'function') {
            // v4 fallback
            c.series.setMarkers(markers);
        } else {
            console.error('[Chart] No setMarkers API found');
        }
    } catch (e) {
        console.error('[Chart] setMarkers error:', e);
    }
};
