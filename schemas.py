from pydantic import BaseModel, StrictBool, Field           #集中放数据结构的规范

class RequestModel(BaseModel):
    message:str
    session_id:str
class ResponseModel(BaseModel):
    session_id:str
    answer:str|None
    status: str
    pending_tool: dict | None = None  # 48课：等待确认时展示工具、参数和确认编号


class ConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=1)
    approved: StrictBool  # 必须传JSON的true/false，不能用字符串"false"冒充
