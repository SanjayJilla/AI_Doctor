

const TOKEN    = localStorage.getItem("token");
const USERNAME = localStorage.getItem("username") || "User";


if (!TOKEN || TOKEN === "null" || TOKEN === "undefined") {
    window.location.href = "/";
} else {
    document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("nav-username").textContent = USERNAME;
        loadHistory();
    });
}


function authHeader() {
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + TOKEN
    };
}

function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    window.location.href = "/";
}

function setMode(mode) {

  currentMode = mode;

  const chatSection = document.getElementById("chat-section");
  const sympSection = document.getElementById("symp-section");

  const btnChat = document.getElementById("btn-chat");
  const btnSymp = document.getElementById("btn-symp");

  if (mode === "chat") {

    chatSection.style.display = "flex";
    sympSection.style.display = "none";

    btnChat.classList.add("active");
    btnSymp.classList.remove("active");

  } else {

    chatSection.style.display = "none";
    sympSection.style.display = "flex";

    btnChat.classList.remove("active");
    btnSymp.classList.add("active");
  }
}

function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function autoResize(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

function suggest(text) {
    document.getElementById("chat-input").value = text;
    sendMessage();
}

let isLoading = false;

async function sendMessage() {
    const input    = document.getElementById("chat-input");
    const question = input.value.trim();
    if (!question || isLoading) return;

    input.value = "";
    input.style.height = "auto";

    // Remove welcome screen on first message
    const welcome = document.getElementById("welcome");
    if (welcome) welcome.remove();

    setLoading(true);
    addMessage("user", question, null);
    const typId = showTyping();

    try {
        const response = await fetch("/api/ask", {
            method:  "POST",
            headers: authHeader(),
            body:    JSON.stringify({ question })
        });

        if (response.status === 401 || response.status === 422) {
            logout();
            return;
        }

        const data = await response.json();
        removeTyping(typId);

        if (!response.ok || data.error) {
            addMessage("bot", "❌ " + (data.error || "Something went wrong."), null);
        } else {
            addMessage("bot", data.answer, data);
            loadHistory();
        }

    } catch (err) {
        removeTyping(typId);
        addMessage("bot", "❌ Cannot reach server. Is Flask running?", null);
    }

    setLoading(false);
}

function addMessage(role, text, data) {
    const container = document.getElementById("messages");

    const wrap = document.createElement("div");
    wrap.className = "msg " + role;

    const av = document.createElement("div");
    av.className = "avatar " + role;
    av.textContent = role === "bot" ? "🩺" : "👤";

    const bw = document.createElement("div");
    bw.className = "bubble-wrap";

    const b = document.createElement("div");
    b.className = "bubble";
    b.innerHTML = formatText(text);
    bw.appendChild(b);

    // Source badge — shows where the answer came from
    if (role === "bot" && data && data.layer) {
        const badge = document.createElement("div");
        const icons = { 1: "🗄️", 2: "🌐", 3: "🤖" };
        badge.className = "source-badge l" + data.layer;
        badge.textContent = (icons[data.layer] || "🤖") + " " + (data.layer_label || data.source || "AI");
        bw.appendChild(badge);
    }

    wrap.appendChild(av);
    wrap.appendChild(bw);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
}

// Converts **bold** and - lists into real HTML
function formatText(text) {
    if (!text) return "";
    return text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/^[-•]\s(.+)/gm, "<li>$1</li>")
        .replace(/(<li>[\s\S]*?<\/li>)+/g, function(m) { return "<ul>" + m + "</ul>"; })
        .replace(/\n\n/g, "</p><p>")
        .replace(/\n/g, "<br>")
        .replace(/^/, "<p>")
        .replace(/$/, "</p>");
}

let typCount = 0;
function showTyping() {
    const id = "typ" + (++typCount);
    const container = document.getElementById("messages");
    const el = document.createElement("div");
    el.id = id;
    el.className = "typing-wrap";
    el.innerHTML = '<div class="avatar bot">🩺</div>' +
        '<div class="typing-dots"><span></span><span></span><span></span></div>';
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function setLoading(v) {
    isLoading = v;
    document.getElementById("send-btn").disabled    = v;
    document.getElementById("chat-input").disabled  = v;
}

// ── SYMPTOM CHECKER ────────────────────────────────────────

let symptoms = [];

function sympKey(e) {
    if (e.key === "Enter") addTag();
}

function addTag() {
    const input = document.getElementById("symp-input");
    const val   = input.value.trim().toLowerCase();
    if (!val || symptoms.includes(val)) return;
    symptoms.push(val);
    input.value = "";
    renderTags();
}

function removeTag(s) {
    symptoms = symptoms.filter(function(x) { return x !== s; });
    renderTags();
}

function renderTags() {
    document.getElementById("tags-area").innerHTML = symptoms.map(function(s) {
        return '<div class="tag">' + s +
            '<button onclick="removeTag(\'' + s + '\')">×</button></div>';
    }).join("");
}

async function analyzeSymptoms() {
    // Auto-add any text left in the input field
    addTag();

    if (symptoms.length === 0) {
        alert("Please add at least one symptom.");
        return;
    }

    const btn    = document.getElementById("analyze-btn");
    const result = document.getElementById("symp-result");
    btn.disabled    = true;
    btn.textContent = "Analyzing...";
    result.classList.remove("show");

    try {
        const response = await fetch("/api/symptoms", {
            method:  "POST",
            headers: authHeader(),
            body:    JSON.stringify({ symptoms: symptoms.join(", ") })
        });

        if (response.status === 401 || response.status === 422) {
            logout();
            return;
        }

        const data = await response.json();

        if (!response.ok || data.error) {
            result.innerHTML = '<span style="color:#f87171">❌ ' + (data.error || "Error") + '</span>';
        } else {
            // BUG FIX: was reading data.message — now reads data.answer correctly
            result.innerHTML = formatText(data.answer);
        }
        result.classList.add("show");

    } catch {
        result.innerHTML = '<span style="color:#f87171">❌ Cannot reach server.</span>';
        result.classList.add("show");
    }

    btn.disabled    = false;
    btn.textContent = "Analyze";
}

// ── HISTORY ────────────────────────────────────────────────

async function loadHistory() {
    try {
        const response = await fetch("/api/history", { headers: authHeader() });
        if (response.status === 401 || response.status === 422) {
            logout();
            return;
        }
        const data     = await response.json();
        const list     = document.getElementById("history-list");

        if (!data.chats || data.chats.length === 0) {
            list.innerHTML = '<div class="hist-empty">No history yet</div>';
            return;
        }

        list.innerHTML = data.chats.map(function(c) {
            
            var q     = c.question.replace(/^\[Symptoms\]\s/, "");
            var icon  = c.question.startsWith("[Symptoms]") ? "🔍" : "💬";
            var short = q.length > 30 ? q.slice(0, 30) + "…" : q;
            return '<button class="hist-item" onclick="suggest(\'' +
                q.replace(/'/g, "\\'") + '\')">' + icon + " " + short + '</button>';
        }).join("");

    } catch (e) {
        
    }
}

async function clearHistory() {
    if (!confirm("Clear all your chat history?")) return;
    try {
        const response = await fetch("/api/history/clear", { method: "DELETE", headers: authHeader() });
        if (response.status === 401 || response.status === 422) {
            logout();
            return;
        }
        document.getElementById("history-list").innerHTML = '<div class="hist-empty">No history yet</div>';
    } catch (e) {}
}
