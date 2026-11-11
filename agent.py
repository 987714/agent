"""46课图流程 + 47课SQLite检查点 + 48课写入前人工确认。"""
import json
import logging
from time import perf_counter
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage, ToolMessage, convert_to_openai_messages
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from database import get_history, save_turn
from prompt import build_message
from llm_client import ask_model
from tools import tools, execute_tool, functions, requires_confirmation
from checkpoint import get_checkpointer

# 复用 Uvicorn 的终端日志配置。不记录问题、工具参数、正文或原始异常文本。
logger = logging.getLogger("uvicorn.error.lesson46.agent")

MAX_MODEL_CALLS = 5               #最多真正调用大模型的次数
MAX_GRAPH_STEPS = 12              #图最多执行的次数


class State(TypedDict):           #给共享状态写一份“字段结构说明”，并为消息列表指定合并规则
    message: Annotated[list[AnyMessage], add_messages]
    model_calls: int
    tool_records: list
    status: str
    final_answer: str | None
    new_start: int                # 本次新增消息起点也要保存，重启恢复后仍知道存哪部分


def model_node(state, config: RunnableConfig):            #模型节点
    if state["model_calls"] >= MAX_MODEL_CALLS:
        return {"status": "max_calls_reached", "final_answer": None}
    message = state["message"]
    session_id = config.get("configurable", {}).get("thread_id", "-")
    logger.info("session=%r model_start call=%s", session_id, state["model_calls"] + 1)
    started = perf_counter()
    messages = ask_model(message, tools)
    logger.info("session=%r model_finished call=%s elapsed_ms=%.0f",
                session_id, state["model_calls"] + 1, (perf_counter() - started) * 1000)
    if messages.tool_calls:
        logger.info("session=%r model_requested_tools count=%s", session_id, len(messages.tool_calls))
        status = "running"
        final_answer = None
    else:
        status = "completed"
        final_answer = messages.content

    return {
        "message": [messages],            #不用append，用LangGraph按add_messages规则合并新增消息
        "model_calls": state["model_calls"] + 1,
        "status": status,
        "final_answer": final_answer
    }


def tool_node(state, config: RunnableConfig):             #工具节点
    session_id = config.get("configurable", {}).get("thread_id", "-")
    messages = state["message"][-1]
    tool_messages = []
    tool_records = []

    # 48课：先完成这一轮的人工确认，再执行任何工具。
    # 恢复会从节点开头重跑，这样确认之前只有校验，没有已执行工具会被重放。
    decisions = {}
    for tool_call in messages.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        try:
            execute_tool(tool_name, args)
        except ValueError:
            continue  # 无效参数不请求确认，留给下面原有逻辑返回失败。
        if requires_confirmation(tool_name):             #如果这次要调用`save_file`，先停下来，把“文件名、内容”返回给用户看
            decision = interrupt({
                "tool_call_id": tool_call["id"],
                "tool_name": tool_name,
                "arguments": args
            })
            if type(decision) is not bool:
                raise ValueError("确认决定必须是true或false")
            decisions[tool_call["id"]] = decision

    for tool_call in messages.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        log_name = tool_name if tool_name in functions else "unknown"
        outcome = "failed"
        started = perf_counter()
        try:
            execute_tool(tool_name, args)  # 原有校验不变
            if requires_confirmation(tool_name) and not decisions[tool_call["id"]]:
                outcome = "rejected_not_written"
                raise ValueError("用户拒绝执行此工具，未写入文件。不要自行重试该写入。")
            function = functions[tool_name]
            logger.info("session=%r tool_start tool=%s", session_id, log_name)
            result = function.invoke(args)
            tool_result = {"ok": True, "result": result}
            outcome = "saved" if tool_name == "save_file" else "succeeded"
        except ValueError as Error:
            tool_result = {"ok": False, "error": str(Error)}
            if tool_name == "save_file" and str(Error) == "文件已存在，不允许覆盖":
                outcome = "existing_file_not_overwritten"
        logger.info("session=%r tool_result tool=%s outcome=%s", session_id, log_name, outcome)
        logger.info("session=%r tool_elapsed tool=%s elapsed_ms=%.0f",
                    session_id, log_name, (perf_counter() - started) * 1000)

        tool_messages.append(
            ToolMessage(
                content=json.dumps(tool_result, ensure_ascii=False),
                tool_call_id=tool_call["id"]
            )
        )
        tool_records.append({
            "tool_name": tool_name,
            "arguments": json.dumps(args, ensure_ascii=False),
            "tool_result": tool_result
        })

    return {
        "message": tool_messages,
        # tool_records没有add_messages规则，所以明确返回累计后的列表。
        "tool_records": state["tool_records"] + tool_records
    }


def choose_next(state):         #edge指路，去定下来接下来的走向
    if state["status"] == "max_calls_reached":
        return "end"
    messages = state["message"][-1]
    if messages.tool_calls:
        return "tools"
    return "end"


# 登记节点和连线；compile只准备流程，不发送任何模型请求。
builder = StateGraph(State)
builder.add_node("model", model_node)
builder.add_node("tools", tool_node)
builder.add_edge(START, "model")
builder.add_conditional_edges(
    "model", choose_next, {"tools": "tools", "end": END}
)
builder.add_edge("tools", "model")
graph = builder.compile()
# 上面保留无检查点的graph供学习、独立节点测试；实际请求在with中编译持久化版本。


def invoke_graph(graph, graph_input, config):
    try:
        return graph.invoke(graph_input, config=config, durability="sync")
    except Exception as error:
        logger.error("session=%r graph_failed error_type=%s",
                     config["configurable"]["thread_id"], type(error).__name__)
        raise


def run_agent(question, session_id):
    logger.info("session=%r request_started", session_id)
    # 我们用相同的字符串对应两个编号，不要求用户再输入一个thread_id。
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MAX_GRAPH_STEPS
    }
    with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        snapshot = graph.get_state(config)
        if snapshot.interrupts:
            raise ValueError("这个会话正在等待人工确认，请先调用/confirm，或换一个session_id")
        if snapshot.next:
            # 不把新问题塞进尚未完成的旧任务，先让用户明确恢复。
            raise ValueError("这个会话有未完成流程，请先调用/resume恢复，或换一个session_id")

        if snapshot.values:
            # 检查点已经有完整消息，不能再次extend数据库历史，否则会重复。
            new_start = len(snapshot.values["message"])
            message = [{"role": "user", "content": question}]
        else:
            # 第一次使用检查点：沿用原来的system、旧聊天历史、当前问题。
            history_message = get_history(session_id)
            message, new_start = build_message(question, history_message)

        state = {
            "message": message,
            "model_calls": 0,
            "tool_records": [],
            "status": "running",
            "final_answer": None,
            "new_start": new_start
        }
        # checkpointer会在图执行时保存快照，不用在每个节点里手动写SQL。
        state = invoke_graph(graph, state, config)
    return finish_turn(session_id, state)


def resume_agent(session_id):
    """不输入新问题，按检查点记录的下一步继续；不是从Python语句中间恢复。"""
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MAX_GRAPH_STEPS
    }
    with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        snapshot = graph.get_state(config)
        if not snapshot.values:
            raise ValueError("没有找到这个session_id的检查点")
        if snapshot.interrupts:
            # 普通故障恢复不能绕过人工确认，也不能默认代表同意。
            raise ValueError("流程正在等待人工确认，请通过/confirm提交同意或拒绝")
        if not snapshot.next:
            # 已完成的任务只返回已有结果，不再次调用模型或重复写入历史。
            return snapshot.values
        # None表示继续已有状态，不是添加一个新的用户问题，也不清零调用次数。
        logger.info("session=%r resume_started", session_id)
        state = invoke_graph(graph, None, config)
    return finish_turn(session_id, state)


def confirm_agent(session_id, confirmation_id, approved):
    """只接受当前待确认操作的决定；不接受客户端替换文件名或内容。"""
    if type(approved) is not bool:
        raise ValueError("approved必须是布尔值")
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MAX_GRAPH_STEPS
    }
    with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        snapshot = graph.get_state(config)
        if not snapshot.interrupts:
            raise ValueError("这个会话没有等待确认的操作；不要重复提交旧决定")
        pending = snapshot.interrupts[0]
        expected_id = f"{pending.id}:{pending.value['tool_call_id']}"
        if confirmation_id != expected_id:
            raise ValueError("确认编号已过期或不属于当前操作，请先查看/state中的待确认信息")
        # 使用相同thread_id恢复；用户的布尔值会成为interrupt()的返回值。
        logger.info("session=%r confirmation_received approved=%s", session_id, approved)
        state = invoke_graph(
            graph, Command(resume={pending.id: approved}), config
        )
    return finish_turn(session_id, state)


def pending_tool_info(pending):
    """把LangGraph中断对象整理为接口能返回的普通字典。"""
    return {
        "confirmation_id": f"{pending.id}:{pending.value['tool_call_id']}",
        "tool_call_id": pending.value["tool_call_id"],
        "tool_name": pending.value["tool_name"],
        "arguments": pending.value["arguments"]
    }


def get_saved_state(session_id):
    """只读状态，不执行节点、不调用模型；next为空表示当前没有待运行节点。"""
    config = {"configurable": {"thread_id": session_id}}
    with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        snapshot = graph.get_state(config)
        if not snapshot.values:
            return {"session_id": session_id, "exists": False}
        state = snapshot.values
        return {
            "session_id": session_id,
            "exists": True,
            "next": list(snapshot.next),
            "status": "waiting_confirmation" if snapshot.interrupts else (
                "unfinished" if snapshot.next else state["status"]
            ),
            "pending_tool": pending_tool_info(snapshot.interrupts[0]) if snapshot.interrupts else None,
            "model_calls": state["model_calls"],
            "tool_records": state["tool_records"],
            "final_answer": state["final_answer"],
            "message": convert_to_openai_messages(state["message"])
        }


def finish_turn(session_id, state):
    """沿用原来的运行记录与聊天历史保存；检查点是另一套独立保存。"""
    if state.get("__interrupt__"):
        # 暂停不是完成。不要把没有tool结果的半套消息写入普通聊天历史。
        state = dict(state)
        state["status"] = "waiting_confirmation"
        state["final_answer"] = None
        state["pending_tool"] = pending_tool_info(state["__interrupt__"][0])
        logger.info("session=%r waiting_confirmation tool=%s not_executed",
                    session_id, state["pending_tool"]["tool_name"])
        return state

    # chat.db是本次新增聊天记录；checkpoints.db是执行过程快照，两者不等价。
    save_turn(
        session_id,
        convert_to_openai_messages(state["message"][state["new_start"]:])
    )
    logger.info("session=%r turn_finished status=%s model_calls=%s tool_records=%s",
                session_id, state["status"], state["model_calls"], len(state["tool_records"]))
    return state

#- State：当前流程的数据，比如消息列表；需要时也可以放调用次数、工具记录等。
#- 模型节点：取出消息，调用大模型，把模型回复交回状态。
#- 工具节点：Python后端根据模型请求执行工具，把执行结果交回状态。
#- Edge：规定接下来去哪个节点，或者结束。
#State存数据，Node做事情，Edge定走向。


        



 
