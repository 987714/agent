from pathlib import Path
from langchain_core.tools import StructuredTool
from knowledge_search import search_knowledge
def add(a, b):
    return a + b


def reduce(a, b):
    return a - b

def greet(name, style="friendly"):        # 不传style时，使用Python默认值friendly
    
    if style == "formal":
        return f"您好，{name}。"
    return f"你好呀，{name}！"

WORK_DIR = Path(__file__).resolve().parent / "workspace_files"
WORK_DIR.mkdir(exist_ok=True)
def get_safe_path(file_name):
    path = Path(WORK_DIR/file_name).resolve()     #把WORK_DIR和file_name拼接在一起，resolve一下取绝对路径
    if not path.is_relative_to(WORK_DIR.resolve()):
        raise ValueError("只能访问workspace_files目录内的文件")
    if path.suffix.lower() not in (".txt", ".md"):
        raise ValueError("只支持.txt和.md文件")
    return path

def read_file(file_name):
    path = get_safe_path(file_name)
    if not path.is_file():
        raise ValueError("文件不存在或不是普通文件")
    try:
        content = path.read_text(encoding="utf-8")
    except(OSError, UnicodeDecodeError) as error:
        raise ValueError("文件无法读取，请检查权限和UTF-8编码") from error
    return content

def save_file(file_name,content):
    # 48课：Agent在调用本函数前要求人工确认；本函数仍负责真正写文件。
    # 手动直接调用会写入，确认入口位于agent.py的工具节点，不在函数内部重复写。
    path = get_safe_path(file_name)
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
    except FileExistsError as error:
        raise ValueError("文件已存在，不允许覆盖") from error
    except OSError as error:
        raise ValueError("文件保存失败，请检查目录和写入权限") from error
    return f"文件已保存：{file_name}"


functions = {"add":add,                                 #工具名到真实函数的对应表            
            "reduce":reduce,                           #把模型给出的名字，转换成可以执行的python函数
            "greet":greet,
            "read_file":read_file,
            "save_file":save_file,
            "search_knowledge":search_knowledge
            }

# 后端执行规则，不是给模型的参数，也不是一个新的工具。
# 集合中的工具具有写入副作用；Agent执行前通过interrupt等待人工确认。
TOOLS_REQUIRING_CONFIRMATION = {"save_file"}


def requires_confirmation(tool_name):
    """输入已注册的工具名字符串；返回是否需要用户确认的布尔值。"""
    if tool_name not in functions:
        raise ValueError("不允许调用未注册的工具")
    return tool_name in TOOLS_REQUIRING_CONFIRMATION

                                                    





TOOL_SCHEMAS = [                              #工具说明书的集成
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "查询本地知识资料。涉及差旅制度、住宿报销标准等问题时调用。返回相关正文、来源和片段编号，不保证资料一定含答案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要检索的完整问题"},
                    "source": {"type": "string", "description": "可选的完整文件名，例如差旅制度.md；不传或空字符串表示查全部"}
                },
                "required": ["question"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",                   #告诉接口，这是一个函数工具
        "function": {
            "name": "add",                    #工具的名称
            "parameters": {                   #工具需要的参数
                "type": "object",            
                "properties": {
                    "a": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 1000
                    },
                    "b": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 1000
                    }
                },
                "required": ["a", "b"],             #必须要有这两个参数
                "additionalProperties": False       #只能有properties什么什么列出来的参数
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reduce",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                },
                "required": ["a", "b"],
                "additionalProperties": False

            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "greet",
            "description": "根据姓名和风格生成一句问候语",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 20
                    },
                    "style": {
                        "type": "string",
                        "enum": ["friendly", "formal"]
                    }
                },
                # name必填，style可省略；默认值由greet函数提供。
                "required": ["name"],
                "additionalProperties": False
            }
        }
    },
    {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取workspace_files目录中的UTF-8文本文件",
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "文件名，例如notes.txt"
                }
            },
            "required": ["file_name"],
            "additionalProperties": False
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "save_file",
        "description": "新建workspace_files内的.txt或.md文件，不覆盖已有文件。实际写入前必须等待用户人工确认；用户拒绝后不要自行重试。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["file_name", "content"],
            "additionalProperties": False
        }
    }
}
]


# LangChain有两种常用封装方法：@tool自动推断，或StructuredTool复用已有说明。
# 本课保留你原来的TOOL_SCHEMAS和校验规则，不重写一整套参数定义。
# 把functions里的普通函数包装成工具对象，键名与函数名都保持原样。
tools = []
for schema in TOOL_SCHEMAS:
    specification = schema["function"]
    tool_name = specification["name"]
    function = functions[tool_name]
    function = StructuredTool.from_function(
        func=function,
        name=tool_name,
        description=specification.get("description", f"执行{tool_name}工具"),
        args_schema=specification["parameters"],
        infer_schema=False
    )
    functions[tool_name] = function
    tools.append(function)


def execute_tool(tool_name,args):           #tool_name输入的是一个字符串，核心是检查这个字符串是否在字典的键中
    if tool_name not in functions:
        raise ValueError("不允许调用未注册的工具")
    if not isinstance(args,dict):
        raise ValueError("工具参数必须是词典")
    if tool_name == "search_knowledge":
        if "question" not in args:
            raise ValueError("search_knowledge必须提供question")
        if set(args) - {"question", "source"}:
            raise ValueError("search_knowledge只能提供question和source")
        if not isinstance(args["question"], str) or not args["question"].strip():
            raise ValueError("question必须是非空字符串")
        if not isinstance(args.get("source", ""), str):
            raise ValueError("source必须是字符串")
    if tool_name in ("add", "reduce"):
        if set(args) != {"a", "b"}:
            raise ValueError("参数必须包含且只能包含a和b")
        a = args["a"]                    #例如字典args{"a":10,"b":1}，取出字典中键a的值，给到变量之中
        b = args["b"]

        if tool_name == "add":
            if type(a) is not int or type(b) is not int:
                raise ValueError("add的a和b必须是整数")
            if not (0<=a<=1000 and 0<=b<=1000):
                raise ValueError("add的a和b必须在0到1000之间")
        if tool_name == "reduce":
            if type(a) not in (int,float) or type(b) not in (int,float):
                raise ValueError("reduce的a和b必须是数字")

    if tool_name == "greet":
        if "name" not in args:
            raise ValueError("必须提供name")
        if set(args) - {"name", "style"}:
            raise ValueError("只能提供name和style参数")
        name = args["name"]
        if not isinstance(name,str):
            raise ValueError("name必须是字符串")
        if not(1 <= len(name) <= 20):
            raise ValueError("name长度必须在1到20之间")
        style = args.get("style","friendly")    #从字典args中取出来键style的值，如果没有这个键，就使用friendly
        if style not in("friendly","formal"):
            raise ValueError("style只能是friendly或formal")
        
    if tool_name == "read_file":
        if set(args) != {"file_name"}:
            raise ValueError("read_file必须且只能提供file_name")
        file_name = args["file_name"]
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError("file_name必须是非空字符串")
        get_safe_path(file_name)

    if tool_name == "save_file":
        if set(args) != {"file_name", "content"}:
            raise ValueError("save_file必须且只能提供file_name和content")
        file_name = args["file_name"]
        content = args["content"]
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError("file_name必须是非空字符串")
        if not isinstance(content, str):
            raise ValueError("content必须是字符串")
        get_safe_path(file_name)

    

        
        
#可以固定按这个顺序写，照着需求或 Schema 逐项检查，不用凭空想：
#1. 是否允许调用：工具名在不在 functions 中？
#2. 整体格式对不对：参数是不是字典？
#3. 必填项有没有缺：例如必须有 name。
#4. 有没有多余参数：例如只允许 name、style。
#5. 每个值的类型对不对：文本、整数、列表等。
#6. 值是否符合限制：长度、数值范围、枚举等。
#7. 业务上是否合理：例如开始日期不能晚于结束日期。
#记住一句话：
#先查结构和缺漏，再查类型，最后查取值与业务规则。
#顺序有意义：先确认是字典，才能按键取值；先确认是字符串，才能安全检查长度。
#写完后，每条规则至少准备一个反例。例如：
#规则：name必须是字符串
#反例：name=123
#规则：长度1～20
#反例：name=""，或超过20个字符
#校验函数只负责这些检查：不合格就 raise，通过就正常结束；实际执行工具仍放在主函数中。


    

