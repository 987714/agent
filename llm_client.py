from langchain_openai import ChatOpenAI
from config import API_KEY,BASE_URL,MODEL_NAME

model = ChatOpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    model=MODEL_NAME,
    max_tokens=10000,
    use_responses_api=False  # 沿用原来的Chat Completions兼容接口
)

def ask_model(message, tools):
    # 名称不变，内部换成LangChain：绑定工具说明，再调用聊天模型。
    model_with_tools = model.bind_tools(tools)
    messages = model_with_tools.invoke(message)
    return messages
