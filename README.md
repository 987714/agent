# 第46—48课：LangGraph循环、SQLite检查点与人工确认

## 56课：差旅报销演示工作台

页面由 FastAPI 同源提供，不需要 Node.js 或另开前端服务。首次配置时，在本课目录进入 Python 环境，执行 `python -m pip install -r requirements.txt`，复制 `.env.example` 为 `.env`，填入自己的 `API_KEY`、`BASE_URL` 和 `MODEL_NAME`。已有配置就不用重做，分享项目时不要分享 `.env`。

```powershell
conda activate agent
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

1. 打开 `http://127.0.0.1:8000/`（接口调试仍用 `/docs`）。点选上海示例，再点「发送问题」。预期住宿上限为每人每晚 600 元，超出 130 元，回答注明本地教学制度出处。首次加载检索模型可能较慢。
2. 点「请求保存这份回答」，右栏应出现待确认文件名和内容。点「拒绝」，核对 `workspace_files` 没有生成该文件。
3. 再请求保存，核对预览后点「同意保存」，检查对应文件是否生成。这一步才会执行实际写入。

页面刷新会新开会话，不会自动取消服务器上已暂停的旧会话。工作台仅用于本地演示，不把会话编号当身份认证，不开放到公网。

## 54课：先计时，再判断是否优化

手动基线：同一道“北京住宿650元，按本地制度超出多少”题，首次检索约120秒；
同一服务进程、新会话重复提问约3～4秒。首次日志出现本地模型权重加载；
这些是用户估计的总耗时，不能把差值全部归因于加载。

`model_finished` 的 `elapsed_ms` 是一次成功返回的模型调用耗时；
`tool_elapsed` 是一次工具处理耗时，含校验，首次检索也包含本地初始化。
等待用户确认的时间不计入工具耗时。这两项不是整次 HTTP 请求耗时。
当前先保留按需加载和原有检索流程；若第一问仍需更快，再评估启动预热的取舍。

## 52课：按会话查看日志

启动 Uvicorn 后在服务终端看 `session=`，同一会话的请求和确认使用相同编号。
`model_start` 表示开始调用模型，`tool_start` 表示开始实际执行工具；
`waiting_confirmation` 表示尚未执行、在等确认，`confirmation_received` 表示收到决定。
保存结果用 `saved`、`rejected_not_written` 或 `existing_file_not_overwritten` 区分；
`graph_failed` 记录异常类型，`turn_finished` 记录本轮状态和调用计数。
新增的流程日志不记录问题、工具参数、文件正文、密钥或原始异常文本。会话编号请勿填写敏感信息。

不用启动服务即可验证等待和拒绝日志：

```powershell
python -m unittest test_confirmation.ConfirmationTests.test_logs_trace_rejected_save_without_exposing_content -v
```

## 51课：运行自动化测试

在本目录的 `agent` 环境执行 `python -m unittest discover -v`，不用启动 FastAPI。
看到 `OK` 表示全部通过；如果出现 `FAIL`，先看失败的测试名和 `AssertionError`，对照预期与实际结果。

- `test_integration.py`：检查工具校验、模型与工具循环、调用上限和接口函数。
- `test_checkpoint.py`：检查中断后恢复、历史不重复和会话隔离。
- `test_confirmation.py`：检查同意、拒绝、确认编号和文件写入边界。51课补测：即使同意保存，已有文件也不能被覆盖。

测试用模拟模型固定发出工具请求，文件和数据库用临时目录隔离；不测试真实模型的工具选择能力。

本目录以lesson45为基础，lesson45原文件不改。
保留ask_model、message、messages、functions、execute_tool、run_agent等名称。
46课建立循环；按用户要求，47课直接在本目录加入检查点与未完成流程恢复。
48课继续在本目录增加save_file执行前人工确认，不新增业务工具。

## 本课只改变什么

原来agent.py在for循环里完成模型调用、工具执行、判断结束。
现在agent.py明确拆成：

1. State：保存message、model_calls、tool_records、status和final_answer；47课再保存new_start。
2. model_node：取消息，调用ask_model，返回这次新增回复。
3. tool_node：执行这一轮全部工具请求，返回工具结果与记录。
4. choose_next：判断进入工具节点还是结束，不在这里执行工具。
5. builder：登记节点和连线；graph = builder.compile()生成可运行的图。
6. run_agent：准备历史，graph.invoke运行图，保存本次新增消息。
7. checkpoint.py：47课新增，管理SQLite检查点连接，实际请求使用带保存器的图。

整体走向：

```text
START → model → 有工具请求？ → tools
           ↑                    │
           └────────────────────┘
           └→ 没有工具请求或达到调用上限 → END
```

模型节点可以多次执行，并不表示创建多个模型节点。
同一轮模型提出两个工具请求时，工具节点执行一次，内部遍历两个请求。
add_messages负责合并消息：新ID通常追加，相同ID更新已有消息。
tool_records仍使用普通列表；工具节点显式返回累计列表。

## 两种上限不是同一回事

- MAX_MODEL_CALLS = 5：最多真正调用聊天模型5次，沿用45课的预算。
- MAX_GRAPH_STEPS = 12：图的执行步数保护，不是允许调用模型12次。

若第5次模型仍要求工具，先执行并保存其工具结果，再回到模型节点。
这次节点只检查上限、不再请求模型，返回max_calls_reached并结束。
因此不会把缺少工具结果的半套调用写入普通历史。
若第5次模型正常给出答案，仍算completed。
本图的调用预算保证正常情况下先主动结束，不触发GraphRecursionError；
未来改连线或调低图步数上限时，仍可能触发该框架错误。

## 保持原样的部分

FastAPI请求和响应、SQLite消息表、工具校验与失败包装、RAG各算法不改。
RAG工具仍可使用，但46课首先用简单工具验证节点与连线。
没有复制45课的chat.db；46课启动后创建自己的数据库。
.env和资料已复制，不在说明或测试中输出密钥。
同一Windows用户的Hugging Face缓存共享，不需要因为新目录重新下载模型。

## 自动验证

在lesson46目录、agent环境执行：

```powershell
python -m unittest test_integration test_checkpoint test_confirmation -v
```

测试运行真实的LangGraph图，用模拟聊天回复代替付费请求。
覆盖直接回答、多轮工具、同轮多个请求、部分失败、保存拦截、
历史消息合并、SQLite往返、模型调用上限和框架步数限制等。
这些测试不代表真实模型端到端验收已经完成。

## 启动和手动验收

为避免与45课仍在运行的8000端口混淆，本课先用8001：

```powershell
$env:HF_HUB_OFFLINE="1"
python -m uvicorn main:app --port 8001
```

打开 http://127.0.0.1:8001/docs，展开POST /chat。
每次测试换一个session_id：

1. 直接回答：
   {"session_id":"lesson46-direct-01","message":"你好，请简单介绍你的作用，不需要调用工具。"}
2. 单轮工具：
   {"session_id":"lesson46-add-01","message":"请使用add计算10加1。"}
3. 多轮工具：
   {"session_id":"lesson46-multi-01","message":"先调用add计算10加1，再把该结果作为a、3作为b调用reduce。请分步骤使用工具。"}

预期最后一题先得到11，再得到8；模型具体是否分轮提出请求，以终端记录为准。
接口返回结构不变，终端会打印模型调用次数和实际工具调用次数。
上限测试由自动模拟完成，不要求真实模型故意无限调用、浪费额度。

## 47课：每个文件改了什么

- 新增checkpoint.py：get_checkpointer()打开SQLite保存器，用完关闭连接。
- agent.py：State新增new_start；实际请求compile(checkpointer=...)；
  config中thread_id直接使用session_id；以同步持久化方式保存检查点后继续下一步。
  新增resume_agent、get_saved_state；原结尾打印和聊天历史保存移到finish_turn。
- main.py：保留POST /chat；新增GET /state/{session_id}和POST /resume/{session_id}。
  未完成会话提交新问题时返回409，不覆盖旧流程。
- requirements.txt：增加langgraph-checkpoint-sqlite依赖。
- .gitignore：排除checkpoints.db及其辅助文件。
- test_integration.py：沿用46课测试，每个用例使用独立临时检查点数据库。
- 新增test_checkpoint.py：测试故障后恢复、独立子进程读取、历史不重复和会话隔离。
- 本README补充操作说明。tools.py、llm_client.py、database.py、schemas.py和RAG算法未改。

## 两个SQLite文件的区别

- chat.db：原database.py保存的聊天记录，仍在整轮结束后归档。
- checkpoints.db：LangGraph执行中的状态快照，由保存器自动建表和读写。

它们使用同一个session_id字符串区分会话；LangGraph配置里这个键叫thread_id。
第一次没有检查点时，才从chat.db导入历史和system。
之后图自己有完整消息，每次只输入新问题，不能再把所有历史重复extend进去。
每个新问题重置5次模型调用预算；恢复旧任务则继续原预算。

## 47课手动验证顺序

1. 停止旧服务，再按上面命令启动。通过POST /chat完成一次简单加法，session_id用lesson47-check-01。
2. GET /state/{session_id}输入相同编号：exists应为true，next应为空列表，能看到消息和记录。
3. 关闭并重启服务，再GET同一编号：仍能读到状态，不需要重新调用聊天模型。
4. 同一编号再POST /chat一个新问题：应保留上下文，不重复加入旧消息；模型调用计数按新问题重新开始。
5. POST /resume/{session_id}：有未完成节点时才继续；已完成时仅返回已有结果，不重新执行。

中断恢复的确定性验证由test_checkpoint.py完成：模拟第二次模型调用抛出异常，
此时工具已完成，检查点next为model；重新导入Agent后恢复，确认add没有执行第二次。
测试还启动独立Python子进程读取文件，验证不是只在内存里保存。
不要求你通过拔网线、杀进程制造真实故障；若实际模型请求失败，也可以先GET查看再决定是否恢复。

## 本课边界

- 检查点只保存可持久化状态，不保存Python内存、正在下载的网络流或模型权重。
- 恢复是从可恢复的节点调度继续，不是从某条Python语句中间继续。
- 异常节点可能重跑；一个工具节点内若前几个工具成功、后面崩溃，不能保证前几个绝不重复。
- 47课阶段save_file保持禁止；48课改为下节说明的人工确认。本地教学先单进程、顺序测试，同一会话不要并发请求。
- chat.db归档和图检查点不是一个跨库原子事务；极端情况下图已完成但归档失败，
  检查点仍可读取，但本课没有增加聊天归档的自动补偿或exactly-once机制。

## 48课：本次具体改动

1. agent.py：tool_node先校验并收集所需确认，使用interrupt暂停，之后才遍历执行工具。
   同意的save_file执行；拒绝的返回失败消息，其他工具继续。
   新增confirm_agent和pending_tool_info；finish_turn遇到中断时直接返回待确认信息，
   不把缺少工具结果的半套消息存入chat.db。run_agent和resume_agent不能绕过待确认状态。
2. schemas.py：ConfirmRequest接收confirmation_id和严格布尔approved；
   ResponseModel新增可选pending_tool，展示具体文件名与完整待写内容。
3. main.py：新增POST /confirm/{session_id}；/chat、/resume响应可携带pending_tool。
4. tools.py：只更新save_file说明与注释，原路径限制、UTF-8写入和不覆盖已有文件都不变。
5. prompt.py：增加用户拒绝后不自行重试写入、未写入不声称保存成功的规则。
6. test_integration.py：原写入拦截用例改成明确拒绝确认；新增test_confirmation.py验证确认流程。
7. 本README补充测试步骤。不新增依赖、不新增任务表，checkpoint.py和database.py不变。

### 为什么先确认、后执行整轮工具

LangGraph恢复interrupt所在节点时，会从节点开头重跑。
因此同一轮如果有add、save_file，我们在add真正执行前就先完成save_file的确认。
同一轮有多个save_file时逐个询问，全部决定收齐后再按原顺序执行。
暂停之前只有校验和确认，不先执行部分工具，避免恢复时重放前面的工具。
决定只保存在LangGraph恢复机制中，不额外增加审批数据库。

### docs测试人工确认

重启服务，继续使用之前的端口。先POST /chat：

```json
{"session_id":"lesson48-approve-01","message":"请新建lesson48-demo.txt，内容为：这是一次人工确认测试。"}
```

预期status为waiting_confirmation、answer为null、pending_tool列出文件名和内容。
此时workspace_files里不应出现该文件。复制pending_tool.confirmation_id。

再POST /confirm/{session_id}，路径填lesson48-approve-01，请求体：

```json
{"confirmation_id":"粘贴本次返回的完整编号","approved":true}
```

预期文件写入，模型继续回答；实际写入内容以确认前展示的arguments为准，
不能在确认请求中另传参数替换。
测试拒绝时换新session_id和新文件名，approved传false，文件不应产生。
不要把布尔false写成字符串"false"，后者会被请求模型拒绝。

GET /state/{session_id}也能查看当前待确认内容；重启后仍能找到它。
POST /resume不能代表同意，会提示使用/confirm。旧编号或重复决定会被拒绝。
一轮多个待写文件时，每次确认后可能再次返回waiting_confirmation，按新的编号继续决定。

### 仍然明确的边界

接口仅用于当前本机教学，没有增加用户登录授权；知道会话ID不等于真正的身份权限。
同一会话不要并发提交确认。拒绝后不重试主要由系统提示约束，不是永久禁止该文件写入。
本课避免的是“确认暂停导致前面工具重跑”；不是对进程崩溃等所有故障承诺exactly-once。
如果真正写入后、工具节点提交检查点前突然崩溃，恢复时工具仍可能重跑；save_file的x模式
会拒绝覆盖已有文件，但这并不是通用副作用去重方案。其他外部写入工具以后需单独设计。
