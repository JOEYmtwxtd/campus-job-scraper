import requests
import json
import time

class FeishuClient:
    def __init__(self, app_id, app_secret, base_token):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_token = base_token
        self.tenant_access_token = self._get_tenant_access_token()

    def _get_tenant_access_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json().get("tenant_access_token")

    def get_table_id(self):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables"
        headers = {"Authorization": f"Bearer {self.tenant_access_token}"}
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        tables = resp.json().get("data", {}).get("items", [])
        return tables[0].get("table_id") if tables else None

    def get_all_records(self, table_id):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {self.tenant_access_token}"}
        records = []
        page_token = ""
        while True:
            params = {"page_size": 500, "page_token": page_token}
            resp = requests.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            records.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return records

    def delete_records(self, table_id, record_ids):
        if not record_ids:
            return
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_delete"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        # 飞书批量删除限制 500 条
        for i in range(0, len(record_ids), 500):
            batch = record_ids[i:i+500]
            payload = {"records": batch}
            requests.post(url, headers=headers, json=payload)

    def add_records(self, table_id, records):
        if not records:
            return
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_create"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        # 飞书批量写入限制 100 条
        for i in range(0, len(records), 100):
            batch = records[i:i+100]
            payload = {"records": [{"fields": r} for r in batch]}
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                print(f"写入失败: {resp.text}")
