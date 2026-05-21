// AI chat terminal stream, attachments, and sandbox helpers.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
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
    var frozenHtml = '';
    var thinkingNodes = [];
    var toolCalls = [];
    var commandRuns = [];
    var runEvents = [];
    var savedAssistantText = false;
    var eventSeq = 0;
    var streamStartedAt = Date.now();
    var flushTimer = null;
    var flushRaf = null;
    var lastFlushAt = 0;
    var streamClosed = false;

    var eventSource = new EventSource(API_BASE + '/stream?request_id=' + requestId);
    currentEventSource = eventSource;
    activeChatRequestId = requestId;

    function nextId(prefix) {
        eventSeq += 1;
        return prefix + '-' + eventSeq;
    }

    function stringifyBrief(value, maxLen) {
        maxLen = maxLen || 600;
        if (value === undefined || value === null || value === '') return '';
        var text = '';
        if (typeof value === 'string') text = value;
        else {
            try { text = JSON.stringify(value, null, 2); }
            catch (e) { text = String(value); }
        }
        if (text.length > maxLen) text = text.substring(0, maxLen) + '\n...';
        return text;
    }

    function isCommandTool(name, args) {
        var n = (name || '').toLowerCase();
        if (n.indexOf('bash') >= 0 || n.indexOf('shell') >= 0 || n.indexOf('terminal') >= 0 || n.indexOf('command') >= 0) return true;
        if (n.indexOf('execute') >= 0 || n.indexOf('sandbox') >= 0) return true;
        if (args && (args.command || args.cmd || args.code)) return true;
        return false;
    }

    function statusMeta(status) {
        if (status === 'success' || status === 'completed') return {label:'成功', glyph:'✓', cls:'success'};
        if (status === 'error' || status === 'failed' || status === 'failure') return {label:'失败', glyph:'✗', cls:'error'};
        return {label:'执行中', glyph:'⏳', cls:'running'};
    }

    function addThinking(title, detail, state) {
        thinkingNodes.push({id: nextId('think'), title: title || '正在思考', detail: detail || '', state: state || 'running'});
        if (thinkingNodes.length > 80) thinkingNodes = thinkingNodes.slice(-80);
        flushOutput();
    }

    function upsertThinking(key, title, detail, state) {
        var node = thinkingNodes.find(function(item) { return item.key === key; });
        if (!node) {
            node = {id: nextId('think'), key: key, title: title, detail: detail || '', state: state || 'running'};
            thinkingNodes.push(node);
        } else {
            node.title = title || node.title;
            node.detail = detail || node.detail;
            node.state = state || node.state;
        }
        flushOutput();
    }

    function startWorkItem(name, args) {
        var item = {
            id: nextId(isCommandTool(name, args) ? 'cmd' : 'tool'),
            name: name || 'tool',
            args: stringifyBrief(args, 1200),
            result: '',
            status: 'running',
            executionTime: ''
        };
        if (isCommandTool(name, args)) commandRuns.push(item);
        else toolCalls.push(item);
        flushOutput();
        return item;
    }

    function finishWorkItem(name, status, result, executionTime) {
        var list = isCommandTool(name, null) ? commandRuns : toolCalls;
        var item = null;
        for (var i = list.length - 1; i >= 0; i--) {
            if (list[i].name === name && list[i].status === 'running') { item = list[i]; break; }
        }
        if (!item) {
            list = toolCalls.concat(commandRuns);
            for (var j = list.length - 1; j >= 0; j--) {
                if (list[j].name === name && list[j].status === 'running') { item = list[j]; break; }
            }
        }
        if (!item) item = startWorkItem(name, {});
        item.status = status === 'success' ? 'success' : (status || 'success');
        item.result = stringifyBrief(result, 2000);
        item.executionTime = executionTime ? String(executionTime) + 's' : '';
        flushOutput();
    }

    function rememberRunEvent(ev) {
        if (!ev) return;
        runEvents.push({
            id: ev.event_id || nextId('event'),
            type: ev.type || 'event',
            source: ev.source || '',
            phase: ev.phase || '',
            status: ev.status || 'event',
            message: ev.message || ev.type || '运行事件',
            error: ev.error || '',
            timestamp: ev.timestamp || Date.now() / 1000
        });
        if (runEvents.length > 40) runEvents = runEvents.slice(-40);
    }

    function renderThinkingSection() {
        if (!thinkingNodes.length) return '';
        var elapsed = Math.max(1, Math.round((Date.now() - streamStartedAt) / 1000));
        var html = '<details class="agent-section agent-thinking-section">';
        html += '<summary><span class="terminal-step-lead">⏵</span><span><span class="thinking-label">Thinking</span><span class="terminal-muted"> 正在思考</span></span></summary>';
        html += '<div class="thinking-meta-row"><span>耗时 ' + elapsed + 's</span><span>' + thinkingNodes.length + ' 个节点</span></div>';
        html += '<div class="thinking-tree">';
        thinkingNodes.forEach(function(node, index) {
            var meta = statusMeta(node.state);
            html += '<div class="thinking-node ' + meta.cls + '">';
            html += '<div class="thinking-node-dot">' + (index === thinkingNodes.length - 1 ? '└' : '├') + '</div>';
            html += '<div class="thinking-node-body"><div class="thinking-node-title">' + escapeHtml(node.title || '正在思考') + '</div>';
            if (node.detail) html += '<div class="thinking-node-detail">' + escapeHtml(node.detail) + '</div>';
            html += '</div></div>';
        });
        html += '</div></details>';
        return html;
    }

    function renderWorkCard(item, type) {
        var meta = statusMeta(item.status);
        var label = type === 'command' ? 'Command' : 'Tool';
        var title = type === 'command' ? (item.name || 'command') : item.name;
        var sub = item.executionTime ? meta.label + ' · ' + item.executionTime : meta.label;
        var collapsedTitle = type === 'command' ? '正在执行命令' : '正在调用工具';
        var html = '<details class="agent-work-card ' + meta.cls + '">';
        html += '<summary class="agent-work-card-head"><span class="terminal-step-lead">⏵</span><span class="work-status-icon">' + meta.glyph + '</span>';
        html += '<div class="work-title-wrap"><div class="work-title">' + collapsedTitle + '</div></div>';
        html += '</summary>';
        html += '<div class="work-detail work-name-detail"><div class="work-detail-static-label">状态</div><pre>' + escapeHtml(sub) + '</pre></div>';
        html += '<div class="work-detail work-name-detail"><div class="work-detail-static-label">' + label + '</div><pre>' + escapeHtml(title || item.name || '') + '</pre></div>';
        if (item.args) {
            html += '<details class="work-detail"><summary>参数</summary><pre>' + escapeHtml(item.args) + '</pre></details>';
        }
        if (item.result) {
            html += '<details class="work-detail"><summary>结果</summary><pre>' + escapeHtml(item.result) + '</pre></details>';
        }
        html += '</details>';
        return html;
    }

    function renderToolSection() {
        if (!toolCalls.length) return '';
        return '<div class="agent-work-card-list">' + toolCalls.map(function(item) { return renderWorkCard(item, 'tool'); }).join('') + '</div>';
    }

    function renderCommandSection() {
        if (!commandRuns.length) return '';
        return '<div class="agent-work-card-list">' + commandRuns.map(function(item) { return renderWorkCard(item, 'command'); }).join('') + '</div>';
    }

    function renderRunEventSection() {
        if (!runEvents.length) return '';
        var latest = runEvents[runEvents.length - 1] || {};
        var counts = {running: 0, completed: 0, error: 0};
        runEvents.forEach(function(ev) {
            if (ev.status === 'error') counts.error += 1;
            else if (ev.status === 'completed') counts.completed += 1;
            else if (ev.status === 'running') counts.running += 1;
        });
        var html = '<details class="agent-section agent-run-section">';
        html += '<summary><span class="terminal-step-lead">⏵</span><span><span class="thinking-label">Run</span><span class="terminal-muted"> · ' + escapeHtml(latest.message || latest.type || 'event') + '</span></span><em>' + runEvents.length + ' events</em></summary>';
        html += '<div class="run-event-stats">';
        html += '<span class="run-stat running">运行中 ' + counts.running + '</span>';
        html += '<span class="run-stat success">成功 ' + counts.completed + '</span>';
        html += '<span class="run-stat error">失败 ' + counts.error + '</span>';
        html += '</div><div class="run-event-list">';
        runEvents.slice(-12).forEach(function(ev) {
            var meta = statusMeta(ev.status);
            var detail = [ev.source, ev.phase, ev.type].filter(Boolean).join(' · ');
            html += '<div class="run-event-row ' + meta.cls + '">';
            html += '<span class="run-event-icon">' + meta.glyph + '</span>';
            html += '<div class="run-event-body"><div class="run-event-title">' + escapeHtml(ev.message || ev.type || 'event') + '</div>';
            html += '<div class="run-event-meta">' + escapeHtml(detail || ev.status || '') + '</div>';
            if (ev.error) html += '<div class="run-event-error">' + escapeHtml(ev.error) + '</div>';
            html += '</div></div>';
        });
        html += '</div></details>';
        return html;
    }

    function renderProcessPanel() {
        var sections = renderThinkingSection() + renderRunEventSection() + renderToolSection() + renderCommandSection();
        if (!sections) return '';
        return '<div class="agent-process-panel">' + sections + '</div>';
    }

    function isNearBottom(el) {
        if (!el) return true;
        return (el.scrollHeight - el.scrollTop - el.clientHeight) < 96;
    }

    function isBubbleVisible() {
        if (!bubbleEl || !bubbleEl.isConnected) return false;
        var page = bubbleEl.closest('.view-page');
        var modal = bubbleEl.closest('.modal-overlay');
        if (modal && modal.style.display !== 'none') return true;
        return !page || page.classList.contains('active');
    }

    function doFlushOutput(force) {
        if (streamClosed || !bubbleEl) return;
        if (!force && !isBubbleVisible()) return;
        var messages = document.getElementById('chatMessages');
        var shouldAutoScroll = isNearBottom(messages);
        var html = frozenHtml + renderProcessPanel();
        if (accumulatedText) {
            var rendered = renderMarkdown(accumulatedText);
            html += rendered || ('<p>' + escapeHtml(accumulatedText) + '</p>');
        }
        if (html) bubbleEl.innerHTML = html;
        if (messages && shouldAutoScroll) messages.scrollTop = messages.scrollHeight;
        lastFlushAt = Date.now();
    }

    function flushOutput(force) {
        if (streamClosed && !force) return;
        if (flushTimer) {
            clearTimeout(flushTimer);
            flushTimer = null;
        }
        if (flushRaf) {
            cancelAnimationFrame(flushRaf);
            flushRaf = null;
        }
        if (force) {
            doFlushOutput(true);
            return;
        }
        var elapsed = Date.now() - lastFlushAt;
        var delay = elapsed > 120 ? 0 : 120 - elapsed;
        flushTimer = setTimeout(function() {
            flushTimer = null;
            flushRaf = requestAnimationFrame(function() {
                flushRaf = null;
                doFlushOutput(false);
            });
        }, delay);
    }

    function freezeCurrentOutput() {
        if (flushTimer) {
            clearTimeout(flushTimer);
            flushTimer = null;
        }
        if (flushRaf) {
            cancelAnimationFrame(flushRaf);
            flushRaf = null;
        }
        var chunk = renderProcessPanel();
        if (accumulatedText) {
            var rendered = renderMarkdown(accumulatedText);
            chunk += rendered || ('<p>' + escapeHtml(accumulatedText) + '</p>');
        }
        if (chunk) frozenHtml += chunk;
        accumulatedText = '';
        thinkingNodes = [];
        toolCalls = [];
        commandRuns = [];
        runEvents = [];
    }

    upsertThinking('agent-working', '等待模型响应', '智能体正在理解任务并准备下一步操作。', 'running');
    window.refreshActiveChatStream = function() {
        if (!streamClosed) flushOutput(true);
    };

    eventSource.onmessage = function(event) {
        try {
            var d = JSON.parse(event.data);
            if (d.type === 'delta') {
                accumulatedText += d.content || '';
                plainTextBuffer += d.content || '';
                flushOutput();
            } else if (d.type === 'done') {
                flushOutput(true);
                if (d.content && !plainTextBuffer) plainTextBuffer = d.content;
                if (accumulatedText || thinkingNodes.length || toolCalls.length || commandRuns.length) {
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
                streamClosed = true;
                if (window.refreshActiveChatStream) window.refreshActiveChatStream = null;
                eventSource.close();
            } else if (d.type === 'error') {
                addThinking('执行出错', d.message || '未知错误', 'error');
                flushOutput(true);
                currentEventSource = null;
                activeChatRequestId = null;
                setChatSending(false);
                streamClosed = true;
                if (window.refreshActiveChatStream) window.refreshActiveChatStream = null;
                eventSource.close();
            } else if (d.type === 'reasoning') {
                addThinking('模型推理', d.content || '', 'running');
            } else if (d.type === 'llm_thinking') {
                var elapsed = d.elapsed_seconds || 0;
                upsertThinking('llm-thinking', '等待模型生成', '已等待 ' + elapsed + ' 秒，后台仍在运行。', 'running');
            } else if (d.type === 'run_event') {
                var ev = d.data || {};
                rememberRunEvent(ev);
                if (ev.message || ev.phase) {
                    var evTitle = ev.message || ev.phase || ev.type || '运行事件';
                    var evDetail = [ev.source, ev.phase, ev.status].filter(Boolean).join(' · ');
                    var evState = ev.status === 'error' ? 'error' : (ev.status === 'completed' ? 'success' : 'running');
                    upsertThinking('run-' + (ev.phase || ev.type || 'event'), evTitle, evDetail, evState);
                }
            } else if (d.type === 'phase_progress') {
                var pd = d.data || {};
                var item = pd.item_label || pd.phase || '处理任务';
                var total = pd.total_items || 0;
                var detail = total ? ('进度 ' + (pd.current_item || 0) + '/' + total) : '';
                upsertThinking('pipeline-progress', item, detail, 'running');
            } else if (d.type === 'tool_start') {
                startWorkItem(d.tool || 'tool', d.arguments || {});
            } else if (d.type === 'tool_end') {
                var endToolName = d.tool || 'tool';
                var endStatus = d.status || 'success';
                var endResult = d.result || '';
                finishWorkItem(endToolName, endStatus, endResult, d.execution_time);
                if (endToolName === 'start_pipeline' && endStatus === 'success') {
                    try {
                        var parsed = typeof endResult === 'string' ? JSON.parse(endResult) : endResult;
                        if (parsed && parsed.book_id) {
                            currentBookId = parsed.book_id;
                            loadTextbooks().then(function() { selectTextbook(parsed.book_id); });
                        }
                    } catch(e) {}
                }
            } else if (d.type === 'message_end') {
                if (d.has_tool_calls) freezeCurrentOutput();
                flushOutput(true);
            } else if (d.type === 'pipeline_start') {
                var bookId = (d.data && d.data.book_id) || currentBookId;
                if (bookId) currentBookId = bookId;
                addThinking('教材管线启动', '7 阶段自动编制流程已启动。', 'running');
            } else if (d.type === 'phase_start') {
                var phaseName = (d.data && d.data.phase) || '';
                var phaseLabel = (d.data && d.data.phase_label) || phaseName || '阶段任务';
                addThinking(phaseLabel, '阶段开始执行。', 'running');
            } else if (d.type === 'phase_complete') {
                var phaseName2 = (d.data && d.data.phase) || '';
                var phaseLabel2 = (d.data && d.data.phase_label) || phaseName2 || '阶段任务';
                addThinking(phaseLabel2, (d.data && d.data.result_summary) || '阶段已完成。', 'success');
            } else if (d.type === 'pipeline_complete') {
                var totalCh = (d.data && d.data.total_chapters) || 0;
                addThinking('管线执行完成', totalCh ? ('共完成 ' + totalCh + ' 章编写。') : '教材编写流程已完成。', 'success');
                loadTextbooks();
            } else if (d.type === 'pipeline_error') {
                addThinking('管线执行失败', (d.data && d.data.error) || '管线执行出错。', 'error');
            }
        } catch (e) {
            // Ignore keepalive or malformed SSE packets.
        }
    };

    eventSource.onerror = function() {
        flushOutput(true);
        if (accumulatedText || thinkingNodes.length || toolCalls.length || commandRuns.length) {
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
        streamClosed = true;
        if (window.refreshActiveChatStream) window.refreshActiveChatStream = null;
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
