var API_BASE = '';

var md = null;
function renderMarkdown(text) {
    if (!text) return '';
    if (!md && window.markdownit) {
        md = window.markdownit({html: false, linkify: true, breaks: true});
    }
    if (md) return md.render(text);
    var lines = text.split(/\r?\n/);
    var html = '';
    var para = [];
    function flushPara() {
        if (para.length) {
            html += '<p>' + escapeHtml(para.join(' ')) + '</p>';
            para = [];
        }
    }
    lines.forEach(function(line) {
        var heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            flushPara();
            var level = heading[1].length;
            html += '<h' + level + '>' + escapeHtml(heading[2]) + '</h' + level + '>';
        } else if (!line.trim()) {
            flushPara();
        } else {
            para.push(line.trim());
        }
    });
    flushPara();
    return html || escapeHtml(text);
}

function toggleTheme() {
    var html = document.documentElement;
    var current = html.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    var btn = document.querySelector('.topbar-btn[onclick*="toggleTheme"]');
    if (btn) {
        if (next === 'dark') {
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
        } else {
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>';
        }
    }
}

(function() {
    var saved = localStorage.getItem('theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
        saved = 'dark';
    }
    document.addEventListener('DOMContentLoaded', function() {
        var btn = document.querySelector('.topbar-btn[onclick*="toggleTheme"]');
        if (btn && saved === 'dark') {
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
        }
    });
})();

var viewNames = {
    workspace: '教材工作台',
    outline: '大纲编辑器',
    chapters: '章节管理',
    preview: '文档生成与下载',
    chat: 'AI 对话',
    settings: '系统设置',
    skills: '技能管理',
    'textbook-detail': '教材详情',
    knowledge: '知识库管理'
};

var currentBookId = null;
var currentBookData = null;
var textbooks = [];
var chatSessionId = 'textbook_' + Date.now();
var selectedTemplate = 'academic';
var pendingAttachments = [];
var chatSending = false;
var currentEventSource = null;
var currentPipelineSource = null;
var currentPipelinePollTimer = null;
var chatHistoryLoaded = false;
var activeChatRequestId = null;

function navigateToChat(prefill) {
    switchView('chat');
    if (prefill) {
        var input = document.getElementById('chatInput');
        if (input) {
            input.value = prefill;
            input.focus();
            input.scrollTop = input.scrollHeight;
        }
    }
}

function setChatSending(sending) {
    chatSending = sending;
    var sendBtn = document.querySelector('.chat-send-btn');
    if (sendBtn) {
        if (sending) {
            sendBtn.classList.add('sending');
            sendBtn.title = '点击暂停';
            sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
            sendBtn.onclick = function() { stopCurrentChat(); };
        } else {
            sendBtn.classList.remove('sending');
            sendBtn.title = '';
            sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
            sendBtn.onclick = function() { sendChatMessage(); };
        }
    }
    var modalSendBtn = document.querySelector('#chatModal .btn-primary');
    if (modalSendBtn) {
        if (sending) {
            modalSendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> 暂停';
            modalSendBtn.onclick = function() { stopCurrentChat(); };
        } else {
            modalSendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 发送';
            modalSendBtn.onclick = function() { sendChatModalMessage(); };
        }
    }
}

function stopCurrentChat() {
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }
    activeChatRequestId = null;
    setChatSending(false);
    fetch(API_BASE + '/api/chat/cancel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: chatSessionId})
    }).catch(function() {});
    showToast('对话已暂停');
}

var EMOJIS = ['📖','🐍','🌳','🤖','💡','🔬','📊','🎯','🧮','📐','🌍','🎨'];

function switchView(viewId) {
    document.querySelectorAll('.view-page').forEach(function(p) { p.classList.remove('active'); });
    document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
    var page = document.getElementById('view-' + viewId);
    if (page) page.classList.add('active');
    var navItem = document.querySelector('.nav-item[data-view="' + viewId + '"]');
    if (navItem) navItem.classList.add('active');
    document.getElementById('breadcrumb-current').textContent = viewNames[viewId] || viewId;

    if (viewId === 'outline' && currentBookId) {
        loadOutline(currentBookId);
    } else if (viewId === 'chapters' && currentBookId) {
        loadChapters(currentBookId);
    } else if (viewId === 'preview' && currentBookId) {
        loadExportChapters(currentBookId);
    } else if (viewId === 'skills') {
        loadSkills();
    } else if (viewId === 'textbook-detail') {
        loadTextbookDetail();
    } else if (viewId === 'settings') {
        loadSettings();
    } else if (viewId === 'knowledge') {
        loadKnowledgePage();
    } else if (viewId === 'chat') {
        if (chatModalSessionId) chatSessionId = chatModalSessionId;
        if (!currentEventSource && !chatHistoryLoaded) {
            loadChatHistory();
        }
    }
}

function showCreateModal() {
    document.getElementById('createModal').style.display = 'flex';
}

function hideCreateModal() {
    document.getElementById('createModal').style.display = 'none';
}

async function loadTextbooks() {
    try {
        var response = await fetch(API_BASE + '/api/textbook');
        var data = await response.json();
        if (data.status === 'success') {
            textbooks = data.textbooks || [];
            renderTextbookGrid(textbooks);
        }
    } catch (e) {
        console.error('Failed to load textbooks:', e);
        document.getElementById('textbookGrid').innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted-fg);">加载教材列表失败，请刷新重试</div>';
    }
}

function renderTextbookGrid(books) {
    var grid = document.getElementById('textbookGrid');
    if (!books || books.length === 0) {
        grid.innerHTML = '<div style="text-align:center;padding:60px 20px;color:var(--muted-fg);grid-column:1/-1;"><div style="font-size:48px;margin-bottom:12px;">📚</div><div style="font-size:15px;font-weight:600;margin-bottom:4px;">暂无教材</div><div style="font-size:13px;">点击"新建教材"开始创建</div></div>';
        return;
    }

    var html = '';
    for (var i = 0; i < books.length; i++) {
        var book = books[i];
        var emoji = EMOJIS[i % EMOJIS.length];
        var progress = book.progress || 0;
        var completedChapters = book.completed_chapters || 0;
        var totalChapters = book.total_chapters || 0;
        var statusClass = 'status-writing';
        var statusText = '编写中';
        if (progress >= 100) { statusClass = 'status-completed'; statusText = '已完成'; }
        else if (book.status === 'reviewing') { statusClass = 'status-reviewing'; statusText = '审查中'; }
        else if (book.status === 'idle' || !book.status) { statusClass = 'status-writing'; statusText = '待开始'; }

        var accentGradient = 'linear-gradient(90deg, var(--secondary), var(--accent))';
        if (progress >= 100) accentGradient = 'linear-gradient(90deg, var(--accent), var(--accent-light))';

        html += '<div class="textbook-card" onclick="selectTextbook(\'' + book.id + '\')">';
        html += '<div class="card-accent" style="background:' + accentGradient + '"></div>';
        html += '<div class="card-icon" style="background:rgba(37,99,235,0.1);color:var(--secondary);">' + emoji + '</div>';
        html += '<div class="card-title">' + escapeHtml(book.title || '未命名教材') + '</div>';
        html += '<div class="card-subtitle">' + escapeHtml((book.target_audience || '通用') + ' · ' + totalChapters + '章 · ' + (book.style || '学术风格')) + '</div>';
        html += '<div class="card-progress">';
        html += '<div class="card-progress-track"><div class="card-progress-fill" style="width:' + progress + '%;background:' + accentGradient + '"></div></div>';
        html += '<div class="card-progress-label"><span>' + completedChapters + '/' + totalChapters + ' 章完成</span><span>' + progress + '%</span></div>';
        html += '</div>';
        html += '<div class="card-meta"><span class="card-status ' + statusClass + '">' + statusText + '</span>';
        html += '<span>' + (book.chapter_word_count || '5,000') + ' 字/章</span>';
        html += '<button class="pipeline-btn" style="padding:2px 8px;font-size:10px;margin-left:auto;color:var(--destructive);border-color:rgba(220,38,38,0.2);" onclick="event.stopPropagation();deleteTextbook(\'' + book.id + '\')">删除</button>';
        html += '</div></div>';
    }
    grid.innerHTML = html;
}

function selectTextbook(bookId) {
    currentBookId = bookId;
    for (var i = 0; i < textbooks.length; i++) {
        if (textbooks[i].id === bookId) {
            currentBookData = textbooks[i];
            break;
        }
    }
    var chapterBadge = document.getElementById('chapterBadge');
    if (chapterBadge) chapterBadge.textContent = currentBookData ? (currentBookData.total_chapters || 0) : '0';
    var exportFilename = document.getElementById('exportFilename');
    if (exportFilename) exportFilename.value = currentBookData ? (currentBookData.title || '') : '';
    currentBookId = bookId;
    switchView('textbook-detail');
}

async function createTextbook() {
    var name = document.getElementById('createName').value.trim();
    if (!name) { alert('请输入教材名称'); return; }

    var config = {
        title: name,
        subject: document.getElementById('createSubject').value.trim() || '',
        target_audience: document.getElementById('createAudience').value.trim() || '通用',
        level: document.getElementById('createLevel').value.trim() || '',
        total_chapters: parseInt(document.getElementById('createChapterCount').value) || 12,
        style: document.getElementById('createStyle').value || 'academic',
        chapter_word_count: parseInt(document.getElementById('createWordCount').value) || 5000,
        notes: document.getElementById('createNotes').value.trim()
    };

    try {
        var response = await fetch(API_BASE + '/api/textbook', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        var data = await response.json();
        if (data.status === 'success') {
            hideCreateModal();
            document.getElementById('createName').value = '';
            document.getElementById('createAudience').value = '';
            document.getElementById('createNotes').value = '';
            await loadTextbooks();
        } else {
            alert('创建失败: ' + (data.message || '未知错误'));
        }
    } catch (e) {
        alert('创建失败: ' + e.message);
    }
}

async function deleteTextbook(bookId) {
    if (!confirm('确定要删除这本教材吗？此操作不可撤销。')) return;

    try {
        var response = await fetch(API_BASE + '/api/textbook/' + bookId, {
            method: 'DELETE'
        });
        var data = await response.json();
        if (data.status === 'success') {
            if (currentBookId === bookId) {
                currentBookId = null;
                currentBookData = null;
            }
            await loadTextbooks();
        } else {
            alert('删除失败: ' + (data.message || '未知错误'));
        }
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

async function loadOutline(bookId) {
    try {
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/outline');
        var data = await response.json();
        if (data.status === 'success') {
            renderOutlineTree(data.outline);
        }
    } catch (e) {
        console.error('Failed to load outline:', e);
    }
}

function renderOutlineTree(outline) {
    var panel = document.getElementById('outlineTreePanel');
    if (!outline) {
        panel.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--muted-fg);font-size:13px;">大纲尚未生成，请先启动编制管线</div>';
        return;
    }

    var outlineObj = outline;
    if (typeof outline === 'string') {
        try { outlineObj = JSON.parse(outline); } catch(e) { outlineObj = null; }
    }

    if (!outlineObj || (!outlineObj.children && !outlineObj.chapters)) {
        panel.innerHTML = '<div style="white-space:pre-wrap;font-size:13px;line-height:1.8;">' + escapeHtml(typeof outline === 'string' ? outline : JSON.stringify(outline, null, 2)) + '</div>';
        return;
    }

    var html = '<div class="outline-node">';
    html += '<div class="outline-node-content" style="font-weight:700;font-size:14px;">';
    html += '<div class="toggle"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg></div>';
    html += '<div class="node-icon" style="background:rgba(37,99,235,0.1);color:var(--secondary);">📘</div>';
    html += escapeHtml(outlineObj.title || currentBookData.title || '教材大纲');
    html += '</div>';

    var items = outlineObj.children || outlineObj.chapters || [];
    html += '<div class="outline-children">';
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var numStr = item.number || item.chapter_num || (i + 1);
        var title = item.title || item.name || ('章节 ' + numStr);
        var children = item.children || item.sections || [];

        html += '<div class="outline-node">';
        html += '<div class="outline-node-content" onclick="selectOutlineNode(' + i + ')">';
        if (children.length > 0) {
            html += '<div class="toggle"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg></div>';
        } else {
            html += '<div class="toggle" style="visibility:hidden"></div>';
        }
        html += '<div class="node-icon" style="background:rgba(139,92,246,0.1);color:var(--phase-outline);">' + numStr + '</div>';
        html += escapeHtml(title);
        html += '</div>';

        if (children.length > 0) {
            html += '<div class="outline-children">';
            for (var j = 0; j < children.length; j++) {
                var child = children[j];
                var childTitle = child.title || child.name || ('小节 ' + (j + 1));
                html += '<div class="outline-node">';
                html += '<div class="outline-node-content" onclick="selectOutlineNode(' + i + ',' + j + ')">';
                html += '<div class="toggle" style="visibility:hidden"></div>';
                html += '<div class="node-icon" style="background:rgba(5,150,105,0.1);color:var(--accent);">' + (j + 1) + '</div>';
                html += escapeHtml(childTitle);
                html += '</div></div>';
            }
            html += '</div>';
        }
        html += '</div>';
    }
    html += '</div></div>';

    panel.innerHTML = html;
}

function selectOutlineNode(chapterIdx, sectionIdx) {
    var detailPanel = document.getElementById('outlineDetailPanel');
    detailPanel.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--muted-fg);font-size:13px;">章节详情加载中...</div>';

    if (currentBookId) {
        loadChapter(currentBookId, chapterIdx + 1).then(function(content) {
            detailPanel.innerHTML = '<h3 style="font-size:16px;font-weight:700;margin-bottom:16px;">第' + (chapterIdx + 1) + '章</h3>' +
                '<div class="detail-section"><div class="detail-label">章节内容</div><div class="detail-value" style="white-space:pre-wrap;max-height:400px;overflow-y:auto;">' +
                escapeHtml(content || '暂无内容') + '</div></div>' +
                '<div class="outline-actions">' +
                '<button class="btn-primary" style="flex:1;justify-content:center;font-size:12px;padding:8px;" onclick="startPipelineForChapter(' + (chapterIdx + 1) + ')">编写本章</button>' +
                '</div>';
        });
    }
}

async function saveOutline(bookId, content) {
    try {
        await fetch(API_BASE + '/api/textbook/' + bookId + '/outline', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({outline_content: content})
        });
    } catch (e) {
        console.error('Failed to save outline:', e);
    }
}

async function loadChapters(bookId) {
    try {
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/chapters');
        var data = await response.json();
        if (data.status === 'success') {
            renderChapterTable(data.chapters || []);
        }
    } catch (e) {
        console.error('Failed to load chapters:', e);
    }
}

function renderChapterTable(chapters) {
    var tbody = document.getElementById('chapterTableBody');
    if (!chapters || chapters.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted-fg);">暂无章节数据，请先生成大纲</td></tr>';
        return;
    }

    var html = '';
    for (var i = 0; i < chapters.length; i++) {
        var ch = chapters[i];
        var num = ch.chapter_num || ch.number || (i + 1);
        var title = ch.title || ch.name || ('第' + num + '章');
        var wordCount = ch.word_count || ch.words || 0;
        var status = ch.status || 'pending';
        var score = ch.score || null;

        var statusBadge = '';
        var rowStyle = '';
        if (status === 'completed' || status === 'done') {
            statusBadge = '<span class="chapter-status-badge status-completed">✓ 完成</span>';
        } else if (status === 'writing' || status === 'in_progress') {
            statusBadge = '<span class="chapter-status-badge status-writing">⟳ 编写中</span>';
            rowStyle = ' style="background:rgba(37,99,235,0.03)"';
        } else if (status === 'reviewing') {
            statusBadge = '<span class="chapter-status-badge status-reviewing">⟳ 审查中</span>';
        } else {
            statusBadge = '<span class="chapter-status-badge" style="background:var(--muted);color:var(--muted-fg)">待编写</span>';
        }

        var scoreHtml = score ? '<span style="color:var(--accent);font-weight:700">' + score + '</span>' : '<span style="color:var(--muted-fg)">—</span>';
        var wordCountHtml = wordCount > 0 ? wordCount.toLocaleString() : '<span style="color:var(--muted-fg)">—</span>';

        html += '<tr' + rowStyle + '>';
        html += '<td style="font-weight:600;font-family:var(--font-mono)">Ch.' + String(num).padStart(2, '0') + '</td>';
        html += '<td>' + escapeHtml(title) + '</td>';
        html += '<td>' + wordCountHtml + '</td>';
        html += '<td>' + statusBadge + '</td>';
        html += '<td>' + scoreHtml + '</td>';
        html += '<td><button class="pipeline-btn" style="padding:4px 10px;font-size:11px;" onclick="viewChapter(' + num + ')">查看</button></td>';
        html += '</tr>';
    }
    tbody.innerHTML = html;

    document.getElementById('chapterBadge').textContent = chapters.length;
    if (currentBookData) {
        document.getElementById('chaptersTitle').textContent = '章节管理 — ' + (currentBookData.title || '');
    }
}

async function loadChapter(bookId, chapterNum) {
    try {
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/chapters/' + chapterNum);
        var data = await response.json();
        if (data.status === 'success') {
            return data.content || '';
        }
    } catch (e) {
        console.error('Failed to load chapter:', e);
    }
    return '';
}

function viewChapter(chapterNum) {
    if (!currentBookId) return;
    loadChapter(currentBookId, chapterNum).then(function(content) {
        alert('第' + chapterNum + '章内容:\n\n' + (content || '暂无内容').substring(0, 500) + (content && content.length > 500 ? '...' : ''));
    });
}

async function updateChapter(bookId, chapterNum, content) {
    try {
        await fetch(API_BASE + '/api/textbook/' + bookId + '/chapters/' + chapterNum, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content: content})
        });
    } catch (e) {
        console.error('Failed to update chapter:', e);
    }
}

async function startPipeline(bookId) {
    try {
        showToast('Pipeline started. You can keep using the page while it runs.');
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/pipeline', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        var data = await response.json();
        if (data.status === 'success') {
            currentBookId = bookId;
            beginPipelineMonitor(bookId);
        } else {
            alert('启动管线失败: ' + (data.message || '未知错误'));
        }
    } catch (e) {
        alert('启动管线失败: ' + e.message);
    }
}

function beginPipelineMonitor(bookId) {
    if (!bookId) return;
    if (currentPipelineSource) {
        currentPipelineSource.close();
        currentPipelineSource = null;
    }
    if (currentPipelinePollTimer) {
        clearInterval(currentPipelinePollTimer);
        currentPipelinePollTimer = null;
    }
    var source = new EventSource(API_BASE + '/api/textbook/' + bookId + '/pipeline/stream');
    currentPipelineSource = source;
    source.onmessage = function(event) {
        try {
            var d = JSON.parse(event.data);
            handlePipelineEvent(d, bookId);
            if (d.type === 'pipeline_complete' || d.type === 'pipeline_error') {
                source.close();
                currentPipelineSource = null;
                refreshBookDetail();
                loadTextbooks();
            }
        } catch (e) {}
    };
    source.onerror = function() {
        if (currentPipelineSource) {
            currentPipelineSource.close();
            currentPipelineSource = null;
        }
        currentPipelinePollTimer = setInterval(function() {
            fetch(API_BASE + '/api/textbook/' + bookId + '/pipeline')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.status === 'success') {
                        handlePipelineEvent({type: 'pipeline_status', data: data.pipeline}, bookId);
                        var st = data.pipeline && data.pipeline.status;
                        if (st === 'completed' || st === 'error' || st === 'cancelled' || st === 'none') {
                            clearInterval(currentPipelinePollTimer);
                            currentPipelinePollTimer = null;
                            refreshBookDetail();
                            loadTextbooks();
                        }
                    }
                }).catch(function() {});
        }, 2000);
    };
}

function handlePipelineEvent(d, bookId) {
    var data = d.data || {};
    var status = data.status || d.type;
    var progress = data.progress;
    if (typeof progress === 'number') progress = Math.round(progress * 100);
    var phase = data.current_phase || data.phase || '';
    var message = '';
    if (d.type === 'pipeline_status') {
        message = 'Pipeline: ' + status + (phase ? ' / ' + phase : '') + (typeof progress === 'number' ? ' / ' + progress + '%' : '');
    } else if (d.type === 'phase_start') {
        message = 'Pipeline phase started: ' + ((data.phase_label || data.phase) || '');
    } else if (d.type === 'phase_progress') {
        message = 'Pipeline progress: ' + ((data.item_label || data.phase) || '');
    } else if (d.type === 'phase_complete') {
        message = 'Pipeline phase completed: ' + ((data.phase_label || data.phase) || '');
    } else if (d.type === 'pipeline_complete') {
        message = 'Pipeline completed';
    } else if (d.type === 'pipeline_error') {
        message = 'Pipeline failed: ' + (data.error || 'unknown error');
    }
    var meta = document.getElementById('detailBookMeta');
    if (meta && message && currentBookId === bookId) {
        meta.textContent = message;
    }
}

function startPipelineForCurrentBook() {
    if (!currentBookId) { alert('请先选择一本教材'); return; }
    startPipeline(currentBookId);
}

function startPipelineForChapter(chapterNum) {
    if (!currentBookId) { alert('请先选择一本教材'); return; }
    startPipeline(currentBookId);
}

async function loadExportChapters(bookId) {
    try {
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/chapters');
        var data = await response.json();
        if (data.status === 'success') {
            renderChapterCheckList(data.chapters || []);
        }
    } catch (e) {
        console.error('Failed to load export chapters:', e);
    }
}

function renderChapterCheckList(chapters) {
    var checkList = document.getElementById('chapterCheckList');
    if (!chapters || chapters.length === 0) {
        checkList.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:var(--muted-fg);font-size:12px;">暂无章节</div>';
        updateChapterCount();
        return;
    }

    var html = '';
    for (var i = 0; i < chapters.length; i++) {
        var ch = chapters[i];
        var num = ch.chapter_num || ch.number || (i + 1);
        var title = ch.title || ch.name || ('第' + num + '章');
        var status = ch.status || 'pending';

        var statusClass = 'pending';
        var statusIcon = '—';
        if (status === 'completed' || status === 'done') { statusClass = 'done'; statusIcon = '✓'; }
        else if (status === 'writing' || status === 'in_progress') { statusClass = 'writing'; statusIcon = '⟳'; }

        var checked = (status === 'completed' || status === 'done') ? 'checked' : '';

        html += '<label class="chapter-check"><input type="checkbox" ' + checked + ' data-ch="' + num + '"><span>第' + num + '章 ' + escapeHtml(title) + '</span><span class="ch-status ' + statusClass + '">' + statusIcon + '</span></label>';
    }
    checkList.innerHTML = html;
    updateChapterCount();
}

function selectTemplate(el, name) {
    document.querySelectorAll('.template-card').forEach(function(c) { c.classList.remove('selected'); });
    el.classList.add('selected');
    selectedTemplate = name;
}

function updateChapterCount() {
    var checks = document.querySelectorAll('#chapterCheckList input[type="checkbox"]');
    var checked = document.querySelectorAll('#chapterCheckList input[type="checkbox"]:checked');
    var el = document.getElementById('chapterSelectCount');
    if (el) el.textContent = '已选 ' + checked.length + '/' + checks.length + ' 章';
}

function toggleAllChapters(state) {
    document.querySelectorAll('#chapterCheckList input[type="checkbox"]').forEach(function(cb) { cb.checked = state; });
    updateChapterCount();
}

function selectCompletedChapters() {
    document.querySelectorAll('#chapterCheckList input[type="checkbox"]').forEach(function(cb) {
        var status = cb.closest('.chapter-check').querySelector('.ch-status');
        cb.checked = status && status.classList.contains('done');
    });
    updateChapterCount();
}

async function exportWord(bookId, template, chapters) {
    try {
        var chaptersParam = chapters.join(',');
        var response = await fetch(API_BASE + '/api/textbook/' + bookId + '/export?template=' + template + '&chapters=' + chaptersParam);
        var data = await response.json();
        return data;
    } catch (e) {
        console.error('Failed to export word:', e);
        return {status: 'error', message: e.message};
    }
}

function generateWord() {
    if (!currentBookId) { alert('请先选择一本教材'); return; }

    var checked = document.querySelectorAll('#chapterCheckList input[type="checkbox"]:checked');
    if (checked.length === 0) { alert('请至少选择一个章节'); return; }

    var chapters = [];
    checked.forEach(function(cb) { chapters.push(cb.getAttribute('data-ch')); });

    var format = document.getElementById('exportFormat').value;
    var filename = document.getElementById('exportFilename').value || '教材';
    var ext = format === 'pdf' ? '.pdf' : '.docx';
    var statusContent = document.getElementById('generateStatusContent');

    statusContent.innerHTML =
        '<div style="margin-bottom:8px;font-size:13px;font-weight:600;">正在生成文档...</div>' +
        '<div class="gen-progress-track"><div class="gen-progress-fill" id="genProgressFill"></div></div>' +
        '<div style="font-size:11px;color:var(--muted-fg);margin-bottom:12px;" id="genProgressLabel">0%</div>' +
        '<div id="genSteps">' +
        '<div class="gen-step"><div class="gen-dot active"></div><span>读取章节内容...</span></div>' +
        '<div class="gen-step"><div class="gen-dot pending"></div><span>应用格式模板...</span></div>' +
        '<div class="gen-step"><div class="gen-dot pending"></div><span>插入图表与代码块...</span></div>' +
        '<div class="gen-step"><div class="gen-dot pending"></div><span>生成目录与页眉页脚...</span></div>' +
        '<div class="gen-step"><div class="gen-dot pending"></div><span>渲染 Word 文档...</span></div>' +
        '</div>';

    var steps = statusContent.querySelectorAll('.gen-step');
    var fill = document.getElementById('genProgressFill');
    var label = document.getElementById('genProgressLabel');
    var stepIndex = 0;
    var pct = 0;

    var stepInterval = setInterval(function() {
        if (stepIndex < steps.length) {
            if (stepIndex > 0) {
                steps[stepIndex - 1].querySelector('.gen-dot').className = 'gen-dot done';
            }
            steps[stepIndex].querySelector('.gen-dot').className = 'gen-dot active';
            stepIndex++;
            pct = Math.round((stepIndex / steps.length) * 80);
            fill.style.width = pct + '%';
            label.textContent = pct + '%';
        }
    }, 600);

    exportWord(currentBookId, selectedTemplate, chapters).then(function(data) {
        clearInterval(stepInterval);

        steps.forEach(function(s) { s.querySelector('.gen-dot').className = 'gen-dot done'; });
        fill.style.width = '100%';
        label.textContent = '100%';

        if (data.status === 'success' && data.file_url) {
            statusContent.innerHTML =
                '<div style="text-align:center;padding:8px 0;">' +
                '<div style="font-size:36px;margin-bottom:8px;">✅</div>' +
                '<div style="font-size:14px;font-weight:700;margin-bottom:4px;">文档生成完成</div>' +
                '<div style="font-size:12px;color:var(--muted-fg);margin-bottom:4px;">' + escapeHtml(filename) + ext + '</div>' +
                '<div style="font-size:11px;color:var(--muted-fg);margin-bottom:12px;">包含 ' + chapters.length + ' 个章节 · ' + (format === 'pdf' ? 'PDF' : 'Word') + ' 格式</div>' +
                '<button class="gen-download-btn" onclick="downloadFile(\'' + data.file_url + '\')">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
                '下载 ' + escapeHtml(filename) + ext + '</button>' +
                '<button class="pipeline-btn" style="width:100%;justify-content:center;margin-top:8px;" onclick="generateWord()">重新生成</button>' +
                '</div>';
        } else {
            statusContent.innerHTML =
                '<div style="text-align:center;padding:8px 0;">' +
                '<div style="font-size:36px;margin-bottom:8px;">❌</div>' +
                '<div style="font-size:14px;font-weight:700;margin-bottom:4px;">生成失败</div>' +
                '<div style="font-size:12px;color:var(--muted-fg);margin-bottom:12px;">' + escapeHtml(data.message || '未知错误') + '</div>' +
                '<button class="pipeline-btn" style="width:100%;justify-content:center;" onclick="generateWord()">重试</button>' +
                '</div>';
        }
    });
}

function downloadFile(url) {
    var a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function sendChatMessage() {
    var input = document.getElementById('chatInput');
    var message = input.value.trim();
    if (!message) return;

    var attachmentsToSend = pendingAttachments.slice();
    input.value = '';

    appendChatMessage('user', message);
    saveChatMessage(chatSessionId, 'user', message);

    setChatSending(true);

    try {
        var body = {
            session_id: chatSessionId,
            message: message,
            stream: true
        };
        if (currentBookId) {
            body.book_id = currentBookId;
        }
        if (attachmentsToSend.length > 0) {
            body.attachments = attachmentsToSend.map(function(a) {
                return {
                    file_path: a.file_path,
                    file_name: a.file_name,
                    file_type: a.file_type
                };
            });
        }
        pendingAttachments = [];
        renderAttachmentPreview();
        var response = await fetch(API_BASE + '/message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        var data = await response.json();
        if (data.status === 'success' && data.stream) {
            startChatSSE(data.request_id, null, null, message);
        } else if (data.status === 'success') {
            pollChatResponse(chatSessionId);
        } else {
            appendChatMessage('assistant', '发送失败: ' + (data.message || '未知错误'));
            setChatSending(false);
        }
    } catch (e) {
        appendChatMessage('assistant', '发送失败: ' + e.message);
        setChatSending(false);
    }
}

function startChatSSE(requestId, externalAssistantEl, externalBubbleEl, userMessage) {
    var assistantEl = externalAssistantEl || null;
    var bubbleEl = externalBubbleEl || null;
    if (!assistantEl) {
        assistantEl = appendChatMessage('assistant', '');
        bubbleEl = assistantEl.querySelector('.chat-bubble');
    }
    var accumulatedText = '';
    var plainTextBuffer = '';
    var toolCallsHtml = '';
    var statusItems = {};
    var reasoningHtml = '';
    var frozenHtml = '';
    var hadToolCallsBeforeText = false;

    var eventSource = new EventSource(API_BASE + '/stream?request_id=' + requestId);
    currentEventSource = eventSource;
    activeChatRequestId = requestId;

    function chapterWorkLabel(text) {
        var msg = text || '';
        var m = msg.match(/第\s*([一二三四五六七八九十百千\d]+)\s*章/);
        if (m) return '第' + m[1] + '章正在编写';
        if (/编写|写作|生成|撰写/.test(msg)) return '智能体正在处理写作任务';
        return '智能体正在工作';
    }

    function upsertStatusItem(key, name, status, detail, state) {
        state = state || 'running';
        var marker = 'data-status-key="' + escapeHtml(key) + '"';
        var html = '<div class="tool-call-item ' + state + ' live-status" ' + marker + '>';
        html += '<div class="tool-call-header"><span class="tool-call-icon">' + (state === 'completed' ? '✓' : '…') + '</span>';
        html += '<span class="tool-call-name">' + escapeHtml(name) + '</span>';
        html += '<span class="tool-call-status' + (state === 'completed' ? ' done' : '') + '">' + escapeHtml(status) + '</span></div>';
        if (detail) html += '<div class="tool-call-args">' + escapeHtml(detail) + '</div>';
        html += '</div>';
        statusItems[key] = html;
        flushOutput();
    }

    upsertStatusItem('agent-working', chapterWorkLabel(userMessage), '进行中', '等待模型输出或工具事件...', 'running');

    function replaceLast(haystack, needle, replacement) {
        var idx = haystack.lastIndexOf(needle);
        if (idx < 0) return haystack;
        return haystack.slice(0, idx) + replacement + haystack.slice(idx + needle.length);
    }

    function replaceLastTag(haystack, startToken, endToken, replacement) {
        var idx = haystack.lastIndexOf(startToken);
        if (idx < 0) return haystack;
        var endIdx = haystack.indexOf(endToken, idx);
        if (endIdx < 0) return haystack;
        return haystack.slice(0, idx) + replacement + haystack.slice(endIdx + endToken.length);
    }

    function flushOutput() {
        var html = frozenHtml;
        if (reasoningHtml) {
            html += '<div class="agent-reasoning">' + reasoningHtml + '</div>';
        }
        if (accumulatedText) {
            var rendered = renderMarkdown(accumulatedText);
            html += rendered || ('<p>' + escapeHtml(accumulatedText) + '</p>');
        }
        var statusHtml = Object.keys(statusItems).map(function(k) { return statusItems[k]; }).join('');
        if (statusHtml || toolCallsHtml) {
            html += '<div class="agent-tool-calls">' + statusHtml + toolCallsHtml + '</div>';
        }
        if (html) {
            bubbleEl.innerHTML = html;
        }
        var messages = document.getElementById('chatMessages');
        if (messages) messages.scrollTop = messages.scrollHeight;
    }

    function freezeCurrentOutput() {
        var chunk = '';
        if (reasoningHtml) {
            chunk += '<div class="agent-reasoning">' + reasoningHtml + '</div>';
        }
        if (accumulatedText) {
            var rendered = renderMarkdown(accumulatedText);
            chunk += rendered || ('<p>' + escapeHtml(accumulatedText) + '</p>');
        }
        var statusHtml = Object.keys(statusItems).map(function(k) { return statusItems[k]; }).join('');
        if (statusHtml || toolCallsHtml) {
            chunk += '<div class="agent-tool-calls">' + statusHtml + toolCallsHtml + '</div>';
        }
        if (chunk) frozenHtml += chunk;
        accumulatedText = '';
        toolCallsHtml = '';
        statusItems = {};
        reasoningHtml = '';
    }

    var savedAssistantText = false;

    eventSource.onmessage = function(event) {
        try {
            var d = JSON.parse(event.data);
            console.log('[SSE] event:', d.type, d.content ? d.content.substring(0, 50) : '');
            if (d.type === 'delta') {
                if (toolCallsHtml) {
                    freezeCurrentOutput();
                }
                accumulatedText += d.content;
                plainTextBuffer += d.content || '';
                flushOutput();
            } else if (d.type === 'done') {
                if (d.content && !plainTextBuffer) {
                    plainTextBuffer = d.content;
                }
                if (accumulatedText || toolCallsHtml || reasoningHtml) {
                    freezeCurrentOutput();
                    bubbleEl.innerHTML = frozenHtml;
                } else if (d.content) {
                    bubbleEl.innerHTML = renderMarkdown(d.content);
                }
                if (!savedAssistantText) {
                    savedAssistantText = true;
                    saveChatMessage(chatSessionId, 'assistant', plainTextBuffer || d.content || '');
                }
                currentEventSource = null;
                activeChatRequestId = null;
                chatHistoryLoaded = false;
                setChatSending(false);
                eventSource.close();
            } else if (d.type === 'error') {
                flushOutput();
                bubbleEl.innerHTML += '<div style="color:var(--destructive);margin-top:8px;">[错误: ' + escapeHtml(d.message || '未知错误') + ']</div>';
                currentEventSource = null;
                activeChatRequestId = null;
                setChatSending(false);
                eventSource.close();
            } else if (d.type === 'reasoning') {
                reasoningHtml += escapeHtml(d.content || '');
                flushOutput();
            } else if (d.type === 'llm_thinking') {
                var elapsed = d.elapsed_seconds || 0;
                upsertStatusItem('agent-working', chapterWorkLabel(userMessage), '思考中 ' + elapsed + 's', '模型仍在生成，页面可保持等待。', 'running');
            } else if (d.type === 'phase_progress') {
                var pd = d.data || {};
                var item = pd.item_label || pd.phase || '处理任务';
                var current = pd.current_item || 0;
                var total = pd.total_items || 0;
                var detail = total ? ('进度 ' + current + '/' + total) : '';
                upsertStatusItem('pipeline-progress', item, '进行中', detail, 'running');
            } else if (d.type === 'tool_start') {
                var toolName = d.tool || 'tool';
                var args = d.arguments || {};
                var argsStr = '';
                try { argsStr = JSON.stringify(args); if (argsStr.length > 200) argsStr = argsStr.substring(0, 200) + '...'; } catch(e) {}
                toolCallsHtml += '<div class="tool-call-item running">';
                toolCallsHtml += '<div class="tool-call-header">';
                toolCallsHtml += '<span class="tool-call-icon">&#9654;</span>';
                toolCallsHtml += '<span class="tool-call-name">' + escapeHtml(toolName) + '</span>';
                toolCallsHtml += '<span class="tool-call-status">执行中...</span>';
                toolCallsHtml += '</div>';
                if (argsStr) {
                    toolCallsHtml += '<div class="tool-call-args">' + escapeHtml(argsStr) + '</div>';
                }
                toolCallsHtml += '<div class="tool-call-result" data-tool="' + escapeHtml(toolName) + '"></div>';
                toolCallsHtml += '</div>';
                flushOutput();
            } else if (d.type === 'tool_end') {
                var endToolName = d.tool || 'tool';
                var endStatus = d.status || 'success';
                var endResult = d.result || '';
                var pipelineBookId = null;
                if (endToolName === 'start_pipeline' && endStatus === 'success') {
                    try {
                        var parsed = typeof endResult === 'string' ? JSON.parse(endResult) : endResult;
                        if (parsed && parsed.book_id) {
                            pipelineBookId = parsed.book_id;
                        }
                    } catch(e) {}
                }
                if (endResult && typeof endResult === 'string' && endResult.length > 300) endResult = endResult.substring(0, 300) + '...';
                var execTime = d.execution_time ? (' (' + d.execution_time + 's)') : '';
                var endClass = endStatus === 'success' ? 'completed' : 'error';
                var statusClass = endStatus === 'success' ? 'done' : 'error';
                var statusText = (endStatus === 'success' ? '完成' : '失败') + execTime;
                toolCallsHtml = replaceLast(toolCallsHtml, 'tool-call-item running', 'tool-call-item ' + endClass);
                toolCallsHtml = replaceLastTag(toolCallsHtml, '<span class="tool-call-icon">', '</span>', '<span class="tool-call-icon ' + statusClass + '">' + (endStatus === 'success' ? '✓' : '×') + '</span>');
                toolCallsHtml = replaceLastTag(toolCallsHtml, '<span class="tool-call-status">', '</span>', '<span class="tool-call-status ' + statusClass + '">' + statusText + '</span>');
                if (endResult) {
                    toolCallsHtml = replaceLast(toolCallsHtml, '<div class="tool-call-result" data-tool="' + escapeHtml(endToolName) + '"></div>', '<div class="tool-call-result" data-tool="' + escapeHtml(endToolName) + '" style="display:block;"><pre>' + escapeHtml(endResult) + '</pre></div>');
                }
                var resultEl = bubbleEl.querySelector('.tool-call-result[data-tool="' + endToolName + '"]');
                var statusEl = bubbleEl.querySelector('.tool-call-item.running:last-child .tool-call-status');
                var iconEl = bubbleEl.querySelector('.tool-call-item.running:last-child .tool-call-icon');
                if (statusEl) {
                    statusEl.textContent = endStatus === 'success' ? '完成' + execTime : '失败' + execTime;
                    statusEl.className = 'tool-call-status ' + (endStatus === 'success' ? 'done' : 'error');
                }
                if (iconEl) {
                    iconEl.innerHTML = endStatus === 'success' ? '&#10003;' : '&#10007;';
                    iconEl.className = 'tool-call-icon ' + (endStatus === 'success' ? 'done' : 'error');
                }
                if (resultEl && endResult) {
                    resultEl.innerHTML = '<pre>' + escapeHtml(endResult) + '</pre>';
                    resultEl.style.display = 'block';
                }
                var runningItem = bubbleEl.querySelector('.tool-call-item.running:last-child');
                if (runningItem) runningItem.className = 'tool-call-item ' + (endStatus === 'success' ? 'completed' : 'error');
                if (endToolName === 'start_pipeline' && endStatus === 'success') {
                    if (pipelineBookId) {
                        currentBookId = pipelineBookId;
                        loadTextbooks().then(function() {
                            selectTextbook(pipelineBookId);
                        });
                    } else {
                        fetch(API_BASE + '/api/textbook').then(function(r) { return r.json(); }).then(function(d) {
                            if (d.status === 'success' && d.textbooks && d.textbooks.length > 0) {
                                var latest = d.textbooks[d.textbooks.length - 1];
                                if (latest && latest.id) {
                                    currentBookId = latest.id;
                                    loadTextbooks().then(function() {
                                        selectTextbook(latest.id);
                                    });
                                }
                            }
                        }).catch(function() {});
                    }
                }
                flushOutput();
            } else if (d.type === 'message_end') {
                if (d.has_tool_calls) {
                    freezeCurrentOutput();
                    flushOutput();
                }
            } else if (d.type === 'pipeline_start') {
                var bookId = (d.data && d.data.book_id) || currentBookId;
                if (bookId) {
                    currentBookId = bookId;
                }
                toolCallsHtml += '<div class="tool-call-item running pipeline-step"><div class="tool-call-header"><span class="tool-call-icon">▶</span><span class="tool-call-name">教材管线</span><span class="tool-call-status">执行中</span></div><div class="tool-call-args">7 阶段自动编制流程已启动</div></div>';
                flushOutput();
            } else if (d.type === 'phase_start') {
                var phaseName = (d.data && d.data.phase) || '';
                var phaseLabel = (d.data && d.data.phase_label) || phaseName;
                var phaseIcons = {'outline':'📋','review_outline':'🔍','compose':'🔧','write':'✍️','review_chapter':'🔎','revise':'✏️','persist':'💾'};
                var icon = phaseIcons[phaseName] || '▶';
                toolCallsHtml += '<div class="tool-call-item running pipeline-step"><div class="tool-call-header"><span class="tool-call-icon">' + icon + '</span><span class="tool-call-name">' + escapeHtml(phaseLabel || phaseName) + '</span><span class="tool-call-status">进行中</span></div></div>';
                flushOutput();
            } else if (d.type === 'phase_complete') {
                var phaseName2 = (d.data && d.data.phase) || '';
                var phaseLabel2 = (d.data && d.data.phase_label) || phaseName2;
                var summary = (d.data && d.data.result_summary) || '';
                toolCallsHtml += '<div class="tool-call-item completed pipeline-step"><div class="tool-call-header"><span class="tool-call-icon done">✓</span><span class="tool-call-name">' + escapeHtml(phaseLabel2 || phaseName2) + '</span><span class="tool-call-status done">完成</span></div>';
                if (summary) toolCallsHtml += '<div class="tool-call-result" style="display:block;"><pre>' + escapeHtml(summary) + '</pre></div>';
                toolCallsHtml += '</div>';
                flushOutput();
            } else if (d.type === 'pipeline_complete') {
                var totalCh = (d.data && d.data.total_chapters) || 0;
                toolCallsHtml += '<div class="tool-call-item completed pipeline-step pipeline-done"><div class="tool-call-header"><span class="tool-call-icon done">✓</span><span class="tool-call-name">管线执行完成</span><span class="tool-call-status done">完成</span></div>';
                if (totalCh) toolCallsHtml += '<div class="tool-call-args">共完成 ' + totalCh + ' 章编写</div>';
                toolCallsHtml += '</div>';
                flushOutput();
            } else if (d.type === 'pipeline_error') {
                var errMsg = (d.data && d.data.error) || '管线执行出错';
                toolCallsHtml += '<div class="tool-call-item error pipeline-step"><div class="tool-call-header"><span class="tool-call-icon error">×</span><span class="tool-call-name">管线执行失败</span><span class="tool-call-status error">失败</span></div><div class="tool-call-result" style="display:block;"><pre>' + escapeHtml(errMsg) + '</pre></div></div>';
                flushOutput();
            }
        } catch (e) {
            // ignore parse errors for keepalive
        }
    };

    eventSource.onerror = function() {
        if (accumulatedText || toolCallsHtml || reasoningHtml) {
            freezeCurrentOutput();
            bubbleEl.innerHTML = frozenHtml;
        }
        if (!savedAssistantText && plainTextBuffer.trim()) {
            savedAssistantText = true;
            saveChatMessage(chatSessionId, 'assistant', plainTextBuffer);
        }
        currentEventSource = null;
        activeChatRequestId = null;
        setChatSending(false);
        eventSource.close();
    };
}

function appendChatMessage(role, content) {
    var messages = document.getElementById('chatMessages');
    var msgDiv = document.createElement('div');
    msgDiv.className = 'chat-msg ' + role;

    var avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = role === 'user' ? 'U' : 'T';

    var wrapper = document.createElement('div');
    wrapper.className = 'chat-content-wrapper';

    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    if (role === 'assistant') {
        bubble.innerHTML = content ? renderMarkdown(content) : '';
    } else {
        bubble.textContent = content;
    }
    wrapper.appendChild(bubble);

    var actions = document.createElement('div');
    actions.className = 'chat-msg-actions';
    if (role === 'user') {
        actions.innerHTML = '<button class="chat-action-btn" onclick="copyMessage(this)" title="复制"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>' +
            '<button class="chat-action-btn" onclick="deleteMessage(this)" title="删除"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg></button>' +
            '<button class="chat-action-btn" onclick="rollbackMessage(this)" title="回退到本轮对话前"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg></button>';
    } else {
        actions.innerHTML = '<button class="chat-action-btn" onclick="copyAssistantMessage(this)" title="复制全部"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>' +
            '<button class="chat-action-btn" onclick="refreshAssistantMessage(this)" title="刷新"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg></button>';
    }
    wrapper.appendChild(actions);

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(wrapper);
    messages.appendChild(msgDiv);
    messages.scrollTop = messages.scrollHeight;

    return msgDiv;
}

async function executeSandbox(code, timeout) {
    try {
        var response = await fetch(API_BASE + '/api/sandbox/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code: code, timeout: timeout || 30})
        });
        var data = await response.json();
        return data;
    } catch (e) {
        console.error('Sandbox execute error:', e);
        return {status: 'error', message: e.message};
    }
}

async function generateChart(chartType, data) {
    try {
        var response = await fetch(API_BASE + '/api/sandbox/charts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({chart_type: chartType, data: data})
        });
        var result = await response.json();
        return result;
    } catch (e) {
        console.error('Chart generation error:', e);
        return {status: 'error', message: e.message};
    }
}

var _allSkills = [];
var _skillFilter = 'all';

async function loadSkills() {
    try {
        var response = await fetch(API_BASE + '/api/skills');
        var data = await response.json();
        if (data.status === 'success') {
            _allSkills = data.skills || [];
            filterSkills(_skillFilter);
        }
    } catch (e) {
        console.error('Failed to load skills:', e);
    }
}

function filterSkills(filter) {
    _skillFilter = filter;
    document.querySelectorAll('.skill-filter-btn').forEach(function(btn) {
        btn.style.background = 'var(--card)';
        btn.style.color = 'var(--fg)';
    });
    var activeBtn = document.getElementById('filter-' + filter);
    if (activeBtn) {
        activeBtn.style.background = '#10b981';
        activeBtn.style.color = '#fff';
    }
    var filtered = _allSkills;
    if (filter === 'builtin') {
        filtered = _allSkills.filter(function(s) { return s.source === 'builtin'; });
    } else if (filter === 'custom') {
        filtered = _allSkills.filter(function(s) { return s.source === 'custom'; });
    }
    renderSkills(filtered);
}

function renderSkills(skills) {
    var grid = document.getElementById('skillsGrid');
    if (!skills || skills.length === 0) {
        grid.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted-fg);grid-column:1/-1;">暂无技能数据</div>';
        return;
    }

    var builtinColors = ['rgba(99,102,241,0.1)', 'rgba(37,99,235,0.1)', 'rgba(5,150,105,0.1)', 'rgba(139,92,246,0.1)', 'rgba(245,158,11,0.1)', 'rgba(236,72,153,0.1)', 'rgba(239,68,68,0.1)'];
    var builtinTextColors = ['var(--phase-persist)', 'var(--secondary)', 'var(--accent)', 'var(--phase-outline)', 'var(--phase-review)', 'var(--phase-polish)', 'var(--phase-revise)'];
    var customColor = 'rgba(16,185,129,0.1)';
    var customTextColor = 'var(--accent)';

    var html = '';
    for (var i = 0; i < skills.length; i++) {
        var skill = skills[i];
        var name = skill.name || skill.display_name || ('技能 ' + (i + 1));
        var desc = skill.description || skill.name || '';
        var isEnabled = skill.enabled !== false;
        var isBuiltin = skill.source === 'builtin';
        var colorIdx = i % builtinColors.length;
        var bgColor = isBuiltin ? builtinColors[colorIdx] : customColor;
        var txtColor = isBuiltin ? builtinTextColors[colorIdx] : customTextColor;
        var icon = isBuiltin ? 'B' : 'C';

        html += '<div style="background:var(--card);border:1px solid var(--border);border-radius:var(--radius-md);padding:16px;display:flex;align-items:center;gap:12px;">';
        html += '<div style="width:36px;height:36px;border-radius:var(--radius-sm);background:' + bgColor + ';color:' + txtColor + ';display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;">' + icon + '</div>';
        html += '<div style="flex:1"><div style="font-size:13px;font-weight:600;display:flex;align-items:center;gap:6px;">' + escapeHtml(name);
        if (isBuiltin) {
            html += '<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:rgba(99,102,241,0.1);color:var(--phase-persist);font-weight:500;">内置</span>';
        } else {
            html += '<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:rgba(16,185,129,0.1);color:var(--accent);font-weight:500;">自定义</span>';
        }
        html += '</div><div style="font-size:11px;color:var(--muted-fg)">' + escapeHtml(desc) + '</div></div>';
        html += '<label class="export-toggle" style="margin:0;"><input type="checkbox" ' + (isEnabled ? 'checked' : '') + ' onchange="toggleSkill(\'' + escapeHtml(name) + '\', this.checked)"><span class="toggle-switch"></span></label>';
        if (!isBuiltin) {
            html += '<button onclick="deleteSkill(\'' + escapeHtml(name) + '\')" title="删除技能" style="background:none;border:none;color:var(--muted-fg);cursor:pointer;padding:4px;font-size:14px;line-height:1;">&times;</button>';
        }
        html += '</div>';
    }
    grid.innerHTML = html;
}

async function toggleSkill(name, enabled) {
    try {
        await fetch(API_BASE + '/api/skills', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: enabled ? 'open' : 'close', name: name})
        });
    } catch (e) {
        console.error('Failed to toggle skill:', e);
    }
}

async function deleteSkill(name) {
    if (!confirm('确定要删除自定义技能 "' + name + '" 吗？')) return;
    try {
        var response = await fetch(API_BASE + '/api/skills', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'delete', name: name})
        });
        var data = await response.json();
        if (data.status === 'success') {
            loadSkills();
        } else {
            alert(data.message || '删除失败');
        }
    } catch (e) {
        console.error('Failed to delete skill:', e);
    }
}

function showAddSkillModal() {
    document.getElementById('addSkillModal').style.display = 'flex';
    var fileInput = document.getElementById('skillZipFile');
    if (fileInput) fileInput.value = '';
    var statusEl = document.getElementById('skillUploadStatus');
    if (statusEl) { statusEl.style.display = 'none'; statusEl.textContent = ''; }
}

function hideAddSkillModal() {
    document.getElementById('addSkillModal').style.display = 'none';
}

async function uploadSkill() {
    var fileInput = document.getElementById('skillZipFile');
    var statusEl = document.getElementById('skillUploadStatus');
    var btn = document.getElementById('uploadSkillBtn');

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        if (statusEl) { statusEl.style.display = 'block'; statusEl.style.color = 'var(--destructive)'; statusEl.textContent = '请选择一个 .zip 压缩文件'; }
        return;
    }

    var file = fileInput.files[0];
    if (!file.name.toLowerCase().endsWith('.zip')) {
        if (statusEl) { statusEl.style.display = 'block'; statusEl.style.color = 'var(--destructive)'; statusEl.textContent = '仅支持 .zip 格式文件'; }
        return;
    }

    btn.disabled = true;
    btn.textContent = '上传中...';
    if (statusEl) { statusEl.style.display = 'block'; statusEl.style.color = 'var(--muted-fg)'; statusEl.textContent = '正在上传并解压...'; }

    try {
        var formData = new FormData();
        formData.append('file', file);
        var response = await fetch(API_BASE + '/api/skills', { method: 'POST', body: formData });
        var data = await response.json();
        if (data.status === 'success') {
            if (statusEl) { statusEl.style.color = '#10b981'; statusEl.textContent = data.message || '安装成功'; }
            setTimeout(function() { hideAddSkillModal(); loadSkills(); }, 1200);
        } else {
            if (statusEl) { statusEl.style.color = 'var(--destructive)'; statusEl.textContent = data.message || '上传失败'; }
        }
    } catch (e) {
        console.error('Failed to upload skill:', e);
        if (statusEl) { statusEl.style.color = 'var(--destructive)'; statusEl.textContent = '上传失败: ' + e.message; }
    } finally {
        btn.disabled = false;
        btn.textContent = '上传并安装';
    }
}

async function refreshSkills() {
    try {
        var response = await fetch(API_BASE + '/api/skills', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'refresh'})
        });
        var data = await response.json();
        if (data.status === 'success') {
            _allSkills = data.skills || [];
            filterSkills(_skillFilter);
        }
    } catch (e) {
        console.error('Failed to refresh skills:', e);
    }
}

function aiOptimizeOutline() {
    if (!currentBookId) { alert('请先选择一本教材'); return; }
    navigateToChat('请优化教材《' + (currentBookData ? currentBookData.title : '') + '》的大纲结构，给出优化建议');
}

function reviewOutline() {
    if (!currentBookId) { alert('请先选择一本教材'); return; }
    navigateToChat('请审查教材《' + (currentBookData ? currentBookData.title : '') + '》的大纲');
}

var _configProviders = {};
var _configApiKeys = {};
var _configApiBases = {};
var _configChatModels = [];
var _configActiveChatModelId = '';
var _configReviewModelId = '';
var _configImageModelId = '';
var _configKnowledgeModelId = '';
var _configProviderKeyUpdates = {};

function normalizeProviderId(pid) {
    return pid === 'chatGPT' ? 'openai' : (pid || '');
}

function botTypeForProvider(pid) {
    var providerMap = {
        'openai': 'chatGPT', 'custom': 'custom', 'deepseek': 'deepseek',
        'zhipu': 'zhipu', 'dashscope': 'dashscope', 'qianfan': 'qianfan',
        'gemini': 'gemini', 'claudeAPI': 'claudeAPI', 'minimax': 'minimax',
        'moonshot': 'moonshot', 'doubao': 'doubao', 'linkai': 'linkai'
    };
    return providerMap[pid] || pid || '';
}

function fillProviderSelect(selectEl, currentProvider) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    for (var pid in _configProviders) {
        var p = _configProviders[pid];
        if (pid === 'bocha') continue;
        var opt = document.createElement('option');
        opt.value = pid;
        opt.textContent = p.label;
        selectEl.appendChild(opt);
    }
    if (currentProvider) selectEl.value = normalizeProviderId(currentProvider);
}

function modelDisplayName(item) {
    var provider = _configProviders[item.provider] || {};
    return (item.name || item.model || '未命名模型') + ' · ' + (provider.label || item.provider || '自定义');
}

function hydrateLegacyChatModels(data) {
    var list = (data.ai_chat_models || []).slice();
    if (!list.length && data.model) {
        list.push({
            id: data.active_chat_model_id || 'default',
            name: data.model,
            provider: normalizeProviderId(data.bot_type || 'custom'),
            model: data.model,
            api_base: ''
        });
    }
    list = list.map(function(item) {
        return {
            id: item.id,
            name: item.name || item.model || '',
            provider: item.provider || 'custom',
            model: item.model || item.name || '',
            api_base: item.api_base || '',
            provider_key_configured: !!item.provider_key_configured
        };
    });
    return list;
}

function renderModelPool() {
    var pool = document.getElementById('settingModelPool');
    if (!pool) return;
    if (!_configChatModels.length) {
        pool.innerHTML = '<div class="settings-empty">尚未配置模型，请先添加一个 AI 对话模型。</div>';
    } else {
        pool.innerHTML = _configChatModels.map(function(item) {
            var isActive = item.id === _configActiveChatModelId;
            return '<div class="settings-model-card' + (isActive ? ' active' : '') + '">' +
                '<div><div class="settings-model-title">' + escapeHtml(modelDisplayName(item)) + '</div>' +
                '<div class="settings-model-meta">' + escapeHtml(item.model || '') + ' · ' + escapeHtml(item.api_base || '默认 URL') + ' · ' + (item.provider_key_configured ? '已配置供应商密钥' : '未配置供应商密钥') + '</div></div>' +
                '<div class="settings-model-actions">' +
                '<button class="chat-action-btn" onclick="editChatModel(&quot;' + escapeHtml(item.id) + '&quot;)" title="编辑">编辑</button>' +
                '<button class="chat-action-btn" onclick="removeChatModel(&quot;' + escapeHtml(item.id) + '&quot;)" title="删除">删除</button>' +
                '</div></div>';
        }).join('');
    }
    fillModelChoice(document.getElementById('settingActiveChatModel'), _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingReviewModelChoice'), _configReviewModelId || _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingImageModelChoice'), _configImageModelId || _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingKnowledgeModelChoice'), _configKnowledgeModelId || _configActiveChatModelId);
}

function fillModelChoice(selectEl, selectedId) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    _configChatModels.forEach(function(item) {
        var opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = modelDisplayName(item);
        selectEl.appendChild(opt);
    });
    if (selectedId) selectEl.value = selectedId;
}

function onModelProviderChange() {
    var providerSelect = document.getElementById('settingModelProvider');
    var apiBaseInput = document.getElementById('settingModelApiBase');
    var apiKeyInput = document.getElementById('settingModelApiKey');
    if (!providerSelect || !apiBaseInput) return;
    var provider = _configProviders[providerSelect.value] || {};
    apiBaseInput.value = _configApiBases[provider.api_base_key] || provider.api_base_default || '';
    apiBaseInput.placeholder = provider.api_base_placeholder || 'https://...../v1';
    if (apiKeyInput) {
        var keyField = provider.api_key_field || '';
        apiKeyInput.value = _configProviderKeyUpdates[keyField] || _configApiKeys[keyField] || '';
        apiKeyInput.placeholder = keyField ? '配置 ' + (provider.label || providerSelect.value) + ' 全局 API Key' : '该供应商无需 API Key';
    }
}

function editChatModel(modelId) {
    var item = _configChatModels.find(function(m) { return m.id === modelId; });
    if (!item) return;
    document.getElementById('settingEditModelId').value = item.id || '';
    document.getElementById('settingModelProvider').value = item.provider || 'custom';
    document.getElementById('settingModelName').value = item.model || '';
    onModelProviderChange();
    if (item.api_base) document.getElementById('settingModelApiBase').value = item.api_base;
}

function removeChatModel(modelId) {
    _configChatModels = _configChatModels.filter(function(m) { return m.id !== modelId; });
    if (_configActiveChatModelId === modelId) _configActiveChatModelId = _configChatModels[0] ? _configChatModels[0].id : '';
    if (_configReviewModelId === modelId) _configReviewModelId = _configActiveChatModelId;
    if (_configImageModelId === modelId) _configImageModelId = _configActiveChatModelId;
    if (_configKnowledgeModelId === modelId) _configKnowledgeModelId = _configActiveChatModelId;
    renderModelPool();
}

function addOrUpdateChatModel() {
    var editId = document.getElementById('settingEditModelId').value || '';
    var provider = document.getElementById('settingModelProvider').value || 'custom';
    var modelName = document.getElementById('settingModelName').value.trim();
    if (!modelName) {
        showToast('请填写模型名称', 'error');
        return;
    }
    var item = {
        id: editId || ('model_' + Date.now()),
        name: modelName,
        provider: provider,
        model: modelName,
        api_base: document.getElementById('settingModelApiBase').value.trim()
    };
    var providerInfo = _configProviders[provider] || {};
    var keyField = providerInfo.api_key_field || '';
    var keyValue = document.getElementById('settingModelApiKey').value.trim();
    if (keyField && keyValue && keyValue.indexOf('*') < 0) {
        _configProviderKeyUpdates[keyField] = keyValue;
        item.provider_key_configured = true;
    } else {
        item.provider_key_configured = !!(_configApiKeys[keyField] || _configProviderKeyUpdates[keyField]);
    }
    var idx = _configChatModels.findIndex(function(m) { return m.id === item.id; });
    if (idx >= 0) _configChatModels[idx] = item;
    else _configChatModels.push(item);
    if (!_configActiveChatModelId) _configActiveChatModelId = item.id;
    document.getElementById('settingEditModelId').value = '';
    document.getElementById('settingModelName').value = '';
    document.getElementById('settingModelApiKey').value = '';
    renderModelPool();
}

function loadSettings() {
    fetch(API_BASE + '/config').then(function(r) { return r.json(); }).then(function(data) {
        if (data.status !== 'success') return;
        _configProviders = data.providers || {};
        _configApiKeys = data.api_keys || {};
        _configApiBases = data.api_bases || {};
        _configProviderKeyUpdates = {};
        _configChatModels = hydrateLegacyChatModels(data);
        _configActiveChatModelId = data.active_chat_model_id || (_configChatModels[0] ? _configChatModels[0].id : '');
        _configReviewModelId = data.review_model_id || _configActiveChatModelId;
        _configImageModelId = data.image_model_id || _configActiveChatModelId;
        _configKnowledgeModelId = data.knowledge_model_id || _configActiveChatModelId;
        fillProviderSelect(document.getElementById('settingModelProvider'), _configChatModels[0] ? _configChatModels[0].provider : 'custom');
        onModelProviderChange();
        renderModelPool();
        var maxTokens = document.getElementById('settingMaxTokens');
        if (maxTokens) maxTokens.value = data.agent_max_context_tokens || 50000;
        var maxTurns = document.getElementById('settingMaxTurns');
        if (maxTurns) maxTurns.value = data.agent_max_context_turns || 20;
        var maxSteps = document.getElementById('settingMaxSteps');
        if (maxSteps) maxSteps.value = data.agent_max_steps || 20;
        var thinking = document.getElementById('settingThinking');
        if (thinking) thinking.checked = data.enable_thinking || false;
    }).catch(function(e) { console.error('Failed to load settings:', e); });
}

function saveSettings() {
    var maxTokens = document.getElementById('settingMaxTokens');
    var maxTurns = document.getElementById('settingMaxTurns');
    var maxSteps = document.getElementById('settingMaxSteps');
    var thinking = document.getElementById('settingThinking');
    var updates = {};
    var activeSelect = document.getElementById('settingActiveChatModel');
    var reviewSelect = document.getElementById('settingReviewModelChoice');
    var imageSelect = document.getElementById('settingImageModelChoice');
    var knowledgeSelect = document.getElementById('settingKnowledgeModelChoice');
    updates.ai_chat_models = _configChatModels;
    updates.active_chat_model_id = activeSelect ? activeSelect.value : _configActiveChatModelId;
    updates.review_model_id = reviewSelect ? reviewSelect.value : updates.active_chat_model_id;
    updates.image_model_id = imageSelect ? imageSelect.value : updates.active_chat_model_id;
    updates.knowledge_model_id = knowledgeSelect ? knowledgeSelect.value : updates.active_chat_model_id;
    if (maxTokens) updates.agent_max_context_tokens = parseInt(maxTokens.value) || 50000;
    if (maxTurns) updates.agent_max_context_turns = parseInt(maxTurns.value) || 20;
    if (maxSteps) updates.agent_max_steps = parseInt(maxSteps.value) || 20;
    if (thinking) updates.enable_thinking = thinking.checked;
    var providerSelect = document.getElementById('settingModelProvider');
    var keyInput = document.getElementById('settingModelApiKey');
    if (providerSelect && keyInput) {
        var providerInfo = _configProviders[providerSelect.value] || {};
        var keyField = providerInfo.api_key_field || '';
        var keyValue = keyInput.value.trim();
        if (keyField && keyValue && keyValue.indexOf('*') < 0) {
            _configProviderKeyUpdates[keyField] = keyValue;
        }
    }
    for (var key in _configProviderKeyUpdates) {
        if (_configProviderKeyUpdates[key]) updates[key] = _configProviderKeyUpdates[key];
    }
    fetch(API_BASE + '/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({updates: updates})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.status === 'success') {
            showToast('配置已保存');
            loadSettings();
        } else {
            showToast('保存失败: ' + (data.message || '未知错误'), 'error');
        }
    }).catch(function(e) {
        showToast('保存失败: ' + e.message, 'error');
    });
}

async function sendChatMessageDirect(message) {
    appendChatMessage('user', message);
    try {
        var response = await fetch(API_BASE + '/message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: chatSessionId,
                message: message,
                stream: true
            })
        });
        var data = await response.json();
        if (data.status === 'success' && data.stream) {
            startChatSSE(data.request_id);
        }
    } catch (e) {
        appendChatMessage('assistant', '发送失败: ' + e.message);
    }
}

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function toggleAttachMenu(event) {
    event.stopPropagation();
    var menu = document.getElementById('attachMenu');
    menu.classList.toggle('hidden');
}

function triggerFileUpload() {
    document.getElementById('chatFileInput').click();
    document.getElementById('attachMenu').classList.add('hidden');
}

function handleFileSelect(files) {
    for (var i = 0; i < files.length; i++) {
        uploadFile(files[i]);
    }
}

function uploadFile(file) {
    var formData = new FormData();
    formData.append('file', file);
    fetch(API_BASE + '/upload', {
        method: 'POST',
        body: formData
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'success') {
            pendingAttachments.push({
                file_path: data.file_path,
                file_name: data.file_name,
                file_type: data.file_type,
                preview_url: data.preview_url || ''
            });
            renderAttachmentPreview();
        }
    })
    .catch(function(e) {
        console.error('Upload failed:', e);
    });
}

function renderAttachmentPreview() {
    var container = document.getElementById('attachment-preview');
    if (pendingAttachments.length === 0) {
        container.classList.add('hidden');
        container.innerHTML = '';
        return;
    }
    container.classList.remove('hidden');
    var html = '';
    for (var i = 0; i < pendingAttachments.length; i++) {
        var att = pendingAttachments[i];
        var icon = 'fa-file';
        if (att.file_type === 'image') icon = 'fa-file-image';
        else if (att.file_name.endsWith('.pdf')) icon = 'fa-file-pdf';
        else if (att.file_name.endsWith('.doc') || att.file_name.endsWith('.docx')) icon = 'fa-file-word';
        html += '<div class="attachment-chip">';
        if (att.file_type === 'image' && att.preview_url) {
            html += '<img src="' + att.preview_url + '" class="attachment-thumb">';
        } else {
            html += '<i class="fas ' + icon + ' attachment-icon"></i>';
        }
        html += '<span class="attachment-name">' + att.file_name + '</span>';
        html += '<button class="attachment-remove" onclick="removeAttachment(' + i + ')">&times;</button>';
        html += '</div>';
    }
    container.innerHTML = html;
}

function removeAttachment(index) {
    pendingAttachments.splice(index, 1);
    renderAttachmentPreview();
}

document.addEventListener('change', function(e) {
    if (e.target.closest('#chapterCheckList')) {
        updateChapterCount();
    }
});

function loadTextbookDetail() {
    if (!currentBookId) {
        switchView('workspace');
        return;
    }
    if (currentBookData) {
        var titleEl = document.getElementById('detailBookTitle');
        var metaEl = document.getElementById('detailBookMeta');
        if (titleEl) titleEl.textContent = currentBookData.title || '教材详情';
        if (metaEl) {
            var parts = [];
            if (currentBookData.subject) parts.push(currentBookData.subject);
            if (currentBookData.target_audience) parts.push(currentBookData.target_audience);
            if (currentBookData.total_chapters) parts.push(currentBookData.total_chapters + '章');
            metaEl.textContent = parts.join(' · ') || '';
        }
    }
    loadOutlineForEditor();
    loadBookPreferences();
}

function switchTab(el, tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    const pane = document.getElementById('tab-' + tabName);
    if (pane) pane.classList.add('active');
    if (tabName === 'outline-edit') loadOutlineForEditor();
    if (tabName === 'chapter-preview') loadChapterTree();
    if (tabName === 'export') { }
    if (tabName === 'knowledge') loadBookKnowledge();
    if (tabName === 'preferences') loadBookPreferences();
}

function loadOutlineForEditor() {
    if (!currentBookId) return;
    fetch(`/api/textbook/${currentBookId}/outline`)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && data.outline) {
                const editor = document.getElementById('outlineEditor');
                if (editor) editor.value = data.outline;
                renderOutlinePreview(data.outline);
            }
        })
        .catch(err => console.error('Load outline error:', err));
}

function renderOutlinePreview(markdown) {
    const preview = document.getElementById('outlinePreview');
    if (!preview || !markdown) return;
    if (typeof marked !== 'undefined') {
        preview.innerHTML = marked.parse(markdown);
    } else if (typeof markdownit !== 'undefined') {
        preview.innerHTML = window.markdownit().render(markdown);
    } else {
        preview.textContent = markdown;
    }
}

function previewOutline() {
    var editor = document.getElementById('outlineEditor');
    if (editor) renderOutlinePreview(editor.value);
}

function saveOutlineEdit() {
    if (!currentBookId) return;
    const editor = document.getElementById('outlineEditor');
    if (!editor) return;
    const content = editor.value;
    const message = prompt('版本说明（可选）:', '手动编辑大纲') || '手动编辑大纲';

    fetch(`/api/textbook/${currentBookId}/outline/versions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content: content, message: message})
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showToast('大纲已保存');
            renderOutlinePreview(content);
        } else {
            showToast('保存失败: ' + (data.message || '未知错误'), 'error');
        }
    })
    .catch(err => {
        showToast('保存失败: ' + err, 'error');
    });
}

function showOutlineHistory() {
    if (!currentBookId) return;
    fetch(`/api/textbook/${currentBookId}/outline/versions`)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && data.versions) {
                let html = '<div style="max-height:400px;overflow-y:auto;">';
                data.versions.forEach(v => {
                    html += `<div style="padding:10px;border-bottom:1px solid var(--border);cursor:pointer;" onclick="restoreOutlineVersion('${v.version_id}')">
                        <div style="font-weight:600;font-size:13px;">${v.message || '无说明'}</div>
                        <div style="font-size:11px;color:var(--muted-fg);">${v.timestamp}</div>
                    </div>`;
                });
                html += '</div>';
                if (data.versions.length === 0) html = '<div style="padding:20px;text-align:center;color:var(--muted-fg);">暂无版本历史</div>';
                showSimpleModal('版本历史', html);
            }
        })
        .catch(err => console.error('Load versions error:', err));
}

function restoreOutlineVersion(versionId) {
    if (!currentBookId || !versionId) return;
    if (!confirm('确定恢复到此版本？')) return;
    fetch('/api/textbook/' + currentBookId + '/outline/versions/' + versionId + '/restore', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'success') {
            showToast('已恢复到选定版本');
            loadOutlineForEditor();
            var modal = document.getElementById('simpleModal');
            if (modal) modal.style.display = 'none';
        } else {
            showToast('恢复失败: ' + (data.message || '未知错误'), 'error');
        }
    })
    .catch(function(err) { showToast('恢复失败: ' + err, 'error'); });
}

function startReview(level, target) {
    if (!currentBookId) return;
    const reviewResults = document.getElementById('reviewResults');
    if (reviewResults) reviewResults.innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted-fg);">正在审查中...</div>';

    fetch(`/api/textbook/${currentBookId}/review`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({level: level, target: target || ''})
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            renderReviewResults(data.result);
        } else {
            if (reviewResults) reviewResults.innerHTML = `<div style="padding:20px;color:var(--danger);">审查失败: ${data.message || '未知错误'}</div>`;
        }
    })
    .catch(err => {
        if (reviewResults) reviewResults.innerHTML = `<div style="padding:20px;color:var(--danger);">审查请求失败: ${err}</div>`;
    });
}

function renderReviewResults(result) {
    const container = document.getElementById('reviewResults');
    if (!container) return;
    if (!result) {
        container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted-fg);">暂无审查结果</div>';
        return;
    }
    let html = `<div style="margin-bottom:16px;display:flex;align-items:center;gap:12px;">
        <div style="font-size:32px;font-weight:800;color:${result.passed ? 'var(--success)' : 'var(--danger)'}">${result.score.toFixed(1)}</div>
        <div><div style="font-weight:700;">${result.passed ? '审查通过' : '审查未通过'}</div><div style="font-size:12px;color:var(--muted-fg);">共发现 ${result.issues ? result.issues.length : 0} 个问题</div></div>
    </div>`;
    if (result.issues && result.issues.length > 0) {
        result.issues.forEach(issue => {
            const levelClass = issue.level === 'critical' ? 'critical' : issue.level === 'warning' ? 'warning' : 'suggestion';
            const levelLabel = issue.level === 'critical' ? '严重问题' : issue.level === 'warning' ? '警告' : '建议';
            html += `<div class="issue-card ${levelClass}">
                <div class="issue-header">
                    <div class="issue-title">${issue.description || ''}</div>
                    <span class="issue-type ${levelClass}">${levelLabel}</span>
                </div>
                ${issue.suggestion ? `<div class="issue-content">建议: ${issue.suggestion}</div>` : ''}
                ${issue.location ? `<div class="issue-location">📍 ${issue.location}</div>` : ''}
            </div>`;
        });
    }
    container.innerHTML = html;
}

function loadKnowledgePage() {
    loadKnowledgeBookSelector();
    loadKnowledgeSources();
    loadKnowledgeStatus();
    loadKnowledgeGraph('', 'knowledgeGraphArea');
}

function loadKnowledgeBookSelector() {
    var select = document.getElementById('knowledgeBookSelect');
    if (!select) return;
    fetch(API_BASE + '/api/textbook')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                var books = data.textbooks || [];
                var currentVal = select.value;
                var html = '<option value="">全部知识库</option>';
                books.forEach(function(b) {
                    html += '<option value="' + escapeHtml(b.id) + '">' + escapeHtml(b.title || b.id) + '</option>';
                });
                select.innerHTML = html;
                if (currentVal) select.value = currentVal;
            }
        })
        .catch(function(err) { console.error('Load book selector error:', err); });
}

function onKnowledgeBookChange() {
    var select = document.getElementById('knowledgeBookSelect');
    var bookId = select ? select.value : '';
    loadKnowledgeSources(bookId);
    loadKnowledgeStatus(bookId);
    loadKnowledgeGraph(bookId, 'knowledgeGraphArea');
}

function organizeKnowledge() {
    var select = document.getElementById('knowledgeBookSelect');
    var bookId = select ? select.value : '';
    var btn = document.getElementById('btnOrganizeKnowledge');
    if (btn) { btn.disabled = true; btn.textContent = '整理中...'; }
    updateKnowledgeOrganizeProgress('knowledge', {status:'starting', stage:'starting', message:'准备整理知识库'});
    fetch(API_BASE + '/api/knowledge/organize', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({book_id: bookId})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'started') {
            _pollOrganizeStatus(bookId, btn);
        } else if (data.status === 'already_running') {
            _pollOrganizeStatus(bookId, btn);
        } else {
            if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> AI整理'; }
            showToast('整理失败: ' + (data.message || ''), 'error');
        }
    })
    .catch(function(err) {
        if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> AI整理'; }
        showToast('整理失败: ' + err, 'error');
    });
}

function _pollOrganizeStatus(bookId, btn) {
    var pollUrl = API_BASE + '/api/knowledge/organize?book_id=' + encodeURIComponent(bookId || '');
    var pollInterval = setInterval(function() {
        fetch(pollUrl)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                updateKnowledgeOrganizeProgress('knowledge', data);
                if (data.status === 'done') {
                    clearInterval(pollInterval);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> AI整理'; }
                    var result = data.result || {};
                    showToast('整理完成: ' + (result.message || 'organized ' + (result.organized_count || 0) + ' entries'));
                    loadKnowledgeSources(bookId);
                    loadKnowledgeStatus(bookId);
                    loadKnowledgeGraph(bookId, 'knowledgeGraphArea');
                } else if (data.status === 'error') {
                    clearInterval(pollInterval);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> AI整理'; }
                    showToast('整理失败: ' + (data.error || ''), 'error');
                }
            })
            .catch(function() {});
    }, 3000);
}

function organizeBookKnowledge() {
    if (!currentBookId) { showToast('请先选择教材', 'error'); return; }
    var btns = document.querySelectorAll('#tab-knowledge .btn-primary');
    var btn = null;
    btns.forEach(function(b) { if (b.textContent.indexOf('AI整理') >= 0 || b.textContent.indexOf('整理中') >= 0 || b.textContent.indexOf('一键AI整理') >= 0) btn = b; });
    if (btn) { btn.disabled = true; btn.textContent = '整理中...'; }
    updateKnowledgeOrganizeProgress('bookKnowledge', {status:'starting', stage:'starting', message:'准备整理教材知识库'});
    fetch(API_BASE + '/api/knowledge/organize', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({book_id: currentBookId})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'started' || data.status === 'already_running') {
            _pollBookOrganizeStatus(currentBookId, btn);
        } else {
            if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 一键AI整理'; }
            showToast('整理失败: ' + (data.message || ''), 'error');
        }
    })
    .catch(function(err) {
        if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 一键AI整理'; }
        showToast('整理失败: ' + err, 'error');
    });
}

function _pollBookOrganizeStatus(bookId, btn) {
    var pollUrl = API_BASE + '/api/knowledge/organize?book_id=' + encodeURIComponent(bookId);
    var pollInterval = setInterval(function() {
        fetch(pollUrl)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                updateKnowledgeOrganizeProgress('bookKnowledge', data);
                if (data.status === 'done') {
                    clearInterval(pollInterval);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 一键AI整理'; }
                    var result = data.result || {};
                    showToast('整理完成: ' + (result.message || 'organized ' + (result.organized_count || 0) + ' entries'));
                    loadBookKnowledge();
                    loadKnowledgeStatus(bookId);
                    loadKnowledgeGraph(bookId, 'bookKnowledgeGraphArea');
                } else if (data.status === 'error') {
                    clearInterval(pollInterval);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> 一键AI整理'; }
                    showToast('整理失败: ' + (data.error || ''), 'error');
                }
            })
            .catch(function() {});
    }, 3000);
}

function updateKnowledgeOrganizeProgress(prefix, data) {
    var panel = document.getElementById(prefix + 'OrganizeProgress');
    if (!panel) return;
    panel.style.display = 'block';
    data = data || {};
    var stageEl = document.getElementById(prefix + 'OrganizeStage');
    var fillEl = document.getElementById(prefix + 'OrganizeFill');
    var msgEl = document.getElementById(prefix + 'OrganizeMessage');
    var metaEl = document.getElementById(prefix + 'OrganizeMeta');
    var eventsEl = document.getElementById(prefix + 'OrganizeEvents');
    var stage = data.stage || data.status || 'idle';
    var message = data.message || (data.running ? '整理中...' : '等待开始');
    var pct = 0;
    if (data.total_chunks && data.current_chunks) {
        pct = Math.min(95, Math.round((data.current_chunks / data.total_chunks) * 100));
    } else if (data.total_files && data.current_file_index) {
        pct = Math.min(80, Math.round((data.current_file_index / data.total_files) * 80));
    } else if (stage === 'scanning' || stage === 'starting') {
        pct = 8;
    } else if (stage === 'graph' || stage === 'cross_references') {
        pct = 96;
    } else if (stage === 'done') {
        pct = 100;
    } else if (stage === 'error') {
        pct = 100;
    }
    if (stageEl) stageEl.textContent = stage;
    if (fillEl) fillEl.style.width = pct + '%';
    if (msgEl) msgEl.textContent = message;
    if (metaEl) {
        var meta = [];
        if (data.current_file) meta.push(['当前文件', data.current_file]);
        if (data.total_files !== undefined) meta.push(['待整理文件', data.total_files]);
        if (data.skipped_files !== undefined) meta.push(['已跳过', data.skipped_files]);
        if (data.total_chunks !== undefined) meta.push(['分块', (data.current_chunks || 0) + '/' + data.total_chunks]);
        if (data.total_batches !== undefined) meta.push(['LLM批次', (data.current_batch || 0) + '/' + data.total_batches]);
        if (data.started_at) meta.push(['耗时', Math.max(0, Math.round(((data.finished_at || Date.now() / 1000) - data.started_at))) + 's']);
        metaEl.innerHTML = meta.map(function(item) {
            return '<div style="background:var(--muted);border-radius:8px;padding:8px;"><div style="font-size:11px;">' + escapeHtml(item[0]) + '</div><div style="font-weight:700;color:var(--fg);margin-top:2px;word-break:break-all;">' + escapeHtml(String(item[1])) + '</div></div>';
        }).join('');
    }
    if (eventsEl && data.events && data.events.length) {
        eventsEl.innerHTML = data.events.slice(-8).reverse().map(function(ev) {
            return '<div style="padding:4px 0;border-top:1px solid var(--border);">' + escapeHtml(ev.message || ev.stage || '') + '</div>';
        }).join('');
    }
}

function uploadBookKnowledgeDoc() {
    if (!currentBookId) { showToast('请先选择教材', 'error'); return; }
    uploadKnowledgeDoc(currentBookId);
}

function loadKnowledgeGraph(bookId, containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var url = API_BASE + '/api/knowledge/knowledge-graph';
    if (bookId) url += '?book_id=' + encodeURIComponent(bookId);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                renderKnowledgeGraph(container, data.nodes || [], data.edges || []);
            } else {
                container.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--muted-fg);font-size:13px;">加载图谱失败</div>';
            }
        })
        .catch(function(err) {
            container.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--muted-fg);font-size:13px;">加载图谱失败</div>';
        });
}

function renderKnowledgeGraph(container, nodes, edges) {
    if (!nodes.length) {
        container.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--muted-fg);font-size:13px;">暂无知识关联数据，请先进行AI整理</div>';
        return;
    }
    var categoryColors = {
        'concepts': '#6366f1',
        'methods': '#2563eb',
        'entities': '#059669',
        'principles': '#8b5cf6',
        'root': '#64748b'
    };
    var html = '<div style="margin-bottom:12px;font-size:12px;color:var(--muted-fg);">' + nodes.length + ' 个知识节点 · ' + edges.length + ' 条关联</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:16px;">';
    html += '<div style="flex:1;min-width:300px;">';
    html += '<div style="font-size:12px;font-weight:600;margin-bottom:8px;">知识节点</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
    nodes.forEach(function(n) {
        var color = categoryColors[n.category] || '#64748b';
        html += '<div style="display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:12px;font-size:11px;background:' + color + '18;color:' + color + ';border:1px solid ' + color + '30;" title="' + escapeHtml(n.id) + '">';
        html += '<span style="width:6px;height:6px;border-radius:50%;background:' + color + ';"></span>';
        html += escapeHtml(n.label);
        html += '</div>';
    });
    html += '</div></div>';
    if (edges.length > 0) {
        html += '<div style="flex:1;min-width:300px;">';
        html += '<div style="font-size:12px;font-weight:600;margin-bottom:8px;">关联关系</div>';
        html += '<div style="max-height:300px;overflow-y:auto;">';
        edges.forEach(function(e) {
            var sourceNode = nodes.find(function(n) { return n.id === e.source; });
            var targetNode = nodes.find(function(n) { return n.id === e.target; });
            var sourceLabel = sourceNode ? sourceNode.label : e.source;
            var targetLabel = targetNode ? targetNode.label : e.target;
            html += '<div style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:11px;">';
            html += '<span style="color:var(--secondary);font-weight:500;">' + escapeHtml(sourceLabel) + '</span>';
            html += '<span style="color:var(--muted-fg);">→</span>';
            html += '<span style="color:var(--accent);font-weight:500;">' + escapeHtml(targetLabel) + '</span>';
            if (e.label) html += '<span style="color:var(--muted-fg);font-size:10px;">(' + escapeHtml(e.label) + ')</span>';
            html += '</div>';
        });
        html += '</div></div>';
    }
    html += '</div>';
    container.innerHTML = html;
}

function renderKnowledgeGraph(container, nodes, edges) {
    if (!nodes.length) {
        container.innerHTML = '<div class="knowledge-graph-empty">暂无知识关联数据，请先进行 AI 整理</div>';
        return;
    }
    var palette = ['#2563eb', '#059669', '#7c3aed', '#dc2626', '#0891b2', '#ca8a04', '#4f46e5'];
    var width = Math.max(container.clientWidth || 720, 520);
    var height = Math.max(Math.min(width * 0.58, 560), 360);
    var cx = width / 2;
    var cy = height / 2;
    var radius = Math.min(width, height) * 0.34;
    var categoryIndex = {};

    var laidOut = nodes.map(function(n, i) {
        var angle = (Math.PI * 2 * i) / Math.max(nodes.length, 1) - Math.PI / 2;
        var category = n.category || n.type || 'node';
        if (categoryIndex[category] === undefined) categoryIndex[category] = Object.keys(categoryIndex).length;
        return Object.assign({}, n, {
            x: cx + Math.cos(angle) * radius * (0.82 + (i % 3) * 0.08),
            y: cy + Math.sin(angle) * radius * (0.82 + ((i + 1) % 3) * 0.08),
            color: palette[categoryIndex[category] % palette.length],
            degree: 0
        });
    });
    var byId = {};
    laidOut.forEach(function(n) { byId[n.id] = n; });
    edges.forEach(function(e) {
        if (byId[e.source]) byId[e.source].degree += 1;
        if (byId[e.target]) byId[e.target].degree += 1;
    });

    function edgePath(s, t, idx) {
        var mx = (s.x + t.x) / 2;
        var my = (s.y + t.y) / 2;
        var dx = t.x - s.x;
        var dy = t.y - s.y;
        var len = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        var curve = ((idx % 3) - 1) * 34;
        var qx = mx - dy / len * curve;
        var qy = my + dx / len * curve;
        return 'M ' + s.x.toFixed(1) + ' ' + s.y.toFixed(1) + ' Q ' + qx.toFixed(1) + ' ' + qy.toFixed(1) + ' ' + t.x.toFixed(1) + ' ' + t.y.toFixed(1);
    }

    var html = '<div class="knowledge-graph-shell">';
    html += '<div class="knowledge-graph-toolbar"><div><strong>' + nodes.length + '</strong> nodes <span>' + edges.length + ' relations</span></div><div class="knowledge-graph-legend">';
    Object.keys(categoryIndex).forEach(function(cat) {
        html += '<span><i style="background:' + palette[categoryIndex[cat] % palette.length] + '"></i>' + escapeHtml(cat) + '</span>';
    });
    html += '</div></div>';
    html += '<svg class="knowledge-graph-svg" viewBox="0 0 ' + width + ' ' + height + '" role="img">';
    edges.forEach(function(e, idx) {
        var s = byId[e.source];
        var t = byId[e.target];
        if (!s || !t) return;
        html += '<path id="kg-edge-' + idx + '" class="kg-edge" d="' + edgePath(s, t, idx) + '"></path>';
        if (e.label) {
            html += '<text class="kg-edge-label"><textPath href="#kg-edge-' + idx + '" startOffset="50%">' + escapeHtml(e.label) + '</textPath></text>';
        }
    });
    laidOut.forEach(function(n) {
        var r = Math.min(30, 15 + Math.sqrt(n.degree + 1) * 4);
        var label = n.label || n.name || n.id;
        html += '<g class="kg-node" tabindex="0" data-id="' + escapeHtml(n.id) + '">';
        html += '<circle cx="' + n.x.toFixed(1) + '" cy="' + n.y.toFixed(1) + '" r="' + r + '" fill="' + n.color + '"></circle>';
        html += '<text x="' + n.x.toFixed(1) + '" y="' + (n.y + r + 16).toFixed(1) + '">' + escapeHtml(label.length > 18 ? label.slice(0, 17) + '...' : label) + '</text>';
        html += '<title>' + escapeHtml(label + (n.category ? ' / ' + n.category : '')) + '</title>';
        html += '</g>';
    });
    html += '</svg></div>';
    container.innerHTML = html;
}

function loadKnowledgeSources(bookId) {
    let url = '/api/knowledge/sources';
    if (bookId) url += '?book_id=' + encodeURIComponent(bookId);
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                renderKnowledgeSources(data.sources || []);
            }
        })
        .catch(err => console.error('Load knowledge sources error:', err));
}

function loadKnowledgeStatus(bookId) {
    var url = '/api/knowledge/status';
    if (bookId) url += '?book_id=' + encodeURIComponent(bookId);
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                const el = document.getElementById('knowledgeStatusInfo');
                if (el) el.textContent = `共 ${data.total_documents || 0} 个文档，${data.categories ? data.categories.length : 0} 个分类`;
                var docsEl = document.getElementById('knowledgeTotalDocs');
                if (docsEl) docsEl.textContent = data.total_documents || 0;
                var sizeEl = document.getElementById('knowledgeTotalSize');
                if (sizeEl) sizeEl.textContent = formatFileSize(data.total_size || 0);
            }
        })
        .catch(err => console.error('Load knowledge status error:', err));
}

function renderKnowledgeSources(sources) {
    const container = document.getElementById('knowledgeSourceList');
    if (!container) return;
    if (!sources.length) {
        container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--muted-fg);">暂无知识库文档</div>';
        return;
    }
    let html = '';
    sources.forEach(s => {
        html += `<div class="kb-card">
            <div class="kb-header">
                <div class="kb-icon" style="background:#dbeafe;">📄</div>
                <div class="kb-title">${s.name}</div>
                <span class="kb-status ${s.status === 'ready' ? 'ready' : 'processing'}">${s.status === 'ready' ? '已就绪' : '处理中'}</span>
            </div>
            <div class="kb-meta">
                <span>📁 ${s.category}</span>
                <span>📊 ${formatFileSize(s.size)}</span>
                <span>📅 ${s.updated_at || ''}</span>
            </div>
        </div>`;
    });
    container.innerHTML = html;
}

function uploadKnowledgeDoc(bookId, category) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,.doc,.docx,.txt,.md,.csv,.json';
    input.onchange = function() {
        if (!input.files.length) return;
        const formData = new FormData();
        formData.append('file', input.files[0]);
        if (bookId) formData.append('book_id', bookId);
        if (category) formData.append('category', category);
        fetch('/api/knowledge/upload', {method: 'POST', body: formData})
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('文档上传成功');
                    loadKnowledgeSources(bookId || '');
                    loadKnowledgeStatus(bookId || '');
                } else {
                    showToast('上传失败: ' + (data.message || ''), 'error');
                }
            })
            .catch(err => showToast('上传失败: ' + err, 'error'));
    };
    input.click();
}

function loadBookKnowledge() {
    if (!currentBookId) return;
    loadKnowledgeSources(currentBookId);
    loadKnowledgeGraph(currentBookId, 'bookKnowledgeGraphArea');
}

function associateKnowledge() {
    if (!currentBookId) {
        showToast('请先选择教材', 'error');
        return;
    }
    uploadKnowledgeDoc(currentBookId);
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function loadBookPreferences() {
    if (!currentBookId) return;
    fetch(`/api/textbook/${currentBookId}/preferences`)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && data.preferences) {
                fillPreferencesForm(data.preferences);
            }
        })
        .catch(err => console.error('Load preferences error:', err));
}

function fillPreferencesForm(prefs) {
    const fields = {
        'prefChapterWordCount': prefs.chapter_word_count,
        'prefStyle': prefs.style,
        'prefExampleCount': prefs.example_count,
        'prefModel': prefs.model,
        'prefReviewStrictness': prefs.review_strictness
    };
    Object.entries(fields).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) el.value = value;
    });
    var autoOptEl = document.getElementById('prefAutoOptimize');
    if (autoOptEl) autoOptEl.checked = prefs.auto_optimize === true || prefs.auto_optimize === '启用';
}

function saveBookPreferences() {
    if (!currentBookId) return;
    const prefs = {
        chapter_word_count: parseInt(document.getElementById('prefChapterWordCount')?.value || '5000'),
        style: document.getElementById('prefStyle')?.value || '学术',
        example_count: parseInt(document.getElementById('prefExampleCount')?.value || '5'),
        model: document.getElementById('prefModel')?.value || '',
        review_strictness: document.getElementById('prefReviewStrictness')?.value || '标准',
        auto_optimize: document.getElementById('prefAutoOptimize')?.checked ? '启用' : '禁用'
    };
    fetch(`/api/textbook/${currentBookId}/preferences`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(prefs)
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') showToast('教材偏好已保存');
        else showToast('保存失败: ' + (data.message || ''), 'error');
    })
    .catch(err => showToast('保存失败: ' + err, 'error'));
}

function showToast(message, type) {
    type = type || 'success';
    const toast = document.createElement('div');
    toast.style.cssText = `position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:9999;color:white;background:${type === 'error' ? 'var(--danger)' : 'var(--success)'};box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:opacity 0.3s;`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}

function showSimpleModal(title, contentHtml) {
    let modal = document.getElementById('simpleModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'simpleModal';
        modal.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:1000;align-items:center;justify-content:center;';
        modal.innerHTML = `<div style="background:var(--card);border-radius:18px;padding:24px;width:480px;max-width:90vw;max-height:80vh;overflow-y:auto;box-shadow:0 25px 70px rgba(0,0,0,0.35);">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
                <h2 style="margin:0;font-size:16px;" id="simpleModalTitle"></h2>
                <button onclick="document.getElementById('simpleModal').style.display='none'" style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--muted-fg);">&times;</button>
            </div>
            <div id="simpleModalBody"></div>
        </div>`;
        document.body.appendChild(modal);
    }
    document.getElementById('simpleModalTitle').textContent = title;
    document.getElementById('simpleModalBody').innerHTML = contentHtml;
    modal.style.display = 'flex';
}

var currentChapterNum = null;
var chapterEditMode = false;

function loadChapterTree() {
    if (!currentBookId) return;
    fetch('/api/textbook/' + currentBookId + '/outline')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success' && data.outline) {
                renderChapterTree(data.outline);
            }
        })
        .catch(function(err) { console.error('Load chapter tree error:', err); });
}

function renderChapterTree(outlineText) {
    var container = document.getElementById('chapterTree');
    if (!container) return;
    var lines = outlineText.split('\n');
    var html = '';
    var chapterNum = 0;
    lines.forEach(function(line) {
        var match = line.match(/^(#{1,6})\s+(.+)/);
        if (match) {
            var level = match[1].length;
            var title = match[2];
            var isChapterTitle = /第[一二三四五六七八九十\d]+章/.test(title);
            if (isChapterTitle || level === 1) {
                chapterNum++;
                html += '<div class="tree-node" data-chapter="' + chapterNum + '" data-title="' + escapeHtml(title) + '" style="padding:8px 10px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;">';
                html += '<span style="width:20px;height:20px;border-radius:6px;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;">' + chapterNum + '</span>';
                html += escapeHtml(title);
                html += '</div>';
            } else if (level === 2 && chapterNum > 0) {
                html += '<div class="tree-node level-2" data-chapter="' + chapterNum + '" data-section="' + escapeHtml(title) + '" style="margin-left:28px;padding:6px 10px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:500;color:#334155;">';
                html += escapeHtml(title);
                html += '</div>';
            } else if (level === 3 && chapterNum > 0) {
                html += '<div class="tree-node level-3" data-chapter="' + chapterNum + '" data-section="' + escapeHtml(title) + '" style="margin-left:48px;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:400;color:#64748b;">';
                html += escapeHtml(title);
                html += '</div>';
            } else if (level >= 4 && chapterNum > 0) {
                var indent = 28 + (level - 2) * 20;
                html += '<div class="tree-node level-' + level + '" data-chapter="' + chapterNum + '" data-section="' + escapeHtml(title) + '" style="margin-left:' + indent + 'px;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:400;color:#94a3b8;">';
                html += escapeHtml(title);
                html += '</div>';
            }
        }
    });
    if (!html) html = '<div style="text-align:center;padding:20px;color:var(--muted-fg);font-size:12px;">暂无大纲</div>';
    container.innerHTML = html;
    container.onclick = function(e) {
        var node = e.target.closest('.tree-node');
        if (!node) return;
        var chNum = parseInt(node.getAttribute('data-chapter'));
        var section = node.getAttribute('data-section');
        if (section) {
            selectChapterSection(chNum, section);
        } else {
            var title = node.getAttribute('data-title');
            selectChapter(chNum, title);
        }
    };
}

function selectChapter(num, title) {
    currentChapterNum = num;
    chapterEditMode = false;
    document.getElementById('currentChapterTitle').textContent = title || ('第' + num + '章');
    document.getElementById('btnToggleEdit').style.display = '';
    document.getElementById('btnSaveChapter').style.display = 'none';
    loadChapterContent(num, null);
}

function selectChapterSection(num, sectionTitle) {
    currentChapterNum = num;
    chapterEditMode = false;
    document.getElementById('currentChapterTitle').textContent = sectionTitle || ('第' + num + '章');
    document.getElementById('btnToggleEdit').style.display = '';
    document.getElementById('btnSaveChapter').style.display = 'none';
    loadChapterContent(num, sectionTitle);
}

function normalizeHeadingText(text) {
    return (text || '')
        .replace(/^#+\s*/, '')
        .replace(/^[\d一二三四五六七八九十百千]+[、.．]\s*/, '')
        .replace(/^第[\d一二三四五六七八九十百千]+[章节]\s*/, '')
        .replace(/[：:，,。；;（）()【】\[\]《》<>]/g, ' ')
        .replace(/\s+/g, '')
        .trim()
        .toLowerCase();
}

function _scrollToSection(sectionTitle) {
    if (!sectionTitle) return;
    var area = document.getElementById('chapterContentArea');
    if (!area) return;
    var headings = area.querySelectorAll('h1, h2, h3, h4, h5, h6');
    var normalizedSection = normalizeHeadingText(sectionTitle);
    var bestMatch = null;
    var bestScore = 0;
    for (var i = 0; i < headings.length; i++) {
        var headingText = normalizeHeadingText(headings[i].textContent);
        var score = 0;
        if (headingText === normalizedSection) {
            score = 3;
        } else if (headingText.indexOf(normalizedSection) >= 0) {
            score = 2;
        } else if (normalizedSection.indexOf(headingText) >= 0 && headingText.length > 1) {
            score = 1;
        }
        if (score > bestScore) {
            bestScore = score;
            bestMatch = headings[i];
        }
    }
    if (bestMatch) {
        bestMatch.scrollIntoView({behavior: 'smooth', block: 'start'});
        bestMatch.style.background = 'rgba(37,99,235,0.1)';
        bestMatch.style.borderRadius = '4px';
        bestMatch.style.transition = 'background 0.5s';
        setTimeout(function(el) {
            el.style.background = '';
        }, 2000, bestMatch);
    }
}

function loadChapterContent(num, scrollToSection) {
    if (!currentBookId) return;
    fetch('/api/textbook/' + currentBookId + '/chapters/' + num)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var area = document.getElementById('chapterContentArea');
            if (!area) return;
            if (data.status === 'success' && data.content) {
                document.getElementById('currentChapterStatus').textContent = '已编写';
                document.getElementById('currentChapterStatus').style.color = 'var(--success)';
                var content = data.content;
                content = content.replace(/!\[([^\]]*)\]\((?!https?:\/\/)(?!\/api\/)([^)]+)\)/g, '![$1](/api/textbook/' + currentBookId + '/assets/$2)');
                var rendered = renderMarkdown(content);
                area.innerHTML = '<div class="markdown-preview">' + (rendered || escapeHtml(content).replace(/\n/g, '<br>')) + '</div>';
                if (scrollToSection) {
                    setTimeout(function() { _scrollToSection(scrollToSection); }, 100);
                }
            } else {
                document.getElementById('currentChapterStatus').textContent = '未编写';
                document.getElementById('currentChapterStatus').style.color = 'var(--muted-fg)';
                area.innerHTML = '<div style="text-align:center;padding:60px 20px;color:var(--muted-fg);"><div style="font-size:48px;margin-bottom:12px;">📝</div><div style="font-size:14px;">该章节尚未编写</div><div style="font-size:12px;margin-top:8px;">点击"一键编写"或通过AI对话让智能体编写此章节</div></div>';
            }
        })
        .catch(function(err) {
            console.error('Load chapter error:', err);
        });
}

function toggleChapterEditMode() {
    chapterEditMode = !chapterEditMode;
    var btn = document.getElementById('btnToggleEdit');
    var saveBtn = document.getElementById('btnSaveChapter');
    var area = document.getElementById('chapterContentArea');
    if (chapterEditMode) {
        btn.innerHTML = '<i class="fas fa-eye"></i> 预览';
        saveBtn.style.display = '';
        var content = '';
        fetch('/api/textbook/' + currentBookId + '/chapters/' + currentChapterNum)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                content = (data.status === 'success' && data.content) ? data.content : '';
                area.innerHTML = '<textarea id="chapterEditor" style="width:100%;min-height:400px;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;font-family:var(--font-mono);resize:vertical;background:var(--card);color:var(--fg);box-sizing:border-box;">' + content.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</textarea>';
            });
    } else {
        btn.innerHTML = '<i class="fas fa-edit"></i> 编辑';
        saveBtn.style.display = 'none';
        loadChapterContent(currentChapterNum, null);
    }
}

function saveChapterEdit() {
    if (!currentBookId || !currentChapterNum) return;
    var editor = document.getElementById('chapterEditor');
    if (!editor) return;
    var content = editor.value;
    fetch('/api/textbook/' + currentBookId + '/chapters/' + currentChapterNum, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content: content})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'success') {
            showToast('章节已保存');
            chapterEditMode = false;
            document.getElementById('btnToggleEdit').innerHTML = '<i class="fas fa-edit"></i> 编辑';
            document.getElementById('btnSaveChapter').style.display = 'none';
            loadChapterContent(currentChapterNum, null);
        } else {
            showToast('保存失败: ' + (data.message || ''), 'error');
        }
    })
    .catch(function(err) { showToast('保存失败: ' + err, 'error'); });
}

var exportFormat = 'word';

function populateExportChapterDropdown() {
    var dropdown = document.getElementById('exportChapterNum');
    if (!dropdown || !currentBookId) return;
    dropdown.innerHTML = '<option value="">加载中...</option>';
    fetch('/api/textbook/' + currentBookId + '/outline')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            dropdown.innerHTML = '';
            if (data.status === 'success' && data.outline) {
                var lines = data.outline.split('\n');
                var chapterNum = 0;
                for (var i = 0; i < lines.length; i++) {
                    var match = lines[i].match(/^(#{1,6})\s+(.+)/);
                    if (match) {
                        var level = match[1].length;
                        var title = match[2];
                        var isChapterTitle = /第[一二三四五六七八九十\d]+章/.test(title);
                        if (isChapterTitle || level === 1) {
                            chapterNum++;
                            var opt = document.createElement('option');
                            opt.value = chapterNum;
                            opt.textContent = '第' + chapterNum + '章 ' + title;
                            dropdown.appendChild(opt);
                        }
                    }
                }
            }
            if (!dropdown.innerHTML) {
                dropdown.innerHTML = '<option value="">暂无章节</option>';
            }
        })
        .catch(function(err) {
            dropdown.innerHTML = '<option value="">加载失败</option>';
        });
}

function selectExportFormat(format) {
    exportFormat = format;
    var wordCard = document.getElementById('exportFormatWord');
    var pdfCard = document.getElementById('exportFormatPdf');
    if (format === 'word') {
        wordCard.style.border = '2px solid var(--primary)';
        wordCard.style.background = 'rgba(37,99,235,0.04)';
        pdfCard.style.border = '1px solid var(--border)';
        pdfCard.style.background = '';
    } else {
        pdfCard.style.border = '2px solid var(--primary)';
        pdfCard.style.background = 'rgba(37,99,235,0.04)';
        wordCard.style.border = '1px solid var(--border)';
        wordCard.style.background = '';
    }
}

function startExport() {
    if (!currentBookId) { showToast('请先选择教材', 'error'); return; }
    var range = document.getElementById('exportRange').value;
    var format = exportFormat;
    var progressEl = document.getElementById('exportProgress');
    var fillEl = document.getElementById('exportProgressFill');
    var textEl = document.getElementById('exportProgressText');
    progressEl.style.display = '';

    var url = '/api/textbook/' + currentBookId + '/export?format=' + encodeURIComponent(format) + '&range=' + encodeURIComponent(range) + '&template=' + encodeURIComponent(selectedTemplate || 'academic');
    if (range === 'chapter') {
        var chNum = document.getElementById('exportChapterNum').value;
        url += '&chapter=' + encodeURIComponent(chNum || '');
    }
    fillEl.style.width = '20%';
    textEl.textContent = 'Preparing export...';
    fetch(API_BASE + url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success' && data.file_url) {
                fillEl.style.width = '100%';
                textEl.textContent = 'Export completed';
                window.open(data.file_url, '_blank');
                setTimeout(function() { progressEl.style.display = 'none'; }, 3000);
            } else {
                fillEl.style.width = '0%';
                textEl.textContent = data.message || 'Export failed';
                showToast(textEl.textContent, 'error');
            }
        })
        .catch(function(err) {
            fillEl.style.width = '0%';
            textEl.textContent = 'Export failed: ' + err.message;
            showToast(textEl.textContent, 'error');
        });
}

var chatModalSessionId = null;

function openChatModal(prefill) {
    var modal = document.getElementById('chatModal');
    if (!modal) return;
    modal.style.display = 'flex';
    if (!chatModalSessionId) {
        chatModalSessionId = chatSessionId || ('chat_' + Date.now());
    }
    loadChatModalHistory();
    if (prefill) {
        document.getElementById('chatModalInput').value = prefill;
    }
    document.getElementById('chatModalInput').focus();
}

function closeChatModal() {
    var modal = document.getElementById('chatModal');
    if (modal) modal.style.display = 'none';
}

function loadChatModalHistory() {
    if (!chatModalSessionId) return;
    fetch('/api/chat/history/' + chatModalSessionId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success' && data.messages) {
                renderChatModalMessages(data.messages);
            }
        })
        .catch(function(err) { console.error('Load chat history error:', err); });
}

function renderChatModalMessages(messages) {
    var container = document.getElementById('chatModalMessages');
    if (!container) return;
    var html = '';
    messages.forEach(function(msg) {
        if (msg.role === 'user') {
            html += '<div style="display:flex;justify-content:flex-end;margin-bottom:12px;"><div style="background:var(--primary);color:white;padding:10px 14px;border-radius:12px 12px 4px 12px;max-width:80%;font-size:13px;line-height:1.6;">' + escapeHtml(msg.content) + '</div></div>';
        } else {
            html += '<div style="display:flex;justify-content:flex-start;margin-bottom:12px;"><div style="background:var(--muted);padding:10px 14px;border-radius:12px 12px 12px 4px;max-width:80%;font-size:13px;line-height:1.6;">' + escapeHtml(msg.content) + '</div></div>';
        }
    });
    container.innerHTML = html || '<div style="text-align:center;padding:40px;color:var(--muted-fg);font-size:13px;">开始与AI助手对话</div>';
    container.scrollTop = container.scrollHeight;
}

function sendChatModalMessage() {
    var input = document.getElementById('chatModalInput');
    if (!input) return;
    var message = input.value.trim();
    if (!message) return;
    input.value = '';

    appendChatModalMessage('user', message);
    saveChatMessage(chatModalSessionId, 'user', message);

    setChatSending(true);

    fetch('/message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            session_id: chatModalSessionId,
            message: message,
            stream: true,
            book_id: currentBookId || ''
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'success' && data.stream) {
            startModalSSE(data.request_id);
        } else if (data.response) {
            appendChatModalMessage('assistant', data.response);
            saveChatMessage(chatModalSessionId, 'assistant', data.response);
            setChatSending(false);
        } else {
            appendChatModalMessage('assistant', '发送失败: ' + (data.message || '未知错误'));
            setChatSending(false);
        }
        refreshBookDetail();
    })
    .catch(function(err) {
        appendChatModalMessage('assistant', '请求失败: ' + err.message);
        setChatSending(false);
    });
}

function startModalSSE(requestId) {
    var container = document.getElementById('chatModalMessages');
    if (!container) return;

    var assistantDiv = document.createElement('div');
    assistantDiv.style.cssText = 'display:flex;justify-content:flex-start;margin-bottom:12px;';
    var bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'chat-modal-bubble';
    bubbleDiv.style.cssText = 'background:var(--muted);padding:10px 14px;border-radius:12px 12px 12px 4px;max-width:80%;font-size:13px;line-height:1.6;';
    bubbleDiv.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
    assistantDiv.appendChild(bubbleDiv);
    container.appendChild(assistantDiv);
    container.scrollTop = container.scrollHeight;

    var accumulatedText = '';
    var eventSource = new EventSource('/stream?request_id=' + requestId);

    eventSource.onmessage = function(event) {
        try {
            var d = JSON.parse(event.data);
            if (d.type === 'delta') {
                accumulatedText += d.content;
                var rendered = renderMarkdown(accumulatedText);
                bubbleDiv.innerHTML = rendered || ('<p>' + escapeHtml(accumulatedText) + '</p>');
                container.scrollTop = container.scrollHeight;
            } else if (d.type === 'done') {
                if (accumulatedText) {
                    bubbleDiv.innerHTML = renderMarkdown(accumulatedText);
                } else if (d.content) {
                    bubbleDiv.innerHTML = renderMarkdown(d.content);
                    accumulatedText = d.content;
                }
                saveChatMessage(chatModalSessionId, 'assistant', accumulatedText || d.content || '');
                eventSource.close();
                setChatSending(false);
                refreshBookDetail();
            } else if (d.type === 'error') {
                bubbleDiv.innerHTML += '<div style="color:var(--destructive);margin-top:8px;">[错误: ' + escapeHtml(d.message || '未知错误') + ']</div>';
                eventSource.close();
                setChatSending(false);
            } else if (d.type === 'reasoning') {
                var reasoningText = escapeHtml(d.content || '');
                bubbleDiv.innerHTML = '<div class="agent-reasoning">' + reasoningText + '</div>' + (accumulatedText ? renderMarkdown(accumulatedText) : '');
                container.scrollTop = container.scrollHeight;
            } else if (d.type === 'tool_start') {
                var toolName = d.tool || 'tool';
                bubbleDiv.innerHTML += '<div style="background:rgba(0,0,0,0.04);padding:6px 10px;border-radius:6px;margin:4px 0;font-size:12px;"><span style="color:var(--primary);">&#9654;</span> ' + escapeHtml(toolName) + ' <span style="color:var(--muted-fg);">执行中...</span></div>';
                container.scrollTop = container.scrollHeight;
            } else if (d.type === 'tool_end') {
                var endTool = d.tool || 'tool';
                var endStatus = d.status || 'success';
                bubbleDiv.innerHTML += '<div style="background:rgba(0,0,0,0.04);padding:6px 10px;border-radius:6px;margin:4px 0;font-size:12px;"><span style="color:' + (endStatus === 'success' ? 'var(--success)' : 'var(--destructive)') + ';">' + (endStatus === 'success' ? '&#10003;' : '&#10007;') + '</span> ' + escapeHtml(endTool) + ' <span style="color:var(--muted-fg);">' + (endStatus === 'success' ? '完成' : '失败') + '</span></div>';
                container.scrollTop = container.scrollHeight;
            }
        } catch (e) {
        }
    };

    eventSource.onerror = function() {
        if (accumulatedText) {
            bubbleDiv.innerHTML = renderMarkdown(accumulatedText);
            saveChatMessage(chatModalSessionId, 'assistant', accumulatedText);
        }
        eventSource.close();
        setChatSending(false);
    };
}

function appendChatModalMessage(role, content) {
    var container = document.getElementById('chatModalMessages');
    if (!container) return;
    var placeholder = container.querySelector('[style*="text-align:center"]');
    if (placeholder) placeholder.remove();

    var div = document.createElement('div');
    if (role === 'user') {
        div.style.cssText = 'display:flex;justify-content:flex-end;margin-bottom:12px;';
        div.innerHTML = '<div style="background:var(--primary);color:white;padding:10px 14px;border-radius:12px 12px 4px 12px;max-width:80%;font-size:13px;line-height:1.6;">' + escapeHtml(content) + '</div>';
    } else {
        div.style.cssText = 'display:flex;justify-content:flex-start;margin-bottom:12px;';
        div.innerHTML = '<div style="background:var(--muted);padding:10px 14px;border-radius:12px 12px 12px 4px;max-width:80%;font-size:13px;line-height:1.6;">' + escapeHtml(content) + '</div>';
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function saveChatMessage(sessionId, role, content) {
    fetch('/api/chat/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: sessionId, role: role, content: content})
    }).catch(function(err) { console.error('Save chat error:', err); });
}

function refreshBookDetail() {
    if (!currentBookId) return;
    var activeTab = document.querySelector('.tab.active');
    if (activeTab) {
        var tabName = activeTab.getAttribute('data-tab');
        if (tabName === 'outline-edit') loadOutlineForEditor();
        if (tabName === 'chapter-preview') { loadChapterTree(); if (currentChapterNum) loadChapterContent(currentChapterNum, null); }
    }
}

function loadChatHistory() {
    if (!chatSessionId) return;
    if (currentEventSource || activeChatRequestId) {
        return;
    }
    fetch('/api/chat/history/' + chatSessionId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            chatHistoryLoaded = true;
            if (data.status === 'success' && data.messages && data.messages.length > 0) {
                var chatMessages = document.getElementById('chatMessages');
                if (chatMessages) {
                    chatMessages.innerHTML = '';
                    data.messages.forEach(function(msg) {
                        appendChatMessage(msg.role, msg.content);
                    });
                }
                // History replay should be passive. Active runs are surfaced by SSE/task events.
            }
        })
        .catch(function(err) { console.error('Load chat history error:', err); });
}

var _slashSkills = [];
var _slashSelectedIdx = -1;
var _slashMenuVisible = false;

function loadSlashSkills() {
    fetch(API_BASE + '/api/skills').then(function(r) { return r.json(); }).then(function(data) {
        if (data.status === 'success' && data.skills) {
            _slashSkills = data.skills.map(function(s) {
                return {
                    name: s.name || '',
                    trigger: s.trigger_words ? s.trigger_words[0] : s.name,
                    description: s.description || ''
                };
            });
        }
    }).catch(function() {});
}

function showSlashMenu(filter) {
    var menu = document.getElementById('slashMenu');
    if (!menu) return;
    var input = document.getElementById('chatInput');
    if (!input) return;
    var text = input.value;
    var slashIdx = text.lastIndexOf('/');
    if (slashIdx < 0) {
        hideSlashMenu();
        return;
    }
    var query = text.substring(slashIdx + 1).toLowerCase();
    if (filter !== undefined) query = filter.toLowerCase();
    var filtered = _slashSkills.filter(function(s) {
        return !query || s.name.toLowerCase().indexOf(query) >= 0 || (s.trigger && s.trigger.toLowerCase().indexOf(query) >= 0);
    });
    if (filtered.length === 0) {
        hideSlashMenu();
        return;
    }
    _slashSelectedIdx = 0;
    _slashMenuVisible = true;
    var html = '';
    for (var i = 0; i < filtered.length; i++) {
        var s = filtered[i];
        var isSelected = i === _slashSelectedIdx;
        html += '<div class="slash-menu-item' + (isSelected ? ' selected' : '') + '" data-idx="' + i + '" onmousedown="selectSlashSkill(' + i + ', event)">';
        html += '<span class="slash-icon">⚡</span>';
        html += '<span class="slash-name">/' + escapeHtml(s.trigger || s.name) + '</span>';
        html += '<span class="slash-desc">' + escapeHtml(s.description) + '</span>';
        html += '</div>';
    }
    menu.innerHTML = html;
    menu.classList.remove('hidden');
}

function hideSlashMenu() {
    var menu = document.getElementById('slashMenu');
    if (menu) menu.classList.add('hidden');
    _slashMenuVisible = false;
    _slashSelectedIdx = -1;
}

function selectSlashSkill(idx, event) {
    if (event) event.preventDefault();
    var input = document.getElementById('chatInput');
    if (!input) return;
    var text = input.value;
    var slashIdx = text.lastIndexOf('/');
    var filtered = _slashSkills.filter(function(s) {
        var query = text.substring(slashIdx + 1).toLowerCase();
        return !query || s.name.toLowerCase().indexOf(query) >= 0 || (s.trigger && s.trigger.toLowerCase().indexOf(query) >= 0);
    });
    if (idx >= 0 && idx < filtered.length) {
        var skill = filtered[idx];
        input.value = '/' + (skill.trigger || skill.name) + ' ';
        input.focus();
    }
    hideSlashMenu();
}

document.addEventListener('DOMContentLoaded', function() {
    loadTextbooks();
    loadSlashSkills();

    var chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', function(e) {
            if (_slashMenuVisible) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    _slashSelectedIdx = Math.min(_slashSelectedIdx + 1, _slashSkills.length - 1);
                    showSlashMenu();
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    _slashSelectedIdx = Math.max(_slashSelectedIdx - 1, 0);
                    showSlashMenu();
                    return;
                }
                if (e.key === 'Enter' || e.key === 'Tab') {
                    e.preventDefault();
                    selectSlashSkill(_slashSelectedIdx);
                    return;
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    hideSlashMenu();
                    return;
                }
            }
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });
    }

    var chatFileInput = document.getElementById('chatFileInput');
    if (chatFileInput) {
        chatFileInput.addEventListener('change', function(e) {
            if (e.target.files.length > 0) {
                handleFileSelect(e.target.files);
                e.target.value = '';
            }
        });
    }

    if (chatInput) {
        chatInput.addEventListener('paste', function(e) {
            var items = e.clipboardData && e.clipboardData.items;
            if (!items) return;
            var hasFile = false;
            for (var i = 0; i < items.length; i++) {
                if (items[i].kind === 'file') {
                    hasFile = true;
                    var file = items[i].getAsFile();
                    uploadFile(file);
                }
            }
            if (hasFile) {
                e.preventDefault();
            }
        });
    }

    var chatInputEl = document.getElementById('chatInput');
    if (chatInputEl) {
        chatInputEl.addEventListener('input', function() {
            var text = this.value;
            var cursorPos = this.selectionStart;
            var textBeforeCursor = text.substring(0, cursorPos);
            var lastSlash = textBeforeCursor.lastIndexOf('/');
            if (lastSlash >= 0 && (lastSlash === 0 || textBeforeCursor[lastSlash - 1] === ' ' || textBeforeCursor[lastSlash - 1] === '\n')) {
                showSlashMenu();
            } else {
                hideSlashMenu();
            }
        });
    }

    document.addEventListener('click', function(e) {
        var modelMenu = document.getElementById('modelMenu');
        if (modelMenu && !modelMenu.classList.contains('hidden')) {
            var btn = document.getElementById('chatModelBtn');
            if (!btn || !btn.contains(e.target)) {
                modelMenu.classList.add('hidden');
            }
        }
        var attachMenu = document.getElementById('attachMenu');
        if (attachMenu && !attachMenu.classList.contains('hidden')) {
            var attachBtn = document.getElementById('chatAttachBtn');
            if (!attachBtn || !attachBtn.contains(e.target)) {
                attachMenu.classList.add('hidden');
            }
        }
        var slashMenu = document.getElementById('slashMenu');
        if (slashMenu && !slashMenu.classList.contains('hidden')) {
            var chatInputEl = document.getElementById('chatInput');
            if (!chatInputEl || !chatInputEl.contains(e.target)) {
                hideSlashMenu();
            }
        }
    });

    document.getElementById('createModal').addEventListener('click', function(e) {
        if (e.target === this) hideCreateModal();
    });

    const outlineEditor = document.getElementById('outlineEditor');
    if (outlineEditor) {
        outlineEditor.addEventListener('input', function() {
            renderOutlinePreview(this.value);
        });
    }

    var rangeSelect = document.getElementById('exportRange');
    if (rangeSelect) {
        rangeSelect.addEventListener('change', function() {
            var chSelect = document.getElementById('exportChapterSelect');
            if (chSelect) chSelect.style.display = this.value === 'chapter' ? '' : 'none';
            if (this.value === 'chapter') {
                populateExportChapterDropdown();
            }
        });
    }
});

var _currentModelName = '';

function toggleModelMenu(event) {
    event.stopPropagation();
    var menu = document.getElementById('modelMenu');
    if (!menu) return;
    if (menu.classList.contains('hidden')) {
        loadModelMenu();
        menu.classList.remove('hidden');
    } else {
        menu.classList.add('hidden');
    }
}

function loadModelMenu() {
    var menu = document.getElementById('modelMenu');
    if (!menu) return;
    fetch(API_BASE + '/config').then(function(r) { return r.json(); }).then(function(data) {
        if (data.status !== 'success') return;
        _currentModelName = data.model || '';
        var chatModels = data.ai_chat_models || [];
        var activeId = data.active_chat_model_id || '';
        var html = '';
        if (chatModels.length) {
            html += '<div class="model-menu-provider">AI 对话模型</div>';
        }
        for (var i = 0; i < chatModels.length; i++) {
            var item = chatModels[i];
            var isActive = item.id === activeId;
            var label = (item.name || item.model || '未命名模型') + ' · ' + (((data.providers || {})[item.provider] || {}).label || item.provider || '自定义');
            html += '<div class="model-menu-item' + (isActive ? ' active' : '') + '" onclick="event.stopPropagation();switchModelById(&quot;' + escapeHtml(item.id) + '&quot;)">';
            html += '<span>' + escapeHtml(label) + '</span>';
            if (isActive) html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--secondary)" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>';
            html += '</div>';
        }
        menu.innerHTML = html || '<div style="padding:12px;color:var(--muted-fg);font-size:12px;">暂无已配置的AI对话模型<br><span style="font-size:11px;">请在系统设置中添加模型</span></div>';
    }).catch(function(e) {
        menu.innerHTML = '<div style="padding:12px;color:var(--muted-fg);font-size:12px;">加载失败</div>';
    });
}

function switchModelById(modelId) {
    var menu = document.getElementById('modelMenu');
    if (menu) menu.classList.add('hidden');
    var updates = {active_chat_model_id: modelId};
    fetch(API_BASE + '/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({updates: updates})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.status === 'success') {
            var applied = data.applied || {};
            _currentModelName = applied.model || _currentModelName;
            showToast('已切换到 ' + (_currentModelName || '所选模型'));
            var btn = document.getElementById('chatModelBtn');
            if (btn) btn.title = '当前: ' + _currentModelName;
        } else {
            showToast('切换失败: ' + (data.message || ''), 'error');
        }
    }).catch(function(e) {
        showToast('切换失败: ' + e.message, 'error');
    });
    return false;
}

function switchModel(modelName, providerId) {
    return switchModelById(modelName || providerId);
}

function copyMessage(btn) {
    var msgDiv = btn.closest('.chat-msg');
    var bubble = msgDiv.querySelector('.chat-bubble');
    if (bubble) {
        navigator.clipboard.writeText(bubble.textContent).then(function() {
            showToast('已复制');
        });
    }
}

function deleteMessage(btn) {
    var msgDiv = btn.closest('.chat-msg');
    if (msgDiv && confirm('确定删除此消息？')) {
        msgDiv.remove();
    }
}

function rollbackMessage(btn) {
    var msgDiv = btn.closest('.chat-msg');
    if (!msgDiv) return;
    if (!confirm('确定回退到本轮对话前？将删除此消息及之后的所有消息。')) return;
    var bubble = msgDiv.querySelector('.chat-bubble');
    var rolledBackText = bubble ? bubble.textContent : '';
    var container = msgDiv.parentNode;
    var found = false;
    var toRemove = [];
    for (var i = 0; i < container.children.length; i++) {
        if (container.children[i] === msgDiv) found = true;
        if (found) toRemove.push(container.children[i]);
    }
    toRemove.forEach(function(el) { el.remove(); });
    if (rolledBackText) {
        var chatInput = document.getElementById('chatInput');
        if (chatInput) chatInput.value = rolledBackText;
    }
    showToast('已回退，输入栏已恢复消息内容');
}

function copyAssistantMessage(btn) {
    var msgDiv = btn.closest('.chat-msg');
    var bubble = msgDiv.querySelector('.chat-bubble');
    if (bubble) {
        navigator.clipboard.writeText(bubble.textContent).then(function() {
            showToast('已复制全部内容');
        });
    }
}

function refreshAssistantMessage(btn) {
    var msgDiv = btn.closest('.chat-msg');
    var prevMsg = msgDiv.previousElementSibling;
    if (!prevMsg || !prevMsg.classList.contains('user')) {
        showToast('无法刷新：找不到对应的用户消息', 'error');
        return;
    }
    var userBubble = prevMsg.querySelector('.chat-bubble');
    if (!userBubble) return;
    var userMessage = userBubble.textContent;
    var assistantBubble = msgDiv.querySelector('.chat-bubble');
    if (assistantBubble) {
        assistantBubble.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div> <span style="color:var(--muted-fg);">重新生成中...</span>';
    }
    setChatSending(true);
    fetch('/message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            session_id: chatSessionId,
            message: userMessage,
            stream: true,
            book_id: currentBookId || ''
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'success' && data.stream) {
            var newAssistantEl = appendChatMessage('assistant', '');
            var newBubbleEl = newAssistantEl.querySelector('.chat-bubble');
            msgDiv.remove();
            startChatSSE(data.request_id, newAssistantEl, newBubbleEl);
        } else {
            if (assistantBubble) assistantBubble.innerHTML = renderMarkdown(data.response || '重新生成失败');
            setChatSending(false);
        }
    })
    .catch(function(err) {
        if (assistantBubble) assistantBubble.innerHTML = '重新生成失败: ' + err.message;
        setChatSending(false);
    });
}
