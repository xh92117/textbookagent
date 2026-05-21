// System configuration, model settings, outline editor, and review helpers.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
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

function switchSettingsTab(tabName) {
    document.querySelectorAll('.settings-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-settings-tab') === tabName);
    });
    document.querySelectorAll('.settings-tab-pane').forEach(function(pane) {
        pane.classList.toggle('active', pane.id === 'tab-' + tabName);
    });
}

function togglePwd(btn) {
    var input = btn && btn.parentElement ? btn.parentElement.querySelector('input') : null;
    if (!input) return;
    var show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    var icon = btn.querySelector('i');
    if (icon) icon.className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
}

function clearModelEditor() {
    var editId = document.getElementById('settingEditModelId');
    var provider = document.getElementById('settingModelProvider');
    var modelName = document.getElementById('settingModelName');
    var apiKey = document.getElementById('settingModelApiKey');
    var apiBase = document.getElementById('settingModelApiBase');
    if (editId) editId.value = '';
    if (provider && _configChatModels[0]) provider.value = _configChatModels[0].provider || 'custom';
    if (modelName) modelName.value = '';
    if (apiKey) apiKey.value = '';
    if (apiBase) apiBase.value = '';
    onModelProviderChange();
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
            var statusText = item.provider_key_configured ? '已配置密钥' : '未配置密钥';
            var apiBaseText = item.api_base || '默认 URL';
            return '<div class="model-card' + (isActive ? ' active' : '') + '">' +
                '<div class="model-card-icon"><i class="fas fa-microchip"></i></div>' +
                '<div class="model-card-info"><div class="model-card-name">' + escapeHtml(modelDisplayName(item)) + '</div>' +
                '<div class="model-card-meta"><span class="status-dot ' + (item.provider_key_configured ? 'ready' : 'muted') + '"></span>' + escapeHtml(statusText) + ' · ' + escapeHtml(item.model || '') + ' · ' + escapeHtml(apiBaseText) + '</div></div>' +
                '<div class="model-card-actions">' +
                '<button class="model-action-btn" type="button" onclick="editChatModel(&quot;' + escapeHtml(item.id) + '&quot;)" title="编辑"><i class="fas fa-pen"></i></button>' +
                '<button class="model-action-btn danger" type="button" onclick="removeChatModel(&quot;' + escapeHtml(item.id) + '&quot;)" title="删除"><i class="fas fa-trash"></i></button>' +
                '</div></div>';
        }).join('');
    }
    fillModelChoice(document.getElementById('settingActiveChatModel'), _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingReviewModelChoice'), _configReviewModelId || _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingImageModelChoice'), _configImageModelId || _configActiveChatModelId);
    fillModelChoice(document.getElementById('settingKnowledgeModelChoice'), _configKnowledgeModelId || _configActiveChatModelId);
    var count = document.getElementById('settingModelCount');
    if (count) count.textContent = String(_configChatModels.length);
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
    apiBaseInput.placeholder = provider.api_base_placeholder || 'https://api.example.com/v1';
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
    clearModelEditor();
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
        var timeout = document.getElementById('settingTimeout');
        if (timeout) timeout.value = data.request_timeout || data.timeout || 180;
        var thinking = document.getElementById('settingThinking');
        if (thinking) thinking.checked = data.enable_thinking || false;
        var password = document.getElementById('settingPassword');
        if (password) password.value = '';
        renderWorkspaceSettings(data.workspace || {});
        var saveStatus = document.getElementById('saveStatus');
        if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-circle-check"></i> 配置已加载';
    }).catch(function(e) {
        console.error('Failed to load settings:', e);
        var saveStatus = document.getElementById('saveStatus');
        if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-triangle-exclamation"></i> 配置加载失败';
    });
}

function renderWorkspaceSettings(workspace) {
    workspace = workspace || {};
    var active = workspace.active_workspace || '';
    var systemDir = workspace.system_dir || '';
    var activeInput = document.getElementById('settingActiveWorkspace');
    var storageInput = document.getElementById('settingTextbooksStorageDir');
    var splitInput = document.getElementById('settingWorkspaceSplit');
    var currentLabel = document.getElementById('settingWorkspaceCurrent');
    var systemLabel = document.getElementById('settingSystemDir');
    if (activeInput) activeInput.value = active;
    if (storageInput) storageInput.value = workspace.textbooks_storage_dir || '';
    if (splitInput) splitInput.checked = workspace.workspace_split_enabled !== false;
    if (currentLabel) currentLabel.textContent = active || '-';
    if (systemLabel) systemLabel.textContent = systemDir || '-';
}

function saveSettings() {
    var maxTokens = document.getElementById('settingMaxTokens');
    var maxTurns = document.getElementById('settingMaxTurns');
    var maxSteps = document.getElementById('settingMaxSteps');
    var timeout = document.getElementById('settingTimeout');
    var thinking = document.getElementById('settingThinking');
    var password = document.getElementById('settingPassword');
    var saveStatus = document.getElementById('saveStatus');
    var updates = {};
    if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 正在保存...';
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
    if (timeout) updates.request_timeout = parseInt(timeout.value) || 180;
    if (thinking) updates.enable_thinking = thinking.checked;
    if (password && password.value.trim()) updates.web_password = password.value.trim();
    var activeWorkspace = document.getElementById('settingActiveWorkspace');
    var textbooksStorageDir = document.getElementById('settingTextbooksStorageDir');
    var workspaceSplit = document.getElementById('settingWorkspaceSplit');
    if (activeWorkspace && activeWorkspace.value.trim()) updates.active_workspace = activeWorkspace.value.trim();
    if (textbooksStorageDir) updates.textbooks_storage_dir = textbooksStorageDir.value.trim();
    if (workspaceSplit) updates.workspace_split_enabled = workspaceSplit.checked;
    var providerSelect = document.getElementById('settingModelProvider');
    var keyInput = document.getElementById('settingModelApiKey');
    if (providerSelect && keyInput) {
        var providerInfo = _configProviders[providerSelect.value] || {};
        var keyField = providerInfo.api_key_field || '';
        var keyValue = keyInput.value.trim();
        if (keyField && keyValue && keyValue.indexOf('*') < 0) _configProviderKeyUpdates[keyField] = keyValue;
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
            if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-circle-check"></i> 配置已保存';
            loadSettings();
        } else {
            showToast('保存失败: ' + (data.message || '未知错误'), 'error');
            if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-triangle-exclamation"></i> 保存失败';
        }
    }).catch(function(e) {
        showToast('保存失败: ' + e.message, 'error');
        if (saveStatus) saveStatus.innerHTML = '<i class="fas fa-triangle-exclamation"></i> 保存失败';
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

