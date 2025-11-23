const API_BASE = "/api/v1";

const App = {
    state: {
        chatId: null,
        moduleId: null,
        tempModule: null,
        theme: localStorage.getItem('kovcheg_theme') || 'dark',
        controller: null
    },

    init() {
        console.log("Kovcheg UI Initializing...");
        this.applyTheme(this.state.theme);
        this.loadChats();
        this.loadModules();
        this.setupInput();

        setTimeout(() => {
            const splash = document.getElementById('splash-screen');
            if (splash) {
                splash.style.opacity = '0';
                setTimeout(() => splash.remove(), 500);
            }
            // Автостворення чату, якщо історія пуста
            setTimeout(() => {
                const chats = document.querySelectorAll('#chat-list .nav-item');
                if (chats.length === 0) this.createNewChat();
            }, 600);
        }, 1200);
    },

    // --- ЧАТИ ---
    async loadChats() {
        try {
            const res = await fetch(`${API_BASE}/chats`);
            const chats = await res.json();
            const list = document.getElementById('chat-list');
            list.innerHTML = '';

            if (chats.length === 0) {
                list.innerHTML = '<div style="padding:10px; font-size:0.8rem; color:var(--text-tertiary)">Історія пуста</div>';
                return;
            }

            chats.forEach(chat => {
                const div = document.createElement('div');
                div.className = 'nav-item chat-item';
                if (chat.id === this.state.chatId) div.classList.add('active');
                
                // Використовуємо App.openChat замість this, щоб уникнути втрати контексту
                div.onclick = () => App.openChat(chat.id);

                div.innerHTML = `
                    <span class="chat-title">${chat.title}</span>
                    <button class="btn-del" onclick="event.stopPropagation(); App.deleteChat('${chat.id}')">✕</button>
                `;
                list.appendChild(div);
            });
        } catch (e) {
            console.error("Load chats error:", e);
        }
    },

    async createNewChat() {
        try {
            const title = "Чат " + new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            const res = await fetch(`${API_BASE}/chats`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title})
            });
            const chat = await res.json();
            await this.loadChats();
            this.openChat(chat.id);
        } catch (e) {
            this.showToast("Помилка створення", true);
        }
    },

    async deleteChat(id) {
        if (!confirm("Видалити цей чат?")) return;
        try {
            await fetch(`${API_BASE}/chats/${id}`, {method: 'DELETE'});
            if (this.state.chatId === id) {
                this.state.chatId = null;
                document.getElementById('chat-history').innerHTML = '';
                document.getElementById('active-chat-title').innerText = "Новий чат";
            }
            this.loadChats();
        } catch (e) {
            this.showToast("Помилка видалення", true);
        }
    },

    async openChat(id) {
        this.state.chatId = id;
        document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
        // Оновлюємо список, щоб підсвітити активний (простий спосіб)
        this.loadChats();
        
        this.switchView('chat');

        try {
            const res = await fetch(`${API_BASE}/chats/${id}`);
            const data = await res.json();
            
            document.getElementById('active-chat-title').innerText = data.title;
            const historyEl = document.getElementById('chat-history');
            historyEl.innerHTML = '';

            if (data.messages.length === 0) {
                this.renderMessage('system', 'Вітаю! Оберіть модуль або завантажте файл.');
            } else {
                data.messages.forEach(msg => this.renderMessage(msg.role, msg.content));
            }
            this.scrollToBottom();
        } catch (e) {
            this.showToast("Не вдалося відкрити чат", true);
        }
    },

    // --- МОДУЛІ (ВИПРАВЛЕНО) ---
    async loadModules() {
        const grid = document.getElementById('packages-grid');
        grid.innerHTML = '<p class="loading-text">Оновлення...</p>';

        try {
            const res = await fetch(`${API_BASE}/modules`);
            const modules = await res.json();
            grid.innerHTML = '';

            if (modules.length === 0) {
                grid.innerHTML = '<p style="text-align:center; color:var(--text-secondary)">Немає модулів.</p>';
                return;
            }

            modules.forEach(mod => {
                const uiMod = {
                    id: mod.id,
                    title: mod.title || "Без назви",
                    version: mod.version || "1.0",
                    size: mod.size || "Unknown",
                    desc: mod.description || "Локальний модуль",
                    verified: mod.verified || false
                };

                const card = document.createElement('div');
                card.className = 'pkg-card fade-enter';
                
                // Клік на картку відкриває інспектор
                card.onclick = (e) => {
                    // Якщо клікнули не по кнопці, відкриваємо інспектор
                    if(!e.target.closest('button')) App.openInspector(uiMod);
                };

                const badge = uiMod.verified 
                    ? '<span style="color:#10b981; border:1px solid #10b981; padding:2px 6px; border-radius:10px; font-size:0.7rem;">Verified</span>'
                    : '<span style="color:#ef4444; border:1px solid #ef4444; padding:2px 6px; border-radius:10px; font-size:0.7rem;">Unsigned</span>';

                card.innerHTML = `
                    <div class="pkg-header">
                        <div class="pkg-title">${uiMod.title}</div>
                        ${badge}
                    </div>
                    <div class="pkg-meta" style="margin-top:10px; font-size:0.85rem; color:var(--text-secondary);">
                        ${uiMod.desc}
                    </div>
                    <div class="pkg-footer" style="margin-top:auto; padding-top:15px; border-top:1px solid var(--border-color); display:flex; align-items:center; justify-content:space-between;">
                        <span style="font-size:0.8rem;">💾 ${uiMod.size}</span>
                        <button class="btn-secondary" style="padding:6px 12px; font-size:0.8rem;" onclick="App.quickActivate('${uiMod.id}', '${uiMod.title}')">
                            Активувати
                        </button>
                    </div>
                `;
                grid.appendChild(card);
            });

        } catch (e) {
            grid.innerHTML = `<p class="loading-text" style="color:var(--danger-color)">Помилка: ${e.message}</p>`;
        }
    },

    // Пряма активація з картки
    quickActivate(id, title) {
        this.state.moduleId = id;
        this.updateModuleIndicator(title);
        this.showToast(`Модуль "${title}" підключено`);
        this.switchView('chat');
        if (!this.state.chatId) this.createNewChat();
    },

    openInspector(mod) {
        this.state.tempModule = mod;
        document.getElementById('ins-title').textContent = mod.title;
        document.getElementById('ins-id').textContent = mod.id;
        document.getElementById('ins-version').textContent = mod.version;
        document.getElementById('inspector').classList.add('open');
    },

    closeInspector() {
        document.getElementById('inspector').classList.remove('open');
        this.state.tempModule = null;
    },

    // Активація з інспектора
    activateCurrentPackage() {
        if (this.state.tempModule) {
            this.quickActivate(this.state.tempModule.id, this.state.tempModule.title);
            this.closeInspector();
        }
    },

    updateModuleIndicator(title) {
        const el = document.getElementById('module-indicator');
        if (el) {
            el.innerHTML = `<span class="status-dot online"></span> ${title}`;
            el.style.color = 'var(--success-color)';
        }
    },

    // --- ПОВІДОМЛЕННЯ ---
    async sendMessage() {
        const input = document.getElementById('chat-input');
        const query = input.value.trim();
        if (!query) return;

        if (!this.state.chatId) await this.createNewChat();

        input.value = '';
        input.disabled = true;
        input.style.height = 'auto';
        this.hideCitations();

        this.renderMessage('user', query);
        const botMsgId = this.renderMessage('system', '<span class="typing-cursor">▋</span>');
        const botBubble = document.getElementById(botMsgId).querySelector('.msg-bubble');
        
        let fullText = '';
        if (this.state.controller) this.state.controller.abort();
        this.state.controller = new AbortController();

        try {
            const res = await fetch(`${API_BASE}/chats/${this.state.chatId}/ask_stream`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    query, 
                    module_id: this.state.moduleId
                }),
                signal: this.state.controller.signal
            });

            if (!res.ok) throw new Error(`Error: ${res.status}`);

            const reader = res.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, {stream: true});
                const lines = chunk.split('\n').filter(l => l.trim());

                for (const line of lines) {
                    try {
                        const json = JSON.parse(line);
                        if (json.type === 'token') {
                            fullText += json.content;
                            botBubble.innerHTML = this.formatText(fullText);
                            this.scrollToBottom();
                        } else if (json.type === 'sources') {
                            this.renderCitations(json.data);
                        }
                    } catch (e) {}
                }
            }
        } catch (e) {
            if (e.name !== 'AbortError') botBubble.innerText = `Помилка: ${e.message}`;
        } finally {
            input.disabled = false;
            input.focus();
            this.state.controller = null;
        }
    },

    // --- ФАЙЛИ ---
    async uploadFile(input) {
        if (input.files.length === 0) return;
        if (!this.state.chatId) await this.createNewChat();

        const file = input.files[0];
        this.renderMessage('system', `⏳ Обробка файлу: ${file.name}...`);
        
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`${API_BASE}/chats/${this.state.chatId}/upload`, {
                method: 'POST',
                body: formData
            });
            if (!res.ok) throw new Error("Upload failed");
            const data = await res.json();
            
            const lastMsg = document.querySelector('#chat-history .msg:last-child .msg-bubble');
            lastMsg.innerHTML = `✅ Файл <b>${data.filename}</b> додано до контексту!`;
        } catch (e) {
            this.renderMessage('system', `❌ Помилка: ${e.message}`);
        }
        input.value = '';
    },

    // --- UI UTILS ---
    switchView(viewName) {
        document.querySelectorAll('.view-container').forEach(el => {
            el.classList.add('hidden');
            el.classList.remove('active');
        });
        const target = document.getElementById(`view-${viewName}`);
        if (target) {
            target.classList.remove('hidden');
            target.classList.add('active');
        }
        this.closeInspector();
    },

    renderMessage(role, html) {
        const hist = document.getElementById('chat-history');
        const div = document.createElement('div');
        div.className = `msg ${role}`;
        div.id = 'msg-' + Date.now();
        div.innerHTML = `<div class="msg-avatar">${role==='user'?'👤':'🤖'}</div><div class="msg-bubble">${html}</div>`;
        hist.appendChild(div);
        this.scrollToBottom();
        return div.id;
    },

    renderCitations(sources) {
        const panel = document.getElementById('citation-panel');
        const content = document.getElementById('citation-content');
        content.innerHTML = '';
        sources.forEach((s, i) => {
            const div = document.createElement('div');
            div.className = 'citation-item';
            div.innerHTML = `<div style="font-weight:bold; font-size:0.75rem; color:var(--accent-color)">Джерело #${i+1} (${Math.round(s.score*100)}%)</div><div style="font-size:0.9rem">${s.chunk}</div>`;
            content.appendChild(div);
        });
        panel.classList.remove('hidden');
    },

    hideCitations() { document.getElementById('citation-panel').classList.add('hidden'); },
    
    scrollToBottom() {
        const el = document.getElementById('chat-history');
        if (el) el.scrollTop = el.scrollHeight;
    },

    formatText(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, '<br>');
    },

    setupInput() {
        const tx = document.getElementById('chat-input');
        if (!tx) return;
        tx.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
        tx.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
    },

    toggleTheme() {
        this.state.theme = this.state.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('kovcheg_theme', this.state.theme);
        this.applyTheme(this.state.theme);
    },

    applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
    },

    showToast(msg, isError = false) {
        const t = document.getElementById('toast');
        const m = document.getElementById('toast-msg');
        if (t && m) {
            m.textContent = msg;
            t.style.backgroundColor = isError ? 'var(--danger-color)' : 'var(--text-primary)';
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 3000);
        }
    }
};

document.addEventListener('DOMContentLoaded', () => App.init());
