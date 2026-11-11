import importlib
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        with patch("database.init_connection"):
            self.module = importlib.import_module("main")
        self.client = TestClient(self.module.app)
        self.addCleanup(self.client.close)

    def test_page_assets_and_api_docs(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("差旅报销工作台", home.text)
        for path in ("/assets/style.css", "/assets/workbench.js", "/assets/api.js", "/docs"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/assets/.env").status_code, 404)

    def test_workbench_uses_existing_confirmation_contract(self):
        pending = {
            "confirmation_id": "demo-confirm", "tool_name": "save_file",
            "arguments": {"file_name": "demo.md", "content": "测试"},
        }
        with patch.object(self.module, "run_agent", return_value={
            "final_answer": None, "status": "waiting_confirmation", "pending_tool": pending
        }) as run:
            result = self.client.post("/chat", json={"session_id": "demo", "message": "请保存"})
        run.assert_called_once_with("请保存", "demo")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["pending_tool"], pending)

        with patch.object(self.module, "confirm_agent", return_value={
            "final_answer": "未写入", "status": "completed"
        }) as confirm:
            result = self.client.post("/confirm/demo", json={
                "confirmation_id": "demo-confirm", "approved": False
            })
        confirm.assert_called_once_with("demo", "demo-confirm", False)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["answer"], "未写入")
