from nicegui import ui



class DebugChart(ui.element):
    def __init__(self):
        super().__init__('div')
        self.style('width: 100%; height: 400px; background-color: #222; border: 2px solid red;')
        self.on('init', self.init_chart)

    def init_chart(self, _):
        # 단계별로 Alert를 띄워서 어디서 막히는지 확인합니다.
        cmd = """
            // 1. 요소 ID 확인
            const id = this.id;
            console.log("Chart ID:", id);
            
            // 2. DOM 요소 찾기
            const container = document.getElementById(id);
            if (!container) {
                alert("❌ 실패: 컨테이너(div)를 찾을 수 없습니다! ID: " + id);
                return;
            }
            container.innerText = "✅ 1단계 성공: 컨테이너 찾음";

            // 3. 라이브러리 로드 확인
            if (!window.LightweightCharts) {
                alert("❌ 실패: 라이브러리가 로드되지 않았습니다! 인터넷 연결을 확인하세요.");
                container.innerText += "\\n❌ 2단계 실패: 라이브러리 없음";
                return;
            }
            container.innerText += "\\n✅ 2단계 성공: 라이브러리 로드됨";

            // 4. 차트 생성 시도
            try {
                const chart = LightweightCharts.createChart(container, {
                    layout: { textColor: 'white', background: { type: 'solid', color: '#111' } },
                    width: container.clientWidth,
                    height: container.clientHeight
                });
                
                const series = chart.addCandlestickSeries();
                series.setData([
                    { time: '2018-12-22', open: 75.16, high: 82.84, low: 36.16, close: 45.72 },
                    { time: '2018-12-23', open: 45.12, high: 53.90, low: 45.12, close: 48.09 },
                    { time: '2018-12-24', open: 60.71, high: 60.71, low: 53.39, close: 59.29 },
                ]);
                
                container.innerText = ""; // 텍스트 지우고 차트 보여주기
                console.log("✅ 차트 생성 성공!");
            } catch (e) {
                alert("❌ 3단계 실패: 차트 생성 중 에러 발생 - " + e.message);
            }
        """
        self.run_method(cmd)

@ui.page('/')
def main():
    # 1. 라이브러리 로드 (페이지 범위 내에서 호출)
    ui.add_head_html('<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>')

    ui.label('Step-by-Step Debugging').classes('text-2xl font-bold mb-4')
    ui.label('아래 빨간 박스 안에 차트가 나와야 합니다.').classes('text-lg mb-2')
    
    # 디버그용 차트 컴포넌트 추가
    DebugChart()

ui.run(port=8081)
