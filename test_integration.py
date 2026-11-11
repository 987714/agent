"""46—47课回归测试：真实LangGraph、隔离检查点文件、模拟聊天模型。"""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_messages

import knowledge_search
import tools


class KnowledgeToolTests(unittest.TestCase):
    def setUp(self):
        # 每个测试用独立检查点文件，不污染真实会话，也不影响测试之间的历史。
        import tempfile
        from pathlib import Path
        import checkpoint
        folder = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(folder.cleanup)
        override = patch.object(checkpoint, "CHECKPOINT_PATH", Path(folder.name) / "checkpoints.db")
        override.start()
        self.addCleanup(override.stop)

    def test_registration_and_validation(self):
        self.assertIs(tools.functions["search_knowledge"].func, knowledge_search.search_knowledge)
        tools.execute_tool("search_knowledge", {"question": "北京住宿上限？"})
        for args in ({}, {"question": 1}, {"question": " "},
                     {"question": "北京", "source": 1},
                     {"question": "北京", "extra": True}):
            with self.assertRaises(ValueError):
                tools.execute_tool("search_knowledge", args)

    def test_unknown_source_returns_empty_without_models(self):
        chunks = [{"text": "北京500元", "source": "差旅制度.md", "chunk_id": 0}]
        with patch.object(knowledge_search, "prepare_knowledge", return_value=(chunks, [[1.0]])):
            self.assertEqual(knowledge_search.search_knowledge("北京？", "不存在.md"), [])

    def test_search_pipeline(self):
        chunks = [{"text": "北京住宿上限500元", "source": "差旅制度.md", "chunk_id": 0}]
        selected = [dict(chunks[0], score=0.03, rerank_score=5.0)]
        embed = Mock(return_value=[[1.0]])
        hybrid = Mock(return_value={"results": chunks})
        rerank = Mock(return_value=selected)
        modules = {
            "embedding": SimpleNamespace(embed_texts=embed),
            "hybrid_retriever": SimpleNamespace(hybrid_retrieve=hybrid),
            "reranker": SimpleNamespace(rerank=rerank)
        }
        with patch.object(knowledge_search, "prepare_knowledge", return_value=(chunks, [[1.0]])), \
             patch.object(knowledge_search, "hybrid_retrieve", hybrid):
            with patch.dict(sys.modules, modules):
                result = knowledge_search.search_knowledge("北京上限？")
        self.assertEqual(result, selected)
        embed.assert_called_once_with(["北京上限？"])
        rerank.assert_called_once_with("北京上限？", chunks, final_k=3)

    def test_agent_receives_tool_evidence_before_final_answer(self):
        # 假模型第一轮提出查资料，第二轮读取message里的工具结果再回答。
        first = AIMessage(content="", tool_calls=[{
            "name": "search_knowledge", "args": {"question": "北京住宿上限？"},
            "id": "call_search", "type": "tool_call"
        }])
        final = AIMessage(content="北京每晚500元（差旅制度.md，片段0）。")

        def fake_ask(message, schemas):
            if isinstance(message[-1], HumanMessage):
                return first
            self.assertIsInstance(message[-1], ToolMessage)
            self.assertIn("500", message[-1].content)
            return final

        # 替换客户端后再导入Agent，避免读取真实密钥或建立API客户端。
        with patch.dict(sys.modules, {"llm_client": SimpleNamespace(ask_model=fake_ask)}):
            sys.modules.pop("agent", None)
            agent_module = importlib.import_module("agent")
        saved = Mock()
        evidence = [{"text": "北京每晚500元", "source": "差旅制度.md", "chunk_id": 0}]
        with patch.object(agent_module, "get_history", return_value=[]), \
             patch.object(agent_module, "save_turn", saved), \
             patch.object(tools.functions["search_knowledge"], "func", return_value=evidence):
            state = agent_module.run_agent("北京住宿上限？", "test45")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["model_calls"], 2)
        self.assertEqual(len(state["tool_records"]), 1)
        saved.assert_called_once()
        self.assertEqual(len(saved.call_args.args[1]), 4)

    def run_mock_agent(self, replies, history=None):
        """复用真实Agent循环，只替换聊天请求和数据库读写。"""
        fake_ask = Mock(side_effect=replies)
        with patch.dict(sys.modules, {"llm_client": SimpleNamespace(ask_model=fake_ask)}):
            sys.modules.pop("agent", None)
            agent_module = importlib.import_module("agent")
        saved = Mock()
        with patch.object(agent_module, "get_history", return_value=history or []), \
             patch.object(agent_module, "save_turn", saved):
            state = agent_module.run_agent("测试问题", "test-lc")
            if state["status"] == "waiting_confirmation":
                # 原先的“写入拦截”回归用例现在明确选择拒绝，仍验证不会写文件。
                state = agent_module.confirm_agent(
                    "test-lc", state["pending_tool"]["confirmation_id"], False
                )
        return state, saved

    def test_real_langchain_tools_execute(self):
        self.assertEqual(tools.functions["add"].invoke({"a": 10, "b": 1}), 11)
        self.assertEqual(tools.functions["reduce"].invoke({"a": 650, "b": 500}), 150)
        self.assertEqual(tools.functions["greet"].invoke({"name": "小明"}), "你好呀，小明！")

    def test_partial_failure_and_save_still_blocked(self):
        import json
        request = AIMessage(content="", tool_calls=[
            {"name": "add", "args": {"a": 1001, "b": 1}, "id": "bad"},
            {"name": "reduce", "args": {"a": 10, "b": 1}, "id": "good"},
            {"name": "save_file", "args": {"file_name": "blocked.txt", "content": "x"}, "id": "save"}
        ])
        # save_file不得被执行，不能产生实际文件。
        with patch.object(tools.functions["save_file"], "func") as save:
            state, saved = self.run_mock_agent([request, AIMessage(content="完成")])
        save.assert_not_called()
        records = state["tool_records"]
        self.assertFalse(records[0]["tool_result"]["ok"])
        self.assertEqual(records[1]["tool_result"]["result"], 9)
        self.assertFalse(records[2]["tool_result"]["ok"])
        rows = saved.call_args.args[1]
        self.assertEqual([r["tool_call_id"] for r in rows if r["role"] == "tool"], ["bad", "good", "save"])
        self.assertTrue(json.loads(rows[3]["content"])["ok"])

    def test_multiple_rounds_and_old_history(self):
        history = [
            {"role": "user", "content": "以前的问题"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "old", "type": "function", "function": {"name": "add", "arguments": '{"a":1,"b":1}'}
            }]},
            {"role": "tool", "tool_call_id": "old", "content": "2"},
            {"role": "assistant", "content": "2"}
        ]
        self.assertEqual(len(convert_to_messages(history)), 4)
        replies = [
            AIMessage(content="", tool_calls=[{"name": "add", "args": {"a": 1, "b": 1}, "id": "one"}]),
            AIMessage(content="", tool_calls=[{"name": "reduce", "args": {"a": 10, "b": 2}, "id": "two"}]),
            AIMessage(content="结果是8")
        ]
        state, saved = self.run_mock_agent(replies, history)
        self.assertEqual(state["model_calls"], 3)
        self.assertEqual(len(state["tool_records"]), 2)
        rows = saved.call_args.args[1]
        self.assertEqual(len(rows), 6)  # 只保存新增，不重复写入旧历史。
        self.assertEqual(len(convert_to_messages(rows)), 6)

    def test_model_call_limit(self):
        replies = []
        for i in range(5):
            replies.append(AIMessage(content="", tool_calls=[{
                "name": "add", "args": {"a": 1, "b": 1}, "id": f"loop-{i}"
            }]))
        state, saved = self.run_mock_agent(replies)
        self.assertEqual(state["status"], "max_calls_reached")
        self.assertEqual(state["model_calls"], 5)
        self.assertEqual(saved.call_args.args[1][-1]["role"], "tool")

    def test_direct_answer_does_not_execute_tools(self):
        state, saved = self.run_mock_agent([AIMessage(content="你好")])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["model_calls"], 1)
        self.assertEqual(state["tool_records"], [])
        self.assertEqual(len(saved.call_args.args[1]), 2)
        self.assertIsInstance(state["message"][1], HumanMessage)

    def test_fifth_model_call_can_still_finish(self):
        replies = []
        for i in range(4):
            replies.append(AIMessage(content="", tool_calls=[{
                "name": "add", "args": {"a": 1, "b": 1}, "id": f"step-{i}"
            }]))
        replies.append(AIMessage(content="正常完成"))
        state, saved = self.run_mock_agent(replies)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["model_calls"], 5)
        self.assertEqual(state["final_answer"], "正常完成")
        self.assertEqual(saved.call_args.args[1][-1]["role"], "assistant")

    def test_graph_step_limit_is_not_model_call_limit(self):
        from langgraph.errors import GraphRecursionError
        first = AIMessage(content="", tool_calls=[{
            "name": "add", "args": {"a": 1, "b": 1}, "id": "limit"
        }])
        fake_ask = Mock(return_value=first)
        with patch.dict(sys.modules, {"llm_client": SimpleNamespace(ask_model=fake_ask)}):
            sys.modules.pop("agent", None)
            agent_module = importlib.import_module("agent")
        initial = {
            "message": [{"role": "user", "content": "1加1"}],
            "model_calls": 0, "tool_records": [], "status": "running", "final_answer": None
        }
        # 故意只给1步：模型节点执行后还需要工具节点，所以框架会阻止继续。
        with self.assertRaises(GraphRecursionError):
            agent_module.graph.invoke(initial, config={"recursion_limit": 1})
        self.assertEqual(fake_ask.call_count, 1)

    def test_ask_model_keeps_our_interface(self):
        import runpy
        # 只验证绑定和调用，不发网络请求、不输出密钥。
        with patch("langchain_openai.ChatOpenAI") as factory:
            namespace = runpy.run_path("llm_client.py")
            message = [{"role": "user", "content": "你好"}]
            namespace["ask_model"](message, tools.tools)
        factory.return_value.bind_tools.assert_called_once_with(tools.tools)
        factory.return_value.bind_tools.return_value.invoke.assert_called_once_with(message)

    def test_sqlite_round_trip_keeps_message_format(self):
        import tempfile
        from pathlib import Path
        import database
        from langchain_core.messages import convert_to_openai_messages
        message = [
            {"role": "user", "content": "10加1"},
            AIMessage(content="", tool_calls=[{
                "name": "add", "args": {"a": 10, "b": 1}, "id": "db-call"
            }]),
            ToolMessage(content='{"ok":true,"result":11}', tool_call_id="db-call"),
            AIMessage(content="11")
        ]
        # 单独临时数据库，不改你的chat.db。
        with tempfile.TemporaryDirectory(dir=".") as folder:
            with patch.object(database, "DB_Path", Path(folder) / "test.db"):
                database.init_connection()
                database.save_turn("roundtrip", convert_to_openai_messages(message))
                history = database.get_history("roundtrip")
                self.assertEqual(history[2]["tool_call_id"], "db-call")
                self.assertEqual(len(convert_to_messages(history)), 4)

    def test_fastapi_keeps_request_response(self):
        from schemas import RequestModel
        fake_state = {"status": "completed", "final_answer": "测试回答"}
        # 替换Agent及初始化，接口测试不访问模型或真实数据库。
        fake_run = Mock(return_value=fake_state)
        with patch.dict(sys.modules, {"agent": SimpleNamespace(
            run_agent=fake_run, get_saved_state=Mock(), resume_agent=Mock(), confirm_agent=Mock()
        )}), \
             patch("database.init_connection"):
            sys.modules.pop("main", None)
            main = importlib.import_module("main")
            # 直接检查路由函数与响应模型，不启动网络或测试线程。
            route = next(route for route in main.app.routes if route.path == "/chat")
            response = route.endpoint(RequestModel(message="测试问题", session_id="api-test"))
        self.assertEqual(response.answer, "测试回答")
        self.assertEqual(response.session_id, "api-test")
        fake_run.assert_called_once_with("测试问题", "api-test")


if __name__ == "__main__":
    unittest.main()
