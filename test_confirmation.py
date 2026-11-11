"""48课：人工确认的离线测试，仅在临时目录中写测试文件。"""
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from pydantic import ValidationError
import checkpoint
from schemas import ConfirmRequest, RequestModel
import tools


def save_call(name="notes.txt", call_id="save-1"):
    return {"name": "save_file", "args": {"file_name": name, "content": "测试正文"}, "id": call_id}


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name).resolve()
        for target, name, value in (
            (checkpoint, "CHECKPOINT_PATH", self.folder / "checkpoints.db"),
            (tools, "WORK_DIR", self.folder)
        ):
            override = patch.object(target, name, value)
            override.start()
            self.addCleanup(override.stop)

    def load_agent(self, ask):
        with patch.dict(sys.modules, {"llm_client": SimpleNamespace(ask_model=ask)}):
            sys.modules.pop("agent", None)
            return importlib.import_module("agent")

    def start(self, agent, session="confirm-test"):
        with patch.object(agent, "get_history", return_value=[]), patch.object(agent, "save_turn") as save:
            state = agent.run_agent("请保存文件", session)
            save.assert_not_called()  # 暂停时不把半套工具消息归档。
        self.assertEqual(state["status"], "waiting_confirmation")
        return state["pending_tool"]

    def test_approve_writes_once_and_old_confirmation_is_rejected(self):
        ask = Mock(side_effect=[AIMessage(content="", tool_calls=[save_call()]), AIMessage(content="已保存")])
        agent = self.load_agent(ask)
        pending = self.start(agent)
        target = self.folder / "notes.txt"
        self.assertFalse(target.exists())
        self.assertEqual(pending["arguments"]["content"], "测试正文")
        self.assertEqual(ask.call_count, 1)
        with patch.object(agent, "save_turn") as save:
            state = agent.confirm_agent("confirm-test", pending["confirmation_id"], True)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(target.read_text(encoding="utf-8"), "测试正文")
            save.assert_called_once()
            with self.assertRaisesRegex(ValueError, "没有等待"):
                agent.confirm_agent("confirm-test", pending["confirmation_id"], True)
        self.assertEqual(ask.call_count, 2)

    def test_approval_does_not_allow_overwriting_existing_file(self):
        target = self.folder / "notes.txt"
        target.write_text("原有内容", encoding="utf-8")
        ask = Mock(side_effect=[
            AIMessage(content="", tool_calls=[save_call()]),
            AIMessage(content="文件已存在，未覆盖")
        ])
        agent = self.load_agent(ask)
        pending = self.start(agent)
        with patch.object(agent, "save_turn"):
            state = agent.confirm_agent("confirm-test", pending["confirmation_id"], True)
        result = state["tool_records"][0]["tool_result"]
        self.assertFalse(result["ok"])
        self.assertIn("已存在", result["error"])
        self.assertEqual(target.read_text(encoding="utf-8"), "原有内容")

    def test_reject_does_not_write_but_other_tool_continues(self):
        calls = [{"name": "reduce", "args": {"a": 10, "b": 1}, "id": "calc"}, save_call()]
        agent = self.load_agent(Mock(side_effect=[AIMessage(content="", tool_calls=calls), AIMessage(content="拒绝保存，计算结果9")]))
        pending = self.start(agent)
        with patch.object(agent, "save_turn"):
            state = agent.confirm_agent("confirm-test", pending["confirmation_id"], False)
        self.assertFalse((self.folder / "notes.txt").exists())
        self.assertEqual(state["tool_records"][0]["tool_result"]["result"], 9)
        self.assertFalse(state["tool_records"][1]["tool_result"]["ok"])

    def test_logs_trace_rejected_save_without_exposing_content(self):
        agent = self.load_agent(Mock(side_effect=[
            AIMessage(content="", tool_calls=[save_call()]), AIMessage(content="未保存")
        ]))
        with self.assertLogs(agent.logger.name, level="INFO") as captured:
            pending = self.start(agent)
            with patch.object(agent, "save_turn"):
                agent.confirm_agent("confirm-test", pending["confirmation_id"], False)
        logs = "\n".join(captured.output)
        waiting = logs.index("session='confirm-test' waiting_confirmation tool=save_file not_executed")
        decision = logs.index("session='confirm-test' confirmation_received approved=False")
        rejected = logs.index("session='confirm-test' tool_result tool=save_file outcome=rejected_not_written")
        self.assertLess(waiting, decision)
        self.assertLess(decision, rejected)
        self.assertNotIn("测试正文", logs)
        self.assertNotIn("notes.txt", logs)
        self.assertFalse((self.folder / "notes.txt").exists())

    def test_restart_and_resume_cannot_bypass_confirmation(self):
        agent = self.load_agent(Mock(return_value=AIMessage(content="", tool_calls=[save_call()])))
        pending = self.start(agent)
        agent = self.load_agent(Mock(return_value=AIMessage(content="完成")))
        info = agent.get_saved_state("confirm-test")
        self.assertEqual(info["status"], "waiting_confirmation")
        self.assertEqual(info["pending_tool"], pending)
        with self.assertRaisesRegex(ValueError, "/confirm"):
            agent.resume_agent("confirm-test")
        with self.assertRaisesRegex(ValueError, "人工确认"):
            agent.run_agent("新问题", "confirm-test")
        self.assertFalse((self.folder / "notes.txt").exists())
        with patch.object(agent, "save_turn"):
            state = agent.confirm_agent("confirm-test", pending["confirmation_id"], True)
        self.assertEqual(state["status"], "completed")

    def test_multiple_confirmations_do_not_replay_earlier_tools(self):
        calls = [
            {"name": "add", "args": {"a": 1, "b": 2}, "id": "calc"},
            save_call("one.txt", "save-one"), save_call("two.txt", "save-two")
        ]
        agent = self.load_agent(Mock(side_effect=[AIMessage(content="", tool_calls=calls), AIMessage(content="完成")]))
        original_add = tools.functions["add"].func
        with patch.object(tools.functions["add"], "func", wraps=original_add) as add, \
             patch.object(agent, "save_turn"):
            first = self.start(agent)
            add.assert_not_called()
            middle = agent.confirm_agent("confirm-test", first["confirmation_id"], True)
            self.assertEqual(middle["status"], "waiting_confirmation")
            self.assertFalse((self.folder / "one.txt").exists())
            second = middle["pending_tool"]
            self.assertNotEqual(first["confirmation_id"], second["confirmation_id"])
            # 旧决定不能被错用到同一轮的下一个文件。
            with self.assertRaisesRegex(ValueError, "过期"):
                agent.confirm_agent("confirm-test", first["confirmation_id"], True)
            state = agent.confirm_agent("confirm-test", second["confirmation_id"], False)
            add.assert_called_once()
        self.assertTrue((self.folder / "one.txt").exists())
        self.assertFalse((self.folder / "two.txt").exists())
        self.assertEqual(len(state["tool_records"]), 3)

    def test_invalid_path_does_not_request_confirmation(self):
        call = save_call("../outside.txt")
        agent = self.load_agent(Mock(side_effect=[AIMessage(content="", tool_calls=[call]), AIMessage(content="参数被拒绝")]))
        with patch.object(agent, "get_history", return_value=[]), patch.object(agent, "save_turn"):
            state = agent.run_agent("保存", "bad-path")
        self.assertEqual(state["status"], "completed")
        self.assertFalse(state["tool_records"][0]["tool_result"]["ok"])
        self.assertNotIn("pending_tool", state)

    def test_wrong_id_and_session_cannot_approve(self):
        agent = self.load_agent(Mock(return_value=AIMessage(content="", tool_calls=[save_call()])))
        pending = self.start(agent)
        with self.assertRaisesRegex(ValueError, "过期"):
            agent.confirm_agent("confirm-test", "not-this-operation", True)
        with self.assertRaisesRegex(ValueError, "没有等待"):
            agent.confirm_agent("another-session", pending["confirmation_id"], True)
        self.assertFalse((self.folder / "notes.txt").exists())

    def test_decision_requires_real_boolean(self):
        for bad in ("false", "true", 0, 1, None):
            with self.assertRaises(ValidationError):
                ConfirmRequest(confirmation_id="test", approved=bad)
        self.assertFalse(ConfirmRequest(confirmation_id="test", approved=False).approved)

    def test_api_exposes_pending_operation_and_accepts_decision(self):
        pending = {
            "confirmation_id": "interrupt-id:call-id", "tool_call_id": "call-id",
            "tool_name": "save_file", "arguments": {"file_name": "notes.txt", "content": "正文"}
        }
        waiting = {"status": "waiting_confirmation", "final_answer": None, "pending_tool": pending}
        fake_confirm = Mock(return_value={"status": "completed", "final_answer": "已保存"})
        fake_agent = SimpleNamespace(
            run_agent=Mock(return_value=waiting), get_saved_state=Mock(),
            resume_agent=Mock(), confirm_agent=fake_confirm
        )
        with patch.dict(sys.modules, {"agent": fake_agent}), patch("database.init_connection"):
            sys.modules.pop("main", None)
            main = importlib.import_module("main")
        routes = {route.path: route.endpoint for route in main.app.routes if hasattr(route, "endpoint")}
        response = routes["/chat"](RequestModel(session_id="api", message="请保存"))
        self.assertEqual(response.pending_tool, pending)
        self.assertEqual(response.status, "waiting_confirmation")
        response = routes["/confirm/{session_id}"](
            "api", ConfirmRequest(confirmation_id=pending["confirmation_id"], approved=True)
        )
        self.assertEqual(response.answer, "已保存")
        fake_confirm.assert_called_once_with("api", pending["confirmation_id"], True)


if __name__ == "__main__":
    unittest.main()
