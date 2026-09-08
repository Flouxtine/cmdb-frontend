"""演示数据源：无需真实云账号即可体验完整流程（12 个资源）"""
from .base import ProviderBase


class DemoProvider(ProviderBase):
    provider = "demo"
    display_name = "演示环境"

    def test_connection(self):
        return True, "演示数据源连接成功"

    def list_resources(self):
        return [
            {"resource_type": "ecs", "resource_id": "i-demo-001", "name": "web-prod-01", "region": "cn-hangzhou",
             "attributes": {"instance_type": "ecs.g6.2xlarge", "status": "Running", "os": "Alibaba Cloud Linux 3", "cpu": 8, "memory": 32}, "tags": {"env": "prod", "app": "web"}},
            {"resource_type": "ecs", "resource_id": "i-demo-002", "name": "web-prod-02", "region": "cn-hangzhou",
             "attributes": {"instance_type": "ecs.g6.2xlarge", "status": "Running", "os": "Alibaba Cloud Linux 3", "cpu": 8, "memory": 32}, "tags": {"env": "prod", "app": "web"}},
            {"resource_type": "ecs", "resource_id": "i-demo-003", "name": "pay-center-01", "region": "cn-shanghai",
             "attributes": {"instance_type": "ecs.c7.4xlarge", "status": "Running", "os": "Alibaba Cloud Linux 3", "cpu": 16, "memory": 64}, "tags": {"env": "prod", "app": "pay"}},
            {"resource_type": "ecs", "resource_id": "i-demo-004", "name": "dev-build-01", "region": "cn-beijing",
             "attributes": {"instance_type": "ecs.c6.xlarge", "status": "Stopped", "os": "Ubuntu 22.04", "cpu": 4, "memory": 8}, "tags": {"env": "dev", "app": "ci"}},
            {"resource_type": "disk", "resource_id": "d-demo-001", "name": "web-prod-01-系统盘", "region": "cn-hangzhou",
             "attributes": {"disk_type": "system", "encrypted": True, "size_gb": 40, "category": "cloud_essd"}, "tags": {"env": "prod"}},
            {"resource_type": "disk", "resource_id": "d-demo-002", "name": "pay-center-01-数据盘", "region": "cn-shanghai",
             "attributes": {"disk_type": "data", "encrypted": False, "size_gb": 500, "category": "cloud_essd"}, "tags": {"env": "prod"}},
            {"resource_type": "disk", "resource_id": "d-demo-003", "name": "dev-build-01-系统盘", "region": "cn-beijing",
             "attributes": {"disk_type": "system", "encrypted": True, "size_gb": 40, "category": "cloud_efficiency"}, "tags": {"env": "dev"}},
            {"resource_type": "security_group", "resource_id": "sg-demo-001", "name": "web-prod-sg", "region": "cn-hangzhou",
             "attributes": {"description": "生产 Web 安全组", "rules": [
                 {"protocol": "tcp", "port_range": "80/80", "source_cidr_ip": "0.0.0.0/0", "direction": "ingress"},
                 {"protocol": "tcp", "port_range": "443/443", "source_cidr_ip": "0.0.0.0/0", "direction": "ingress"},
                 {"protocol": "tcp", "port_range": "22/22", "source_cidr_ip": "0.0.0.0/0", "direction": "ingress"}]}, "tags": {"env": "prod"}},
            {"resource_type": "security_group", "resource_id": "sg-demo-002", "name": "pay-center-sg", "region": "cn-shanghai",
             "attributes": {"description": "支付中心安全组", "rules": [
                 {"protocol": "tcp", "port_range": "3306/3306", "source_cidr_ip": "0.0.0.0/0", "direction": "ingress"},
                 {"protocol": "tcp", "port_range": "8080/8080", "source_cidr_ip": "10.0.0.0/8", "direction": "ingress"}]}, "tags": {"env": "prod"}},
            {"resource_type": "security_group", "resource_id": "sg-demo-003", "name": "dev-build-sg", "region": "cn-beijing",
             "attributes": {"description": "开发构建安全组", "rules": [
                 {"protocol": "tcp", "port_range": "22/22", "source_cidr_ip": "10.0.0.0/8", "direction": "ingress"}]}, "tags": {"env": "dev"}},
            {"resource_type": "oss", "resource_id": "prod-app-static", "name": "prod-app-static", "region": "cn-hangzhou",
             "attributes": {"acl": "public-read", "storage_class": "Standard", "location": "oss-cn-hangzhou"}, "tags": {"env": "prod"}},
            {"resource_type": "oss", "resource_id": "backup-data", "name": "backup-data", "region": "cn-shanghai",
             "attributes": {"acl": "private", "storage_class": "IA", "location": "oss-cn-shanghai"}, "tags": {"env": "prod"}},
        ], []
