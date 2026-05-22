// Book preferences, chapter preview, export panel, modal chat, init, model menu, message actions.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
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
    const ratio = prefs.content_ratio || (prefs.writing_spec && prefs.writing_spec.content_ratio) || {};
    const fields = {
        'prefChapterWordCount': prefs.chapter_word_count,
        'prefStyle': prefs.style,
        'prefExampleCount': prefs.example_count,
        'prefModel': prefs.model,
        'prefReviewStrictness': prefs.review_strictness,
        'prefLearningOrientation': prefs.learning_orientation || (prefs.writing_spec && prefs.writing_spec.learning_orientation),
        'prefRatioTheory': ratio.theory,
        'prefRatioCase': ratio.case,
        'prefRatioProcedure': ratio.procedure,
        'prefRatioPractice': ratio.practice,
        'prefRatioCode': ratio.code,
        'prefMinVisualAssets': prefs.min_visual_assets || (prefs.writing_spec && prefs.writing_spec.visual_policy && prefs.writing_spec.visual_policy.min_assets_per_chapter),
        'prefAdditionalNotes': prefs.additional_notes || (prefs.writing_spec && prefs.writing_spec.additional_notes)
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
    const contentRatio = {
        theory: parseInt(document.getElementById('prefRatioTheory')?.value || '25'),
        case: parseInt(document.getElementById('prefRatioCase')?.value || '25'),
        procedure: parseInt(document.getElementById('prefRatioProcedure')?.value || '20'),
        practice: parseInt(document.getElementById('prefRatioPractice')?.value || '20'),
        code: parseInt(document.getElementById('prefRatioCode')?.value || '10')
    };
    const prefs = {
        chapter_word_count: parseInt(document.getElementById('prefChapterWordCount')?.value || '5000'),
        style: document.getElementById('prefStyle')?.value || '学术',
        example_count: parseInt(document.getElementById('prefExampleCount')?.value || '5'),
        model: document.getElementById('prefModel')?.value || '',
        review_strictness: document.getElementById('prefReviewStrictness')?.value || '标准',
        auto_optimize: document.getElementById('prefAutoOptimize')?.checked ? '启用' : '禁用',
        learning_orientation: document.getElementById('prefLearningOrientation')?.value || '应用型',
        content_ratio: contentRatio,
        min_visual_assets: parseInt(document.getElementById('prefMinVisualAssets')?.value || '1'),
        additional_notes: document.getElementById('prefAdditionalNotes')?.value || ''
    };
    fetch(`/api/textbook/${currentBookId}/preferences`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(prefs)
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showToast('教材偏好已保存，并已纳入本教材全局 WritingSpec');
            loadTextbooks();
        }
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

function parseChapterOrdinal(raw) {
    raw = String(raw || '').trim();
    if (/^\d+$/.test(raw)) return parseInt(raw, 10);
    var digits = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9};
    if (raw === '十') return 10;
    if (raw.indexOf('十') >= 0) {
        var parts = raw.split('十');
        var tens = parts[0] ? digits[parts[0]] : 1;
        var ones = parts[1] ? digits[parts[1]] : 0;
        return (tens || 0) * 10 + (ones || 0);
    }
    return digits[raw] || null;
}

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
            var chapterMatch = title.match(/^第\s*(\d{1,3}|[一二三四五六七八九十]{1,3})\s*章/);
            if (chapterMatch) {
                var parsedChapter = parseChapterOrdinal(chapterMatch[1]);
                chapterNum = parsedChapter || (chapterNum + 1);
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
        btn.innerHTML = '<i class="fas fa-times"></i> 取消';
        saveBtn.style.display = '';
        var content = '';
        fetch('/api/textbook/' + currentBookId + '/chapters/' + currentChapterNum)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                content = (data.status === 'success' && data.content) ? data.content : '';
                area.innerHTML =
                    '<div class="chapter-editor-shell">' +
                        '<div class="chapter-editor-actions">' +
                            '<div class="chapter-editor-status">正在编辑，修改后请点击保存</div>' +
                            '<div class="chapter-editor-buttons">' +
                                '<button class="pipeline-btn" type="button" onclick="cancelChapterEdit()"><i class="fas fa-times"></i> 取消</button>' +
                                '<button class="pipeline-btn primary" type="button" onclick="saveChapterEdit()"><i class="fas fa-save"></i> 保存</button>' +
                            '</div>' +
                        '</div>' +
                        '<textarea id="chapterEditor" class="chapter-editor-textarea">' + escapeHtml(content) + '</textarea>' +
                    '</div>';
            });
    } else {
        cancelChapterEdit();
    }
}

function cancelChapterEdit() {
    chapterEditMode = false;
    var btn = document.getElementById('btnToggleEdit');
    var saveBtn = document.getElementById('btnSaveChapter');
    if (btn) btn.innerHTML = '<i class="fas fa-edit"></i> 编辑';
    if (saveBtn) saveBtn.style.display = 'none';
    if (currentChapterNum) loadChapterContent(currentChapterNum, null);
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
    fetch('/api/textbook/' + currentBookId + '/chapters')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            dropdown.innerHTML = '';
            if (data.status === 'success' && Array.isArray(data.chapters)) {
                data.chapters
                    .filter(function(ch) {
                        return Number.isFinite(Number(ch.chapter_num)) && ch.status === 'completed';
                    })
                    .sort(function(a, b) { return Number(a.chapter_num) - Number(b.chapter_num); })
                    .forEach(function(ch) {
                        var num = Number(ch.chapter_num);
                        var opt = document.createElement('option');
                        opt.value = String(num);
                        opt.textContent = '第' + num + '章 ' + (ch.title || ch.file || '');
                        dropdown.appendChild(opt);
                    });
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
