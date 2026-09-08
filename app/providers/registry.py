from .base import ProviderBase  # noqa
from .demo import DemoProvider
from .aliyun import AliyunProvider

REGISTRY = {p.provider: p for p in [DemoProvider, AliyunProvider]}


def list_provider_meta():
    return [{"provider": p.provider, "display_name": p.display_name} for p in REGISTRY.values()]


def get_provider(credential):
    cls = REGISTRY.get(credential.get("provider"))
    if not cls:
        raise ValueError(f"不支持的厂商: {credential.get('provider')}")
    return cls(credential)
