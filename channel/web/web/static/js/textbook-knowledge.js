// Knowledge base management, graph, organize progress, file browser.
// Split from textbook.js; loaded as classic scripts to preserve existing globals.
var knowledgeFileState = {
    bookId: '',
    offset: 0,
    limit: 80,
    total: 0,
    hasMore: false,
    loading: false,
    query: '',
    files: []
};
var knowledgeFileSearchTimer = null;

function loadKnowledgePage() {
    var select = document.getElementById('knowledgeBookSelect');
    var preferredBookId = select ? select.value : '';
    loadKnowledgeBookSelector(preferredBookId).then(function(bookId) {
        var selectedBookId = bookId || preferredBookId || '';
        loadKnowledgeSources(selectedBookId);
        loadKnowledgeStatus(selectedBookId);
        resetKnowledgeGraphPanel(selectedBookId);
    });
    initKnowledgeBrowserResize();
}

function loadKnowledgeBookSelector(preferredBookId) {
    var select = document.getElementById('knowledgeBookSelect');
    if (!select) return Promise.resolve(preferredBookId || '');
    return fetch(API_BASE + '/api/textbook')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                var books = data.textbooks || [];
                var currentVal = preferredBookId || select.value;
                var html = '<option value="">全部知识库</option>';
                books.forEach(function(b) {
                    html += '<option value="' + escapeHtml(b.id) + '">' + escapeHtml(b.title || b.id) + '</option>';
                });
                select.innerHTML = html;
                if (currentVal) select.value = currentVal;
                return select.value || '';
            }
            return preferredBookId || select.value || '';
        })
        .catch(function(err) {
            console.error('Load book selector error:', err);
            return preferredBookId || select.value || '';
        });
}

function onKnowledgeBookChange() {
    var select = document.getElementById('knowledgeBookSelect');
    var bookId = select ? select.value : '';
    loadKnowledgeSources(bookId);
    loadKnowledgeStatus(bookId);
    resetKnowledgeGraphPanel(bookId);
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
        body: JSON.stringify({book_id: bookId, force: true})
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
                    resetKnowledgeGraphPanel(bookId);
                } else if (data.status === 'error') {
                    clearInterval(pollInterval);
                    if (btn) { btn.disabled = false; btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> AI整理'; }
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
            var payload = ev.payload || ev;
            var status = ev.status || payload.status || '';
            var cls = status === 'error' ? 'error' : (status === 'completed' ? 'success' : 'running');
            var title = ev.message || payload.message || payload.stage || ev.type || '';
            var meta = [ev.source, ev.phase || payload.stage, status].filter(Boolean).join(' · ');
            return '<div class="knowledge-run-event ' + cls + '">' +
                '<div class="knowledge-run-title">' + escapeHtml(title) + '</div>' +
                '<div class="knowledge-run-meta">' + escapeHtml(meta) + '</div>' +
                '</div>';
        }).join('');
    }
}

function resetKnowledgeGraphPanel(bookId) {
    var container = document.getElementById('knowledgeGraphArea');
    if (container) {
        container.innerHTML = '<div class="knowledge-graph-empty">知识图谱较耗资源，点击“加载图谱”后再渲染当前知识库的关联数据。</div>';
    }
    var btn = document.getElementById('btnLoadKnowledgeGraph');
    if (btn) {
        btn.disabled = false;
        btn.textContent = '加载图谱';
        btn.dataset.bookId = bookId || '';
    }
}

function loadKnowledgeGraphOnDemand() {
    var select = document.getElementById('knowledgeBookSelect');
    var bookId = select ? select.value : '';
    var btn = document.getElementById('btnLoadKnowledgeGraph');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '加载中...';
    }
    loadKnowledgeGraph(bookId, 'knowledgeGraphArea');
}

function loadKnowledgeGraph(bookId, containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var params = new URLSearchParams();
    params.set('limit', '80');
    if (bookId) params.set('book_id', bookId);
    var url = API_BASE + '/api/knowledge/knowledge-graph?' + params.toString();
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                renderKnowledgeGraph(container, data.nodes || [], data.edges || []);
                var btn = document.getElementById('btnLoadKnowledgeGraph');
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '重新加载图谱';
                }
            } else {
                container.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--muted-fg);font-size:13px;">加载图谱失败</div>';
            }
        })
        .catch(function(err) {
            container.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--muted-fg);font-size:13px;">加载图谱失败</div>';
            var btn = document.getElementById('btnLoadKnowledgeGraph');
            if (btn) {
                btn.disabled = false;
                btn.textContent = '加载图谱';
            }
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
    knowledgeFileState.bookId = bookId || '';
    knowledgeFileState.offset = 0;
    knowledgeFileState.total = 0;
    knowledgeFileState.hasMore = false;
    knowledgeFileState.files = [];
    var previewEl = document.getElementById('knowledgeFilePreview');
    if (previewEl) previewEl.innerHTML = '<div class="knowledge-file-preview-empty">选择左侧文件查看内容</div>';
    loadKnowledgeFilePage(false);
}

function onKnowledgeFileSearchInput() {
    clearTimeout(knowledgeFileSearchTimer);
    knowledgeFileSearchTimer = setTimeout(function() {
        var input = document.getElementById('knowledgeFileSearch');
        knowledgeFileState.query = input ? input.value.trim() : '';
        knowledgeFileState.offset = 0;
        knowledgeFileState.files = [];
        loadKnowledgeFilePage(false);
    }, 250);
}

function loadKnowledgeFilePage(append) {
    if (knowledgeFileState.loading) return;
    knowledgeFileState.loading = true;
    var treeEl = document.getElementById('knowledgeFileTree');
    var metaEl = document.getElementById('knowledgeFileMeta');
    if (treeEl && !append) treeEl.innerHTML = '<div class="knowledge-empty">正在加载文件...</div>';
    var params = new URLSearchParams();
    params.set('mode', 'page');
    params.set('offset', String(append ? knowledgeFileState.offset : 0));
    params.set('limit', String(knowledgeFileState.limit));
    if (knowledgeFileState.bookId) params.set('book_id', knowledgeFileState.bookId);
    if (knowledgeFileState.query) params.set('query', knowledgeFileState.query);
    fetch(API_BASE + '/api/knowledge/list?' + params.toString())
        .then(r => r.json())
        .then(data => {
            knowledgeFileState.loading = false;
            if (data.status === 'success') {
                var incoming = data.files || [];
                knowledgeFileState.files = append ? knowledgeFileState.files.concat(incoming) : incoming;
                knowledgeFileState.offset = data.next_offset || knowledgeFileState.files.length;
                knowledgeFileState.total = data.total || knowledgeFileState.files.length;
                knowledgeFileState.hasMore = !!data.has_more;
                renderKnowledgeSources(knowledgeFileState.files, [], knowledgeFileState.bookId, {
                    hasMore: knowledgeFileState.hasMore,
                    total: knowledgeFileState.total,
                    loaded: knowledgeFileState.files.length
                });
                if (metaEl) metaEl.textContent = '已加载 ' + knowledgeFileState.files.length + ' / ' + knowledgeFileState.total + ' 个文件';
            } else {
                renderKnowledgeSourceError(data.message || '加载知识库文件失败');
            }
        })
        .catch(function(err) {
            knowledgeFileState.loading = false;
            console.error('Load knowledge sources error:', err);
            renderKnowledgeSourceError(String(err));
        });
}

function loadKnowledgeStatus(bookId) {
    var url = API_BASE + '/api/knowledge/status';
    if (bookId) url += '?book_id=' + encodeURIComponent(bookId);
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                const el = document.getElementById('knowledgeStatusInfo');
                if (el) el.textContent = `共 ${data.total_documents || 0} 个文档，${data.categories ? data.categories.length : 0} 个分类`;
                var docsEl = document.getElementById('knowledgeTotalDocs');
                if (docsEl) docsEl.textContent = data.total_documents || 0;
                var chunksEl = document.getElementById('knowledgeTotalChunks');
                if (chunksEl) chunksEl.textContent = (data.wiki && data.wiki.chunks) ? data.wiki.chunks : 0;
                var sizeEl = document.getElementById('knowledgeTotalSize');
                if (sizeEl) sizeEl.textContent = formatFileSize(data.total_size || 0);
            }
        })
        .catch(err => console.error('Load knowledge status error:', err));
}

function renderKnowledgeSources(rootFiles, tree, bookId, pageInfo) {
    const treeEl = document.getElementById('knowledgeFileTree');
    const previewEl = document.getElementById('knowledgeFilePreview');
    if (!treeEl) return;
    rootFiles = rootFiles || [];
    tree = tree || [];
    if (!rootFiles.length && !tree.length) {
        treeEl.innerHTML = '<div class="knowledge-empty">暂无知识库文件</div>';
        if (previewEl) previewEl.innerHTML = '<div class="knowledge-file-preview-empty">上传或整理知识库后，可在这里查阅文件内容</div>';
        return;
    }
    var html = '';
    if (rootFiles.length) {
        html += '<div class="knowledge-tree-section">files</div>';
        html += rootFiles.map(function(file) { return renderKnowledgeFileNode(file, bookId, 0); }).join('');
    }
    html += tree.map(function(group) { return renderKnowledgeDirNode(group, bookId, 0); }).join('');
    if (pageInfo && pageInfo.hasMore) {
        html += '<button type="button" class="knowledge-load-more" onclick="loadKnowledgeFilePage(true)">加载更多（' +
            escapeHtml(String(pageInfo.loaded)) + '/' + escapeHtml(String(pageInfo.total)) + '）</button>';
    }
    treeEl.innerHTML = html;
    if (previewEl && !pageInfo) previewEl.innerHTML = '<div class="knowledge-file-preview-empty">选择左侧文件查看内容</div>';
}

function renderKnowledgeSourceError(message) {
    var treeEl = document.getElementById('knowledgeFileTree');
    var previewEl = document.getElementById('knowledgeFilePreview');
    if (treeEl) {
        treeEl.innerHTML = '<div class="knowledge-empty">加载知识库文件失败：' + escapeHtml(message || 'unknown error') + '</div>';
    }
    if (previewEl) {
        previewEl.innerHTML = '<div class="knowledge-file-preview-empty">请检查后端日志或重新进入知识库页面</div>';
    }
}

function renderKnowledgeDirNode(group, bookId, depth) {
    var files = group.files || [];
    var children = group.children || [];
    var html = '<details class="knowledge-dir" open>' +
        '<summary style="padding-left:' + (depth * 12) + 'px;"><i class="fas fa-folder"></i><span title="' + escapeHtml(group.path || group.dir || '') + '">' + escapeHtml(group.dir || 'folder') + '</span></summary>' +
        '<div class="knowledge-dir-body">';
    html += files.map(function(file) { return renderKnowledgeFileNode(file, bookId, depth + 1); }).join('');
    html += children.map(function(child) { return renderKnowledgeDirNode(child, bookId, depth + 1); }).join('');
    html += '</div></details>';
    return html;
}

function renderKnowledgeFileNode(file, bookId, depth) {
    var path = file.path || file.name || '';
    var label = file.title || file.name || path;
    var meta = formatFileSize(file.size || 0);
    return '<button type="button" class="knowledge-file-node" style="padding-left:' + (10 + depth * 12) + 'px;" data-path="' + escapeHtml(path) + '" data-book-id="' + escapeHtml(bookId || '') + '" onclick="readKnowledgeFile(this.dataset.path, this.dataset.bookId, this)">' +
        '<i class="fas fa-file-lines"></i>' +
        '<span class="knowledge-file-node-title" title="' + escapeHtml(path) + '">' + escapeHtml(label) + '</span>' +
        '<span class="knowledge-file-node-meta">' + escapeHtml(meta) + '</span>' +
    '</button>';
}

function readKnowledgeFile(path, bookId, node) {
    if (!path) return;
    document.querySelectorAll('.knowledge-file-node.active').forEach(function(el) { el.classList.remove('active'); });
    if (node) node.classList.add('active');
    var previewEl = document.getElementById('knowledgeFilePreview');
    if (previewEl) previewEl.innerHTML = '<div class="knowledge-file-preview-empty">正在读取...</div>';
    var params = new URLSearchParams();
    params.set('path', path);
    if (bookId) params.set('book_id', bookId);
    fetch(API_BASE + '/api/knowledge/read?' + params.toString())
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!previewEl) return;
            if (data.status !== 'success') {
                previewEl.innerHTML = '<div class="knowledge-file-preview-empty">读取失败：' + escapeHtml(data.message || '') + '</div>';
                return;
            }
            var content = data.content || '';
            var isMarkdown = /\.md$/i.test(path);
            var truncated = data.truncated ? '<div class="knowledge-preview-truncated">文件较大，预览已截断前 ' + escapeHtml(String(data.max_chars || 300000)) + ' 字符。</div>' : '';
            var body = truncated + (isMarkdown ? '<div class="markdown-preview">' + renderMarkdown(content) + '</div>' : '<pre class="knowledge-text-preview">' + escapeHtml(content) + '</pre>');
            previewEl.innerHTML = body;
        })
        .catch(function(err) {
            if (previewEl) previewEl.innerHTML = '<div class="knowledge-file-preview-empty">读取失败：' + escapeHtml(String(err)) + '</div>';
        });
}

function initKnowledgeBrowserResize() {
    var browser = document.getElementById('knowledgeSourceList');
    var handle = document.getElementById('knowledgeBrowserResize');
    if (!browser || !handle || handle.dataset.bound === '1') return;
    handle.dataset.bound = '1';
    var savedWidth = localStorage.getItem('knowledgeBrowserSidebarWidth');
    if (savedWidth) browser.style.setProperty('--knowledge-sidebar-width', savedWidth + 'px');

    var dragging = false;
    function setWidth(clientX) {
        var rect = browser.getBoundingClientRect();
        var min = 240;
        var max = Math.max(min, rect.width - 360);
        var width = Math.min(max, Math.max(min, clientX - rect.left));
        browser.style.setProperty('--knowledge-sidebar-width', width + 'px');
        localStorage.setItem('knowledgeBrowserSidebarWidth', String(Math.round(width)));
    }
    handle.addEventListener('pointerdown', function(ev) {
        if (window.matchMedia && window.matchMedia('(max-width: 980px)').matches) return;
        dragging = true;
        browser.classList.add('resizing');
        handle.setPointerCapture(ev.pointerId);
        ev.preventDefault();
    });
    handle.addEventListener('pointermove', function(ev) {
        if (!dragging) return;
        setWidth(ev.clientX);
    });
    function stopResize(ev) {
        if (!dragging) return;
        dragging = false;
        browser.classList.remove('resizing');
        try { handle.releasePointerCapture(ev.pointerId); } catch (e) {}
    }
    handle.addEventListener('pointerup', stopResize);
    handle.addEventListener('pointercancel', stopResize);
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
        fetch(API_BASE + '/api/knowledge/upload', {method: 'POST', body: formData})
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('文档上传成功');
                    loadKnowledgeSources(bookId || '');
                    loadKnowledgeStatus(bookId || '');
                    resetKnowledgeGraphPanel(bookId || '');
                } else {
                    showToast('上传失败: ' + (data.message || ''), 'error');
                }
            })
            .catch(err => showToast('上传失败: ' + err, 'error'));
    };
    input.click();
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}
