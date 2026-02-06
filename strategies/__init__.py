
from .standard import StandardLogic
from .aggressive import AggressiveLogic

STRATEGY_MAP = {
    'standard': StandardLogic,
    'aggressive': AggressiveLogic
}

def get_strategy(name):
    """
    이름으로 전략 인스턴스를 반환합니다.
    """
    logic_cls = STRATEGY_MAP.get(name, StandardLogic)
    return logic_cls()
