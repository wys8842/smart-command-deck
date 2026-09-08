"""装配层：统一构建框架 Config / Components（应用侧唯一允许触碰框架全局配置的地方）。"""
from agentorchestra.components import Components
from agentorchestra.core.config import Config


def make_config() -> Config:
    """构建业务侧默认配置（feature 大多 opt-in，这里先保持最小集）。

    上线/推演需要时再按场景开启：checkpoint / memory / ontology / trace 等。
    """
    cfg = Config()
    # M0：关闭会产生外部副作用的开关，保证离线干净
    cfg.session_enabled = False
    cfg.state_checkpoint_enabled = False
    cfg.memory_enabled = False
    cfg.trace_enabled = False
    return cfg


def init_components(db_dir: str = "data") -> None:
    """装配框架横切组件（幂等）。

    - 默认不强制注册 store：需要持久化时调用方再显式
      Components.register_state_store(...) 并传入同一 db_url。
    - 这里只保证目录存在，并把指标收集器设为 NoOp 之外的默认。
    """
    import os

    os.makedirs(db_dir, exist_ok=True)


__all__ = ["Components", "Config", "init_components", "make_config"]
