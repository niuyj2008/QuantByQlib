"""QuantByQlib 自定义异常体系"""


class QuantError(Exception):
    """所有自定义异常的基类"""
    pass


class DataUnavailableError(QuantError):
    """数据不可用（数据源返回空或所有 provider 均失败）"""
    pass


class QlibNotInitializedError(QuantError):
    """Qlib 未完成初始化（数据未下载或路径错误）"""
    pass


class ModelNotTrainedError(QuantError):
    """模型尚未训练，无法执行预测"""
    pass


class StrategyRunError(QuantError):
    """策略运行过程中发生错误"""
    pass


class PortfolioError(QuantError):
    """持仓管理相关错误"""
    pass


class InsufficientSharesError(PortfolioError):
    """卖出股数超过持仓数量"""
    def __init__(self, symbol: str, held: float, sell: float):
        super().__init__(f"{symbol}: 持仓 {held} 股，尝试卖出 {sell} 股，数量不足")
        self.symbol = symbol
        self.held = held
        self.sell = sell


class OpenBBError(QuantError):
    """OpenBB 数据接口调用失败"""
    pass


class DockerError(QuantError):
    """Docker 相关操作失败"""
    pass


class ConfigError(QuantError):
    """配置文件读取或校验失败"""
    pass
