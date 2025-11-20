const API_BASE = "/api/v1";
let currentModuleId = null;

document.addEventListener('DOMContentLoaded', () => {
    loadModules();
    
    // Відправка по Enter
    document.getElementById('question-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendQuery();
        }
    });
});

// 1. Завантаження списку модулів
async function loadModules() {
    const listElement = document.getElementById('module-list');
    try {
        const response = await fetch(`${API_BASE}/modules`);
        if (!response.ok) throw new Error('Помилка мережі');
        
        const modules = await response.json();
        listElement.innerHTML = ''; // Очистити "Завантаження..."

        if (modules.length === 0) {
            listElement.innerHTML = '<p class="loading-text" style="color:red;">Модулі не знайдено. Запустіть "ark build".</p>';
            return;
        }

        modules.forEach(module => {
            const item = document.createElement('div');
            item.className = 'module-item';
            // Форматуємо назву красиво
            item.innerHTML = `<strong>${module.title}</strong><br><small>v${module.version}</small>`;
            item.dataset.id = module.id;
            item.onclick = () => selectModule(module.id, item, module.title);
            listElement.appendChild(item);
        });

        // Автовибір першого модуля
        if (modules.length > 0) {
            const firstItem = listElement.querySelector('.module-item');
            selectModule(modules[0].id, firstItem, modules[0].title);
        }

    } catch (error) {
        listElement.innerHTML = `<p class="loading-text" style="color:red;">Помилка з'єднання: ${error.message}</p>`;
    }
}

// 2. Вибір модуля
function selectModule(moduleId, element, title) {
    if (currentModuleId === moduleId) return;

    // UI оновлення
    document.querySelectorAll('.module-item').forEach(el => el.classList.remove('active'));
    element.classList.add('active');

    currentModuleId = moduleId;
    addMessage('system', `Модуль "<b>${title}</b>" активовано. Я готовий відповідати на питання по цьому документу.`);
}

// 3. Відправка запиту
async function sendQuery() {
    const inputElement = document.getElementById('question-input');
    const sendBtn = document.getElementById('send-btn');
    const query = inputElement.value.trim();

    if (!query) return;
    if (!currentModuleId) {
        alert("Спочатку оберіть модуль!");
        return;
    }

    // UI: Блокуємо ввід
    inputElement.value = '';
    inputElement.disabled = true;
    sendBtn.disabled = true;
    document.getElementById('citation-panel').classList.add('hidden'); // Ховаємо старі цитати

    // Додаємо питання користувача
    addMessage('user', query);

    // Додаємо "думаю..."
    const loadingMsgId = addMessage('system', 'Thinking... ⏳');

    try {
        const response = await fetch(`${API_BASE}/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, module_id: currentModuleId })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        // Видаляємо "Thinking..."
        document.getElementById(loadingMsgId).remove();

        // Показуємо відповідь
        addMessage('system', data.answer);

        // Показуємо джерела
        if (data.sources && data.sources.length > 0) {
            showCitations(data.sources);
        }

    } catch (error) {
        document.getElementById(loadingMsgId).remove();
        addMessage('system', `❌ Помилка: ${error.message}. Перевірте сервер.`);
    } finally {
        // Розблокуємо UI
        inputElement.disabled = false;
        sendBtn.disabled = false;
        inputElement.focus();
    }
}

// Допоміжні функції
function addMessage(type, text) {
    const chatWindow = document.getElementById('chat-window');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${type}-message`;
    msgDiv.id = 'msg-' + Date.now();
    
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = type === 'user' ? '👤' : '🤖';

    const content = document.createElement('div');
    content.className = 'content';
    content.innerHTML = text; // Дозволяємо HTML для форматування

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(content);
    chatWindow.appendChild(msgDiv);
    
    // Автоскрол вниз
    chatWindow.scrollTop = chatWindow.scrollHeight;
    
    return msgDiv.id;
}

function showCitations(sources) {
    const panel = document.getElementById('citation-panel');
    const content = document.getElementById('citation-content');
    content.innerHTML = '';

    sources.forEach(source => {
        const div = document.createElement('div');
        div.className = 'citation-item';
        div.innerHTML = `
            <div class="citation-score">Релевантність: ${(source.score * 100).toFixed(1)}%</div>
            <div>${source.chunk}</div>
        `;
        content.appendChild(div);
    });

    panel.classList.remove('hidden');
}
