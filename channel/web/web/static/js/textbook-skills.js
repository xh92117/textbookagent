// Skill management UI.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
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
    var title = typeof getCurrentBookTitle === 'function' ? getCurrentBookTitle() : ((currentBookData && currentBookData.title) || '当前教材');
    navigateToChat('请优化《' + title + '》教材大纲');
}

function reviewOutline() {
    if (!currentBookId) { alert('请先选择一本教材'); return; }
    var title = typeof getCurrentBookTitle === 'function' ? getCurrentBookTitle() : ((currentBookData && currentBookData.title) || '当前教材');
    navigateToChat('请审查《' + title + '》教材大纲');
}
