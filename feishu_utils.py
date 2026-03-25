import requests
import json
import time
from datetime import datetime


class FeishuTable:
    """飞书多维表格工具类（修复版）"""

    def __init__(self, app_id, app_secret, base_token):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_token = base_token
        self.tenant_access_token = self._get_tenant_access_token()
        print(f"[飞书] 初始化成功，base_token={base_token}")

    def _get_tenant_access_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data}")
        token = data["tenant_access_token"]
        print(f"[飞书] tenant_access_token 获取成功")
        return token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }

    def get_table_id(self):
        """获取第一个数据表的 table_id"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables"
        resp = requests.get(url, headers=self._headers())
        resp.raise_for_status()
        tables = resp.json().get("data", {}).get("items", [])
        if tables:
            return tables[0].get("table_id")
        return None

    def get_all_records(self, table_id):
        """获取所有记录（支持分页）"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records"
        records = []
        page_token = ""
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            records.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return records

    def delete_records(self, table_id, record_ids):
        """批量删除记录（每批最多 500 条）"""
        if not record_ids:
            return
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_delete"
        for i in range(0, len(record_ids), 500):
            batch = record_ids[i:i + 500]
            payload = {"records": batch}
            resp = requests.post(url, headers=self._headers(), json=payload)
            if resp.status_code != 200:
                print(f"[飞书] 删除失败: {resp.text}")
            else:
                print(f"[飞书] 删除 {len(batch)} 条记录成功")

    def batch_add_records(self, table_id, records):
        """
        批量写入记录（每批最多 500 条）
        records: list of dict，每个 dict 是一行数据的字段映射
        返回成功写入的总条数
        """
        if not records:
            print("[飞书] 没有数据需要写入")
            return 0

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_create"
        total_written = 0

        for i in range(0, len(records), 500):
            batch = records[i:i + 500]
            payload = {"records": [{"fields": r} for r in batch]}
            resp = requests.post(url, headers=self._headers(), json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("code") == 0:
                written = len(data.get("data", {}).get("records", []))
                total_written += written
                print(f"[飞书] 批次 {i//500 + 1}：成功写入 {written} 条记录")
            else:
                print(f"[飞书] 批次 {i//500 + 1} 写入失败: {data}")
            time.sleep(0.3)  # 避免触发飞书限流

        print(f"[飞书] 全部写入完成，共 {total_written} 条")
        return total_written
