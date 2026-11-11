"""47课检查点测试：临时SQLite文件、模拟模型；不调用付费API。"""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage
import checkpoint
import tools


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name).resolve() / "checkpoint-test.db"
        override = patch.object(checkpoint, "CHECKPOINT_PATH", self.path)
        override.start()
        self.addCleanup(override.stop)

    def load_agent(self, ask):
        # 重新导入Agent模拟应用重新启动；数据库文件保持不变。
        with patch.dict(sys.modules, {"llm_client": SimpleNamespace(ask_model=ask)}):
            sys.modules.pop("agent", None)
            return importlib.import_module("agent")

    def test_failure_restart_and_resume_without_repeating_tool(self):
        request = AIMessage(content="", tool_calls=[{
            "name": "add", "args": {"a": 10, "b": 1}, "id": "checkpoint-add"
        }])
        ask = Mock(side_effect=[request, RuntimeError("模拟聊天连接中断")])
        agent = self.load_agent(ask)
        original_add = tools.functions["add"].func
        with patch.object(agent, "get_history", return_value=[]), \
             patch.object(agent, "save_turn") as save, \
             patch.object(tools.functions["add"], "func", wraps=original_add) as add:
            with self.assertRaisesRegex(RuntimeError, "模拟"):
                agent.run_agent("10加1", "resume-test")
            add.assert_called_once()
            save.assert_not_called()  # 过程尚未完成，但检查点已经存在。

        saved = agent.get_saved_state("resume-test")
        self.assertEqual(saved["next"], ["model"])
        self.assertEqual(saved["model_calls"], 1)
        self.assertEqual(saved["tool_records"][0]["tool_result"]["result"], 11)

        # 独立Python进程重新读取同一文件，证明数据不只保存在当前进程内存。
        code = (
            "from langgraph.checkpoint.sqlite import SqliteSaver; "
            "import json; "
            f"path={str(self.path)!r}; "
            "saver_context=SqliteSaver.from_conn_string(path); "
            "saver=saver_context.__enter__(); "
            "item=saver.get_tuple({'configurable':{'thread_id':'resume-test'}}); "
            "print(json.dumps({'model_calls':item.checkpoint['channel_values']['model_calls']})); "
            "saver_context.__exit__(None,None,None)"
        )
        output = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            check=True, timeout=30
        )
        self.assertEqual(json.loads(output.stdout)["model_calls"], 1)

        # 再导入新Agent，仅允许一次模型回复；已经执行的add不应再运行。
        new_ask = Mock(return_value=AIMessage(content="结果是11"))
        agent = self.load_agent(new_ask)
        with patch.object(agent, "save_turn") as save, \
             patch.object(tools.functions["add"], "func") as add:
            state = agent.resume_agent("resume-test")
            add.assert_not_called()
            new_ask.assert_called_once()
            self.assertEqual(state["model_calls"], 2)
            self.assertEqual(state["final_answer"], "结果是11")
            self.assertEqual(len(save.call_args.args[1]), 4)
            # 已完成时再点恢复：只返回状态，不重复执行或再次保存。
            agent.resume_agent("resume-test")
            save.assert_called_once()
            new_ask.assert_called_once()
        self.assertEqual(agent.get_saved_state("resume-test")["next"], [])

    def test_next_question_does_not_duplicate_history(self):
        ask = Mock(side_effect=[AIMessage(content="第一轮"), AIMessage(content="第二轮")])
        agent = self.load_agent(ask)
        history = [{"role": "user", "content": "旧问题"},
                   {"role": "assistant", "content": "旧回答"}]
        with patch.object(agent, "get_history", return_value=history) as get_history, \
             patch.object(agent, "save_turn") as save:
            agent.run_agent("新问题1", "history-test")
            second = agent.run_agent("新问题2", "history-test")
        get_history.assert_called_once()
        self.assertEqual(len(second["message"]), 7)  # system+旧2条+本次两轮各2条
        self.assertEqual(second["model_calls"], 1)    # 新问题重置模型调用预算
        self.assertEqual(len(save.call_args.args[1]), 2)
        questions = [m.content for m in second["message"] if isinstance(m, HumanMessage)]
        self.assertEqual(questions, ["旧问题", "新问题1", "新问题2"])

    def test_pending_session_rejects_new_question(self):
        agent = self.load_agent(Mock(side_effect=RuntimeError("模拟中断")))
        with patch.object(agent, "get_history", return_value=[]), patch.object(agent, "save_turn"):
            with self.assertRaises(RuntimeError):
                agent.run_agent("旧任务", "pending")
            with self.assertRaisesRegex(ValueError, "未完成"):
                agent.run_agent("不能覆盖旧任务", "pending")

    def test_sessions_are_isolated_and_unknown_resume_rejected(self):
        agent = self.load_agent(Mock(return_value=AIMessage(content="A回答")))
        with patch.object(agent, "get_history", return_value=[]), patch.object(agent, "save_turn"):
            agent.run_agent("A问题", "session-A")
        self.assertTrue(agent.get_saved_state("session-A")["exists"])
        self.assertFalse(agent.get_saved_state("session-B")["exists"])
        with self.assertRaisesRegex(ValueError, "没有找到"):
            agent.resume_agent("session-B")


if __name__ == "__main__":
    unittest.main()
