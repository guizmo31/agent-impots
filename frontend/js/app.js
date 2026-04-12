/**
 * Agent Impôts - Frontend Application
 * Gère les sessions, la connexion WebSocket et l'interface de chat.
 */

const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const statusBadge = document.getElementById('status-badge');
const statusText = document.getElementById('status-text');
const sessionPicker = document.getElementById('session-picker');
const sessionList = document.getElementById('session-list');
const chatContainer = document.getElementById('chat-container');
const inputArea = document.getElementById('input-area');

let ws = null;
let sessionId = null;
let isWaiting = false;

// --- Session Management ---

async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const sessions = await response.json();
        renderSessionList(sessions);
    } catch (e) {
        console.error('Erreur chargement sessions:', e);
        renderSessionList([]);
    }
}

function renderSessionList(sessions) {
    if (sessions.length === 0) {
        sessionList.innerHTML = '<p class="no-sessions">Aucune session sauvegardée.</p>';
        return;
    }

    sessionList.innerHTML = sessions.map(s => {
        const date = s.updated_at ? new Date(s.updated_at).toLocaleDateString('fr-FR', {
            day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : '?';

        const stateLabels = {
            'welcome': 'Non commencée',
            'scan_folder': 'En attente de documents',
            'analyze_docs': 'Analyse en cours',
            'questions': 'Questions en cours',
            'compute': 'Calcul en cours',
            'report': 'Rapport en cours',
            'done': 'Terminée',
        };
        const stateLabel = stateLabels[s.state] || s.state;
        const stateClass = s.state === 'done' ? 'state-done' : s.state === 'questions' ? 'state-progress' : 'state-other';

        return `
            <div class="session-card" data-id="${s.session_id}">
                <div class="session-card-main" onclick="resumeSession('${s.session_id}')">
                    <div class="session-card-title">${escapeHtml(s.name)}</div>
                    <div class="session-card-meta">
                        <span class="session-state ${stateClass}">${stateLabel}</span>
                        <span>${s.documents_count} doc(s)</span>
                        <span>${date}</span>
                    </div>
                </div>
                <button class="session-delete" onclick="event.stopPropagation(); deleteSession('${s.session_id}')" title="Supprimer">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                </button>
            </div>`;
    }).join('');
}

function startNewSession() {
    const nameInput = document.getElementById('new-session-name');
    const name = nameInput.value.trim() || `Déclaration ${new Date().toLocaleDateString('fr-FR')}`;
    sessionId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString();
    showChat();
    connect();
}

function resumeSession(id) {
    sessionId = id;
    showChat();
    connect();
}

async function deleteSession(id) {
    if (!confirm('Supprimer cette session et toutes ses données ?')) return;
    try {
        await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        loadSessions();
    } catch (e) {
        console.error('Erreur suppression:', e);
    }
}

function showChat() {
    sessionPicker.style.display = 'none';
    chatContainer.style.display = 'flex';
    inputArea.style.display = 'block';
}

function showSessionPicker() {
    sessionPicker.style.display = 'flex';
    chatContainer.style.display = 'none';
    inputArea.style.display = 'none';
    loadSessions();
}

// --- WebSocket ---

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${sessionId}`);

    ws.onopen = () => {
        setStatus('connected', 'Connecté (local)');
        enableInput();
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };

    ws.onclose = () => {
        setStatus('error', 'Déconnecté');
        disableInput();
        setTimeout(connect, 3000);
    };

    ws.onerror = () => {
        setStatus('error', 'Erreur de connexion');
    };
}

function setStatus(state, text) {
    statusBadge.className = `status-badge ${state}`;
    statusText.textContent = text;
}

// --- Messages ---

let ingestionInProgress = false;

function handleMessage(data) {
    switch (data.type) {
        case 'progress':
            ingestionInProgress = true;
            updateProgressBar(data);
            return; // Ne pas toucher au typing indicator ni au input
        case 'assistant':
            removeTypingIndicator();
            if (ingestionInProgress) {
                // Pendant l'ingestion, les messages assistant ne suppriment PAS la barre
                // Ils s'affichent au-dessus (liste de fichiers) ou en dessous (resume)
                finalizeProgressBar();
                ingestionInProgress = false;
            }
            isWaiting = false;
            enableInput();
            addAssistantMessage(data.content);
            break;
        case 'status':
            addStatusMessage(data.content);
            break;
        case 'report':
            removeTypingIndicator();
            finalizeProgressBar();
            ingestionInProgress = false;
            isWaiting = false;
            enableInput();
            addReportMessage(data.content, data.report_path);
            break;
        default:
            // Ignorer les messages sans type connu qui n'ont pas de content
            if (!data.content) return;
            removeTypingIndicator();
            isWaiting = false;
            enableInput();
            addAssistantMessage(data.content);
    }
}

function updateProgressBar(data) {
    let container = document.getElementById('progress-container');
    if (!container) {
        // Creer le bloc de progression
        container = document.createElement('div');
        container.id = 'progress-container';
        container.className = 'progress-container';
        container.innerHTML = `
            <div class="progress-header">
                <span class="progress-title">Analyse des documents</span>
                <span class="progress-counter" id="progress-counter">0/0</span>
            </div>
            <div class="progress-bar-track">
                <div class="progress-bar-fill" id="progress-bar-fill"></div>
            </div>
            <div class="progress-current" id="progress-current"></div>
            <div class="progress-log" id="progress-log"></div>
        `;
        chatMessages.appendChild(container);
    }

    const pct = data.percent || 0;
    const current = data.current || 0;
    const total = data.total || 0;
    const filename = data.filename || '';
    const status = data.status || '';
    const detail = data.detail || '';

    // Mettre a jour la barre
    document.getElementById('progress-counter').textContent = `${current}/${total} (${pct}%)`;
    document.getElementById('progress-bar-fill').style.width = `${pct}%`;

    // Document en cours
    if (status === 'processing') {
        document.getElementById('progress-current').innerHTML =
            `<span class="spinner"></span> <strong>${escapeHtml(filename)}</strong>`;
    } else {
        document.getElementById('progress-current').textContent = '';
    }

    // Log des documents traites
    const log = document.getElementById('progress-log');
    const statusIcon = status === 'ok' ? '&#10003;' : status === 'skip' ? '&#8631;' : '&#10007;';
    const statusClass = status === 'ok' ? 'log-ok' : status === 'skip' ? 'log-skip' : 'log-error';

    if (status !== 'processing') {
        const entry = document.createElement('div');
        entry.className = `progress-log-entry ${statusClass}`;
        entry.innerHTML = `<span class="log-icon">${statusIcon}</span> ${escapeHtml(filename)} <span class="log-detail">${escapeHtml(detail)}</span>`;
        log.appendChild(entry);
        // Garder le scroll en bas du log
        log.scrollTop = log.scrollHeight;
    }

    scrollToBottom();
}

function finalizeProgressBar() {
    const container = document.getElementById('progress-container');
    if (container) {
        // Mettre la barre a 100% et marquer comme termine
        const fill = document.getElementById('progress-bar-fill');
        if (fill) fill.style.width = '100%';
        const counter = document.getElementById('progress-counter');
        if (counter && !counter.textContent.includes('Termine')) {
            counter.textContent += ' - Termine !';
        }
        const current = document.getElementById('progress-current');
        if (current) current.textContent = '';
    }
}

function addUserMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message user';
    msg.innerHTML = `
        <div class="message-avatar">U</div>
        <div class="message-bubble">${escapeHtml(text)}</div>
    `;
    chatMessages.appendChild(msg);
    scrollToBottom();
}

function addAssistantMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-bubble">${renderMarkdown(text)}</div>
    `;
    chatMessages.appendChild(msg);
    scrollToBottom();
}

function addStatusMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'status-message';
    msg.innerHTML = `<span class="spinner"></span>${escapeHtml(text)}`;
    chatMessages.appendChild(msg);
    scrollToBottom();
}

function addReportMessage(text, reportPath) {
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-bubble">
            <p>${escapeHtml(text)}</p>
            <a href="/output/${reportPath}" target="_blank" class="report-link">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                </svg>
                Ouvrir le rapport détaillé
            </a>
        </div>
    `;
    chatMessages.appendChild(msg);
    scrollToBottom();
}

function addTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'message assistant';
    indicator.id = 'typing-indicator';
    indicator.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-bubble">
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    chatMessages.appendChild(indicator);
    scrollToBottom();
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
}

// --- Input ---

function sendMessage() {
    const text = userInput.value.trim();
    if (!text || isWaiting || !ws || ws.readyState !== WebSocket.OPEN) return;

    addUserMessage(text);
    ws.send(JSON.stringify({ message: text }));
    userInput.value = '';
    userInput.style.height = 'auto';
    isWaiting = true;
    disableInput();
    addTypingIndicator();
}

function enableInput() {
    if (!isWaiting) {
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.focus();
    }
}

function disableInput() {
    userInput.disabled = true;
    sendBtn.disabled = true;
}

// --- Event listeners ---

sendBtn.addEventListener('click', sendMessage);

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

userInput.addEventListener('input', () => {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
});

document.getElementById('new-session-btn').addEventListener('click', startNewSession);

document.getElementById('new-session-name').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') startNewSession();
});

// --- Utilities ---

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    html = html.replace(/^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)+)/gm, (match, header, separator, body) => {
        const headers = header.split('|').filter(c => c.trim());
        const rows = body.trim().split('\n');
        let table = '<table><thead><tr>';
        headers.forEach(h => { table += `<th>${h.trim()}</th>`; });
        table += '</tr></thead><tbody>';
        rows.forEach(row => {
            const cells = row.split('|').filter(c => c.trim());
            table += '<tr>';
            cells.forEach(c => { table += `<td>${c.trim()}</td>`; });
            table += '</tr>';
        });
        table += '</tbody></table>';
        return table;
    });

    html = html.replace(/^---$/gm, '<hr>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<h[23]>)/g, '$1');
    html = html.replace(/(<\/h[23]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<table>)/g, '$1');
    html = html.replace(/(<\/table>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');
    html = html.replace(/<p>(<hr>)<\/p>/g, '$1');

    return html;
}

// --- Start ---
showSessionPicker();
