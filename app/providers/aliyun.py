"""阿里云 Provider：ECS/云盘/安全组(含入方向规则)/OSS"""
import json

import oss2
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkecs.request.v20140526.DescribeDisksRequest import DescribeDisksRequest
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkecs.request.v20140526.DescribeRegionsRequest import DescribeRegionsRequest
from aliyunsdkecs.request.v20140526.DescribeSecurityGroupAttributeRequest import DescribeSecurityGroupAttributeRequest
from aliyunsdkecs.request.v20140526.DescribeSecurityGroupsRequest import DescribeSecurityGroupsRequest

from .base import ProviderBase

PAGE = 50


def _client(cred, region):
    return AcsClient(cred["access_key"], cred["secret_key"], region, timeout=15)


def _page_all(client, req_cls, list_key):
    out, page_no = [], 1
    while True:
        req = req_cls()
        req.set_PageSize(PAGE)
        req.set_PageNumber(page_no)
        data = json.loads(client.do_action_with_exception(req))
        items = data.get(list_key, []) or []
        out.extend(items)
        if page_no * PAGE >= int(data.get("TotalCount", len(items))):
            break
        page_no += 1
    return out


class AliyunProvider(ProviderBase):
    provider = "aliyun"
    display_name = "阿里云"

    def test_connection(self):
        try:
            client = _client(self.credential, self.regions()[0])
            client.do_action_with_exception(DescribeRegionsRequest())
            return True, f"连接成功（{self.regions()[0]}）"
        except (ClientException, ServerException) as e:
            return False, f"连接失败: {e}"
        except Exception as e:
            return False, f"连接异常: {e}"

    def list_resources(self):
        resources, errors = [], []
        for region in self.regions():
            try:
                client = _client(self.credential, region)
            except Exception as e:
                errors.append(f"[{region}] 客户端创建失败: {e}")
                continue
            try:
                for inst in _page_all(client, DescribeInstancesRequest, "Instances"):
                    sg_ids = [g.get("SecurityGroupId") for g in (inst.get("SecurityGroupIds", {}) or {}).get("SecurityGroupId", [])] if inst.get("SecurityGroupIds") else []
                    resources.append({"resource_type": "ecs", "resource_id": inst.get("InstanceId"),
                                      "name": inst.get("InstanceName") or inst.get("InstanceId"), "region": region,
                                      "attributes": {"status": inst.get("Status"), "os": inst.get("OSName"),
                                                     "instance_type": inst.get("InstanceType"), "cpu": inst.get("Cpu"),
                                                     "memory": inst.get("Memory"), "vpc_id": (inst.get("VpcAttributes") or {}).get("VpcId"),
                                                     "security_group_ids": sg_ids},
                                      "tags": {t.get("TagKey"): t.get("TagValue") for t in (inst.get("Tags") or {}).get("Tag", [])}})
            except Exception as e:
                errors.append(f"[{region}] ECS 同步失败: {e}")
            try:
                for d in _page_all(client, DescribeDisksRequest, "Disks"):
                    resources.append({"resource_type": "disk", "resource_id": d.get("DiskId"),
                                      "name": d.get("DiskName") or d.get("DiskId"), "region": region,
                                      "attributes": {"disk_type": "system" if d.get("Type") == "system" else "data",
                                                     "encrypted": bool(d.get("Encrypted")), "size_gb": d.get("Size"),
                                                     "category": d.get("Category"), "status": d.get("Status")},
                                      "tags": {t.get("TagKey"): t.get("TagValue") for t in (d.get("Tags") or {}).get("Tag", [])}})
            except Exception as e:
                errors.append(f"[{region}] 云盘同步失败: {e}")
            try:
                for g in _page_all(client, DescribeSecurityGroupsRequest, "SecurityGroups"):
                    sg_id = g.get("SecurityGroupId")
                    rules = []
                    try:
                        req = DescribeSecurityGroupAttributeRequest()
                        req.set_SecurityGroupId(sg_id)
                        req.set_Direction("ingress")
                        perms = (json.loads(client.do_action_with_exception(req)).get("Permissions") or {}).get("Permission", []) or []
                        rules = [{"protocol": p.get("IpProtocol"), "port_range": p.get("PortRange"),
                                  "source_cidr_ip": p.get("SourceCidrIp"), "direction": "ingress"} for p in perms]
                    except Exception as e:
                        errors.append(f"[{region}] 安全组规则获取失败: {e}")
                    resources.append({"resource_type": "security_group", "resource_id": sg_id,
                                      "name": g.get("SecurityGroupName") or sg_id, "region": region,
                                      "attributes": {"description": g.get("Description"), "rules": rules},
                                      "tags": {t.get("TagKey"): t.get("TagValue") for t in (g.get("Tags") or {}).get("Tag", [])}})
            except Exception as e:
                errors.append(f"[{region}] 安全组同步失败: {e}")
        try:
            auth = oss2.Auth(self.credential["access_key"], self.credential["secret_key"])
            for info in oss2.BucketIterator(oss2.Service(auth, "https://oss-cn-hangzhou.aliyuncs.com", connect_timeout=15)):
                acl = "unknown"
                try:
                    acl = oss2.Bucket(auth, f"https://{info.location}.aliyuncs.com", info.name, connect_timeout=15).get_bucket_acl().access_control_list.grant
                except Exception:
                    pass
                resources.append({"resource_type": "oss", "resource_id": info.name, "name": info.name,
                                  "region": info.location.replace("oss-", ""),
                                  "attributes": {"acl": acl, "location": info.location}, "tags": {}})
        except Exception as e:
            errors.append(f"OSS 同步失败: {e}")
        return resources, errors
