from pathlib import Path

from database import init_connection
from schemas import RequestModel,ResponseModel,ConfirmRequest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent, get_saved_state, resume_agent, confirm_agent

init_connection()
app = FastAPI()
WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="demo_assets")


@app.get("/", include_in_schema=False)
def demo():
    return FileResponse(WEB_DIR / "index.html")

def main():
    @app.post("/chat",response_model = ResponseModel)
    def chat(request:RequestModel):
        question = request.message
        session_id = request.session_id
        try:
            state = run_agent(question,session_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ResponseModel(session_id = session_id,answer = state["final_answer"],status = state["status"],pending_tool=state.get("pending_tool"))

    @app.get("/state/{session_id}")
    def read_state(session_id: str):
        # 只查看，不会再次执行图。
        return get_saved_state(session_id)

    @app.post("/resume/{session_id}", response_model=ResponseModel)
    def resume(session_id: str):
        # 恢复不需要重复输入问题，原问题和下一步已经保存在检查点中。
        try:
            state = resume_agent(session_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return ResponseModel(session_id=session_id, answer=state["final_answer"], status=state["status"], pending_tool=state.get("pending_tool"))

    @app.post("/confirm/{session_id}", response_model=ResponseModel)   # 用户只决定同意/拒绝；和检查点相关，如果同意，就使用save_file保存最终结果，不同意，就不能用save_file
    def confirm(session_id: str, request: ConfirmRequest):
        try:
            state = confirm_agent(session_id, request.confirmation_id, request.approved)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ResponseModel(session_id=session_id, answer=state["final_answer"], status=state["status"], pending_tool=state.get("pending_tool"))

main()
