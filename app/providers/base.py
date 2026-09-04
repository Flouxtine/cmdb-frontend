"""云厂商适配基类（新增厂商：继承本类并在 registry 注册）"""
import abc


class ProviderBase(abc.ABC):
    provider = "base"
    display_name = "未知"

    def __init__(self, credential):
        """credential 需含解密后的 access_key/secret_key"""
        self.credential = credential

    def regions(self):
        return self.credential.get("regions") or ["cn-hangzhou"]

    @abc.abstractmethod
    def test_connection(self):
        """返回 (ok, message)"""
        raise NotImplementedError

    @abc.abstractmethod
    def list_resources(self):
        """返回 (resources, errors)；resources 为标准化 dict：
        {resource_type: ecs|disk|security_group|oss, resource_id, name, region,
         attributes: {...}, tags: {...}}"""
        raise NotImplementedError
