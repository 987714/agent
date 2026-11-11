import { sendMessage, confirmSave } from "./api.js";

const $ = (id) => document.getElementById(id);
const question = $("question");
const examples = [...document.querySelectorAll("[data-example]")];
let sessionId;
let busy = false;
let pending = null;
let lastAnswer = "";

function showError(id, message = "") {
    $(id).textContent = message;
    $(id).hidden = !message;
}

function updateControls() {
    for (const control of [question, $("send"), ...examples]) {
        control.disabled = busy || Boolean(pending);
    }
    $("new-chat").disabled = busy || Boolean(pending);
    $("prepare").hidden = !lastAnswer || Boolean(pending);
    $("prepare").disabled = busy;
    $("approve").disabled = $("reject").disabled = busy;
}

// 只解析常用的粗体、行内代码和列表。模型文字不作为 HTML 执行。
function inline(element, line) {
    for (const part of line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
            const strong = document.createElement("strong");
            strong.textContent = part.slice(2, -2);
            element.append(strong);
        } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
            const code = document.createElement("code");
            code.textContent = part.slice(1, -1);
            element.append(code);
        } else {
            element.append(document.createTextNode(part));
        }
    }
}

function addMessage(author, text, formatted = false) {
    const entry = document.createElement("article");
    entry.className = "message";
    const label = document.createElement("b");
    label.textContent = author;
    entry.append(label);
    let list = null;
    for (const line of (formatted ? text.split("\n") : [text])) {
        if (formatted && !line.trim()) {
            list = null;
            continue;
        }
        const bullet = formatted && line.match(/^\s*[-*]\s+(.+)/);
        if (bullet && !list) {
            list = document.createElement("ul");
            entry.append(list);
        }
        if (!bullet) list = null;
        const element = document.createElement(bullet ? "li" : "p");
        if (formatted) inline(element, bullet ? bullet[1] : line.replace(/^#{1,6}\s+/, ""));
        else element.textContent = line;
        (list || entry).append(element);
    }
    $("messages").append(entry);
}

function updateSources(answer) {
    const names = [...new Set(answer.match(/[\p{L}\p{N}_-]+\.(?:md|txt)\b/gu) || [])];
    $("source-list").replaceChildren();
    for (const name of names) {
        const item = document.createElement("li");
        item.textContent = name;
        $("source-list").append(item);
    }
    $("source-list").hidden = !names.length;
    $("source-note").textContent = names.length
        ? "从最新业务回答中提取的文件名，具体条款见左侧回答。"
        : "最新业务回答未注明制度文件。";
}

function applyResult(result, saving = false) {
    if (result.status === "waiting_confirmation") {
        const tool = result.pending_tool;
        if (tool?.tool_name !== "save_file" || !tool.confirmation_id
            || typeof tool.arguments?.file_name !== "string" || typeof tool.arguments?.content !== "string") {
            throw new Error("无法预览待确认操作。请到接口文档查看会话状态。");
        }
        pending = tool;
        $("file-name").textContent = tool.arguments.file_name;
        $("file-content").textContent = tool.arguments.content;
        $("preview").hidden = false;
        $("save-note").textContent = "尚未写入。请核对文件名和完整内容，再做决定。";
        $("status").textContent = "等待你确认保存。";
        $("file-name").focus();
        return;
    }
    pending = null;
    $("preview").hidden = true;
    $("save-note").textContent = "想保留结果？先让助手生成一份文件。它会暂停，等你核对后再写入。";
    if (typeof result.answer === "string" && result.answer.trim()) {
        addMessage("差旅助手", result.answer, true);
        if (!saving) {
            lastAnswer = result.answer;
            updateSources(result.answer);
        }
        $("status").textContent = "本轮已结束。";
    } else {
        $("status").textContent = result.status === "max_calls_reached"
            ? "本轮达到调用上限。请缩小问题范围再试。"
            : "本轮没有返回可显示的回答。";
    }
}

async function ask(text, saving = false) {
    if (!text || busy || pending) return;
    busy = true;
    updateControls();
    showError("error");
    addMessage("你", text);
    $("status").textContent = "正在处理。首次查制度可能需要加载本地模型。";
    try {
        applyResult(await sendMessage(sessionId, text), saving);
    } catch (error) {
        showError("error", error.message + "。如果连接中断，请先确认服务仍在运行。");
        $("status").textContent = "未收到本轮结果。";
        if (!saving) question.value = text;
    } finally {
        busy = false;
        updateControls();
    }
}

async function decide(approved) {
    if (!pending || busy) return;
    busy = true;
    updateControls();
    showError("confirm-error");
    $("status").textContent = "正在提交你的决定。";
    try {
        applyResult(await confirmSave(sessionId, pending.confirmation_id, approved), true);
    } catch (error) {
        showError("confirm-error", error.message + "。如果连接中断，请先核对会话状态和文件。");
        $("status").textContent = "未收到确认结果。";
    } finally {
        busy = false;
        updateControls();
        if (!pending) question.focus({ preventScroll: true });
    }
}

function newSession() {
    sessionId = "demo-" + crypto.randomUUID();
    pending = null;
    lastAnswer = "";
    question.value = "";
    $("messages").replaceChildren();
    $("preview").hidden = true;
    $("source-list").hidden = true;
    $("source-list").replaceChildren();
    $("source-note").textContent = "回答提到的制度文件会列在这里。";
    $("status").textContent = "首次查制度可能需要加载本地模型。";
    showError("error");
    showError("confirm-error");
    updateControls();
}

$("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = question.value.trim();
    if (!text || busy || pending) return;
    question.value = "";
    ask(text);
});
for (const button of examples) {
    button.addEventListener("click", () => {
        question.value = button.dataset.example;
        question.focus();
    });
}
$("prepare").addEventListener("click", () => {
    ask("请把上一份报销回答整理成 Markdown 文件，保留计算结果和制度出处，并请求保存。文件名使用 trip-" + sessionId + ".md。", true);
});
$("approve").addEventListener("click", () => decide(true));
$("reject").addEventListener("click", () => decide(false));
$("new-chat").addEventListener("click", () => { newSession(); question.focus(); });
newSession();
