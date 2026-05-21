// Core navigation, textbook workspace, pipeline, and document export.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
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
        if (window.refreshActiveChatStream) window.refreshActiveChatStream();
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
    if (d.type === 'run_event') {
        data = d.data || {};
        if (data.payload && data.payload.book_id) bookId = data.payload.book_id;
    }
    var status = data.status || d.type;
    var progress = data.progress;
    if (typeof progress === 'number') progress = Math.round(progress * 100);
    var phase = data.current_phase || data.phase || '';
    var message = '';
    if (d.type === 'run_event') {
        message = 'Run: ' + (data.message || data.type || 'event') + (data.phase ? ' / ' + data.phase : '') + (data.status ? ' / ' + data.status : '');
    } else if (d.type === 'pipeline_status') {
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
