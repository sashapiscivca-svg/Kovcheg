/* =========================================
   KOVCHEG V1.0: CORE LOGIC
   ========================================= */

const API_BASE = "/api/v1";

const App = {
    state: {
        chatId: null,
        moduleId: null,
        tempModule: null,
        theme: localStorage.getItem('kovcheg_theme') || 'dark',
        controller: null
    },

    async init() {
        console.log("Kovcheg Core Initializing...");
        
        // 1. Setup UI
        this.applyTheme(this.state.theme);
        this.setupInput();
        this.initTelemetry(); // Start "live" monitoring

        // 2. Load Data
        await this.loadModules(); // Load modules into Sidebar & Grid
        
        // 3. Create Session (Silent)
        // Ми завжди створюємо нову сесію при старті, оскільки історію видалено
        await this.createNewChat();

        // 4. Remove Splash Screen
        setTimeout(() => {
            const splash = document.getElementById('splash-screen');
            if (splash) {
                splash.style.opacity = '0';
                setTimeout(() => splash.remove(), 500);
            }
        }, 800);
    },

    // --- SESSION MANAGEMENT ---
    async createNewChat() {
        try {
            const title = "SESSION_" + Date.now().toString().slice(-4);
            const res = await fetch(`${API_BASE}/chats`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({title})
            });
            const chat = await res.json();
            this.state.chatId = chat.id;
            console.log(`Session initialized: ${chat.id}`);
            
            // Очистити UI при новому старті
            document.getElementById('chat-history').innerHTML = '';
            this.renderMessage('system', 'Термінал готовий. Оберіть модуль у <b>DATA CORE</b> або введіть запит.');
        } catch (e) {
            this.showToast("Помилка ініціалізації сесії", true);
        }
    },

    // --- MODULES & DATA CORE ---
    async loadModules() {
        const grid = document.getElementById('packages-grid');
        const sidebarList = document.getElementById('modules-list');
        
        // Reset UI
        if (grid) grid.innerHTML = '<p class="loading-text">Scanning storage...</p>';
        if (sidebarList) sidebarList.innerHTML = ''; // Clear loading text

        try {
            const res = await fetch(`${API_BASE}/modules`);
            const modules = await res.json();

            if (grid) grid.innerHTML = '';

            if (modules.length === 0) {
                const emptyMsg = '<div style="padding:10px; font-size:0.8rem; color:var(--text-secondary)">No modules detected.</div>';
                if (grid) grid.innerHTML = emptyMsg;
                if (sidebarList) sidebarList.innerHTML = emptyMsg;
                return;
            }

            // Render Modules
            modules.forEach(mod => {
                const uiMod = {
                    id: mod.id,
                    title: mod.title || "Untitled Module",
                    version: mod.version || "1.0",
                    size: mod.size || "Unknown",
                    desc: mod.description || "Local knowledge container",
                    verified: mod.verified || false
                };

                // 1. Render to GRID (Manager View)
                if (grid) this.renderGridCard(grid, uiMod);

                // 2. Render to SIDEBAR (Data Core)
                if (sidebarList) this.renderSidebarItem(sidebarList, uiMod);
            });

        } catch (e) {
            console.error(e);
            if (grid) grid.innerHTML = `<p class="loading-text" style="color:var(--danger-color)">Error: ${e.message}</p>`;
        }
    },

    // Рендер картки в менеджері
    renderGridCard(container, mod) {
        const card = document.createElement('div');
        card.className = 'pkg-card fade-enter';
        card.onclick = (e) => {
            if(!e.target.closest('button')) App.openInspector(mod);
        };

        const badge = mod.verified 
            ? '<span style="color:#10b981; border:1px solid #10b981; padding:2px 6px; border-radius:10px; font-size:0.7rem;">Verified</span>'
            : '<span style="color:#ef4444; border:1px solid #ef4444; padding:2px 6px; border-radius:10px; font-size:0.7rem;">Unsigned</span>';

        card.innerHTML = `
            <div class="pkg-header">
                <div class="pkg-title">${mod.title}</div>
                ${badge}
            </div>
            <div class="pkg-meta" style="margin-top:10px; font-size:0.85rem; color:var(--text-secondary);">
                ${mod.desc}
            </div>
            <div class="pkg-footer" style="margin-top:auto; padding-top:15px; border-top:1px solid var(--border-color); display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:0.8rem;">💾 ${mod.size}</span>
                <button class="btn-secondary" style="padding:6px 12px; font-size:0.8rem;" onclick="App.activateModule('${mod.id}', '${mod.title}')">
                    MOUNT
                </button>
            </div>
        `;
        container.appendChild(card);
    },

    // Рендер рядка в сайдбарі
    renderSidebarItem(container, mod) {
        const div = document.createElement('button');
        div.className = 'nav-item module-item';
        div.setAttribute('data-id', mod.id);
        div.onclick = () => this.activateModule(mod.id, mod.title);

        // Name truncation
        let displayName = mod.title;
        if (displayName.length > 22) displayName = displayName.substring(0, 20) + '..';

        div.innerHTML = `
            <span style="font-family:var(--font-mono);">${displayName}</span>
            <div class="module-status-icon" title="${mod.verified ? 'Verified' : 'Unsigned'}"></div>
        `;
        container.appendChild(div);
    },

    // Логіка активації модуля
    activateModule(id, title) {
        this.state.moduleId = id;
        
        // 1. Update Sidebar UI
        document.querySelectorAll('.module-item').forEach(el => {
            el.classList.remove('active');
            if (el.getAttribute('data-id') === id) el.classList.add('active');
        });

        // 2. Update Header Indicator
        const indicator = document.getElementById('module-indicator');
        if (indicator) {
            indicator.innerHTML = `<span class="status-dot online"></span> ${title} <span style="opacity:0.5">[MOUNTED]</span>`;
            indicator.style.color = 'var(--success-color)';
        }

        // 3. System Log in Chat
        this.renderMessage('system', `🔄 Контекст переключено на модуль: <b>${title}</b>`);
        
        this.showToast(`Module mounted: ${title}`);
        this.switchView('chat');
    },

    // --- MESSAGING ---
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
            if (e.name !== 'AbortError') botBubble.innerText = `Помилка зв'язку: ${e.message}`;
        } finally {
            input.disabled = false;
            input.focus();
            this.state.controller = null;
        }
    },

    // --- FILE UPLOAD ---
    async uploadFile(input) {
        if (input.files.length === 0) return;
        if (!this.state.chatId) await this.createNewChat();

        const file = input.files[0];
        this.renderMessage('system', `⏳ Ingesting file: ${file.name}...`);
        
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`${API_BASE}/chats/${this.state.chatId}/upload`, {
                method: 'POST',
                body: formData
            });
            if (!res.ok) throw new Error("Ingest failed");
            const data = await res.json();
            
            const lastMsg = document.querySelector('#chat-history .msg:last-child .msg-bubble');
            lastMsg.innerHTML = `✅ Файл <b>${data.filename}</b> інтегровано в поточний сеанс (${data.chunks} фрагментів).`;
        } catch (e) {
            this.renderMessage('system', `❌ Error: ${e.message}`);
        }
        input.value = '';
    },

    // --- SYSTEM TELEMETRY SIMULATION ---
    initTelemetry() {
        // Simple randomizer to make the UI look "alive"
        setInterval(() => {
            const vramEl = document.querySelectorAll('.tele-val')[2]; // VRAM Row
            if(vramEl) {
                // Fluctuate between 3.1 and 3.4 GB
                const val = (3.1 + Math.random() * 0.3).toFixed(2);
                vramEl.innerText = `${val} GB`;
            }
        }, 3000);
    },

    // --- UI HELPERS ---
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
    },

    // Inspector Utils
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

    activateCurrentPackage() {
        if (this.state.tempModule) {
            this.activateModule(this.state.tempModule.id, this.state.tempModule.title);
            this.closeInspector();
        }
    }
};

document.addEventListener('DOMContentLoaded', () => App.init());
