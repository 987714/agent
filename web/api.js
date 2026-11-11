// 使用相对地址，页面和 API 都由同一个 FastAPI 服务提供。
async function post(path, body) {
    const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
        const detail = typeof result?.detail === "string" ? result.detail : null;
        throw new Error(detail ?? `请求失败（HTTP ${response.status}）`);
    }
    if (!result || typeof result.status !== "string") {
        throw new Error("服务没有返回有效的会话状态");
    }
    return result;
}

export function sendMessage(sessionId, message) {
    return post("/chat", { session_id: sessionId, message });
}

export function confirmSave(sessionId, confirmationId, approved) {
    if (typeof approved !== "boolean" || !confirmationId) {
        throw new TypeError("请使用待确认操作的编号，并明确同意或拒绝");
    }
    return post(`/confirm/${encodeURIComponent(sessionId)}`, {
        confirmation_id: confirmationId,
        approved,
    });
}
