/* ── LFTP Download GUI — Client-side logic ──────────────────────────────── */

const API = {
    browse: (path) => fetch(`/api/browse?path=${encodeURIComponent(path)}`).then(r => r.json()),
    download: (data) => fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    }).then(r => r.json()),
    cancel: (id) => fetch(`/api/cancel/${id}`, { method: 'POST' }).then(r => r.json()),
    resume: (id) => fetch(`/api/resume/${id}`, { method: 'POST' }).then(r => r.json()),
    delete: (id) => fetch(`/api/delete/${id}`, { method: 'POST' }).then(r => r.json()),
    clear: () => fetch('/api/clear', { method: 'POST' }).then(r => r.json()),
};

// ── State ────────────────────────────────────────────────────────────────

let currentPath = '/';
let currentEntries = []; // Cache entries for client-side sorting
let queueData = [];
let sortField = 'name';
let sortAsc = true;

// ── DOM refs ─────────────────────────────────────────────────────────────

const breadcrumbsEl = document.getElementById('breadcrumbs');
const fileListEl = document.getElementById('file-list');
const queueListEl = document.getElementById('queue-list');
const queueCountEl = document.getElementById('queue-count');
const queueStatsEl = document.getElementById('queue-stats');
const clearBtn = document.getElementById('btn-clear');

// ── File browser ─────────────────────────────────────────────────────────

async function browseTo(path) {
    fileListEl.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <span>Loading…</span>
        </div>`;

    try {
        const data = await API.browse(path);
        currentPath = data.path;
        currentEntries = data.entries;
        renderBreadcrumbs();
        renderFileList();
        // Remember this path across sessions
        fetch('/api/last-path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: currentPath }),
        }).catch(() => {});
    } catch (err) {
        fileListEl.innerHTML = `
            <div class="error-state">
                <p>⚠️ ${escapeHtml(err.message)}</p>
                <button class="btn" onclick="browseTo('${escapeAttr(currentPath)}')">Retry</button>
            </div>`;
    }
}

function renderBreadcrumbs() {
    const parts = currentPath.split('/').filter(Boolean);
    let html = `<span class="breadcrumb-item ${parts.length === 0 ? 'active' : ''}" onclick="browseTo('/')">📁 rtorrent</span>`;

    let accumulated = '';
    for (let i = 0; i < parts.length; i++) {
        accumulated += '/' + parts[i];
        const isLast = i === parts.length - 1;
        html += `<span class="breadcrumb-sep">›</span>`;
        html += `<span class="breadcrumb-item ${isLast ? 'active' : ''}" onclick="browseTo('${escapeAttr(accumulated)}')">${escapeHtml(parts[i])}</span>`;
    }
    breadcrumbsEl.innerHTML = html;
}

function setSort(field) {
    if (sortField === field) {
        sortAsc = !sortAsc; // Toggle direction
    } else {
        sortField = field;
        sortAsc = true; // Default to ascending for new field
    }
    renderFileList();
}

function sortEntries(entries) {
    return [...entries].sort((a, b) => {
        // Always keep directories grouped together first
        if (a.is_dir !== b.is_dir) {
            return a.is_dir ? -1 : 1;
        }

        let valA, valB;
        switch (sortField) {
            case 'size':
                valA = a.size || 0;
                valB = b.size || 0;
                break;
            case 'ext':
                valA = a.is_dir ? '' : (a.name.split('.').pop().toLowerCase() || '');
                valB = b.is_dir ? '' : (b.name.split('.').pop().toLowerCase() || '');
                if (valA === valB) {
                    valA = a.name.toLowerCase();
                    valB = b.name.toLowerCase();
                }
                break;
            case 'date':
                valA = a.mtime || 0;
                valB = b.mtime || 0;
                break;
            case 'name':
            default:
                valA = a.name.toLowerCase();
                valB = b.name.toLowerCase();
                break;
        }

        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
    });
}

function formatDate(epoch) {
    if (!epoch) return '';
    const d = new Date(epoch * 1000);
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

function renderFileList() {
    if (currentEntries.length === 0) {
        fileListEl.innerHTML = `
            <div class="loading" style="color: var(--text-muted)">
                <span>This directory is empty</span>
            </div>`;
        return;
    }

    const sortedEntries = sortEntries(currentEntries);

    // Helper to render sort arrow
    const getArrow = (field) => {
        if (sortField !== field) return '';
        return `<span class="sort-icon">${sortAsc ? '▴' : '▾'}</span>`;
    };

    let html = `
        <div class="file-list-header">
            <div></div> <!-- Icon col -->
            <div onclick="setSort('name')">Name ${getArrow('name')}</div>
            <div onclick="setSort('ext')">Ext ${getArrow('ext')}</div>
            <div onclick="setSort('size')">Size ${getArrow('size')}</div>
            <div onclick="setSort('date')">Modified ${getArrow('date')}</div>
            <div></div> <!-- Action col -->
        </div>
        <ul class="file-list">
    `;

    html += sortedEntries.map(entry => {
        const icon = entry.is_dir ? '📁' : getFileIcon(entry.name);
        const size = entry.is_dir ? '--' : (entry.size_human || '');
        const ext = entry.is_dir ? '' : (entry.name.includes('.') ? entry.name.split('.').pop().toLowerCase() : '');
        const dateStr = formatDate(entry.mtime);
        const entryPath = currentPath === '/' ? '/' + entry.name : currentPath + '/' + entry.name;

        const clickAttr = entry.is_dir ? `onclick="browseTo('${escapeAttr(entryPath)}')"` : '';

        return `
            <li class="file-item" ${clickAttr}>
                <span class="file-icon">${icon}</span>
                <span class="file-name" title="${escapeAttr(entry.name)}">${escapeHtml(entry.name)}</span>
                <span class="file-size">${escapeHtml(ext)}</span>
                <span class="file-size">${size}</span>
                <span class="file-size">${dateStr}</span>
                <span class="file-action">
                    <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); enqueue('${escapeAttr(entryPath)}', '${escapeAttr(entry.name)}', ${entry.is_dir})">
                        ⬇ ${entry.is_dir ? 'Mirror' : 'Download'}
                    </button>
                </span>
            </li>`;
    }).join('');

    html += '</ul>';
    fileListEl.innerHTML = html;
}

function getFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const icons = {
        mkv: '🎬', mp4: '🎬', avi: '🎬', wmv: '🎬', mov: '🎬',
        mp3: '🎵', flac: '🎵', ogg: '🎵', aac: '🎵', wav: '🎵',
        zip: '📦', rar: '📦', '7z': '📦', tar: '📦', gz: '📦',
        nfo: '📄', txt: '📄', srt: '📝', sub: '📝', ass: '📝',
        jpg: '🖼️', png: '🖼️', gif: '🖼️', bmp: '🖼️',
        iso: '💿', img: '💿',
    };
    return icons[ext] || '📄';
}

// ── Download actions ─────────────────────────────────────────────────────

async function enqueue(path, name, isDir) {
    try {
        await API.download({ path, name, is_dir: isDir });
    } catch (err) {
        console.error('Failed to enqueue:', err);
    }
}

// ── Queue rendering (SSE) ────────────────────────────────────────────────

function connectSSE() {
    const source = new EventSource('/api/queue');

    source.onmessage = (event) => {
        queueData = JSON.parse(event.data);
        renderQueue();
    };

    source.onerror = () => {
        // Reconnect after a short delay
        source.close();
        setTimeout(connectSSE, 3000);
    };
}

function parseSpeedToBytes(str) {
    if (!str) return 0;
    const m = str.match(/([\d.]+)\s*([KMGT]?i?B?\/s)/i);
    if (!m) return 0;
    const val = parseFloat(m[1]);
    const unit = m[2].toUpperCase();
    if (unit.startsWith('G')) return val * 1073741824;
    if (unit.startsWith('M')) return val * 1048576;
    if (unit.startsWith('K')) return val * 1024;
    return val;
}

function formatBytesPerSec(bps) {
    if (bps >= 1073741824) return (bps / 1073741824).toFixed(1) + ' GB/s';
    if (bps >= 1048576)    return (bps / 1048576).toFixed(1) + ' MB/s';
    if (bps >= 1024)       return (bps / 1024).toFixed(1) + ' KB/s';
    return bps.toFixed(0) + ' B/s';
}

function parseEtaToSeconds(str) {
    if (!str) return 0;
    let s = 0;
    const d = str.match(/(\d+)d/i); if (d) s += parseInt(d[1]) * 86400;
    const h = str.match(/(\d+)h/i); if (h) s += parseInt(h[1]) * 3600;
    const mn = str.match(/(\d+)m/i); if (mn) s += parseInt(mn[1]) * 60;
    const sc = str.match(/(\d+)s/i); if (sc) s += parseInt(sc[1]);
    return s;
}

function formatSeconds(s) {
    if (s < 60)   return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function renderQueue() {
    const active = queueData.filter(i => i.status === 'downloading' || i.status === 'queued').length;
    queueCountEl.textContent = active > 0 ? active : '';

    const downloading = queueData.filter(i => i.status === 'downloading');
    if (downloading.length > 0) {
        const totalBps = downloading.reduce((sum, i) => sum + parseSpeedToBytes(i.speed), 0);
        const avgPct   = Math.round(downloading.reduce((sum, i) => sum + i.percent, 0) / downloading.length);
        const maxEta   = Math.max(...downloading.map(i => parseEtaToSeconds(i.eta)));
        const parts = [];
        if (totalBps > 0) parts.push(formatBytesPerSec(totalBps));
        if (avgPct > 0)   parts.push(`${avgPct}%`);
        if (maxEta > 0)   parts.push(`ETA: ${formatSeconds(maxEta)}`);
        queueStatsEl.textContent = parts.join('  ·  ');
    } else {
        queueStatsEl.textContent = '';
    }

    if (queueData.length === 0) {
        queueListEl.innerHTML = `
            <div class="queue-empty">
                <div class="queue-empty-icon">📥</div>
                <p>No downloads yet.<br>Browse files and click download to get started.</p>
            </div>`;
        clearBtn.style.display = 'none';
        return;
    }

    const hasFinished = queueData.some(i => ['completed', 'failed', 'cancelled'].includes(i.status));
    clearBtn.style.display = hasFinished ? '' : 'none';

    queueListEl.innerHTML = queueData.map(item => {
        const statusClass = `status-${item.status}`;
        const statusLabel = item.status.charAt(0).toUpperCase() + item.status.slice(1);
        const showProgress = item.status === 'downloading';
        const isActive = item.status === 'downloading' || item.status === 'queued';
        const barClass = item.status === 'completed' ? 'completed' : '';

        let metaHtml = '';
        if (showProgress) {
            const parts = [];
            if (item.percent > 0) parts.push(`${item.percent}%`);
            if (item.speed) parts.push(item.speed);
            if (item.eta) parts.push(`ETA: ${item.eta}`);
            if (item.threads > 0) parts.push(`${item.threads} threads`);
            metaHtml = parts.join('  ·  ') || 'Starting…';
        } else if (item.status === 'completed' && item.speed) {
            metaHtml = item.speed;
        }

        return `
            <div class="queue-item">
                <div class="queue-item-header">
                    <span class="queue-item-name" title="${escapeAttr(item.name)}">${item.is_dir ? '📁' : '📄'} ${escapeHtml(item.name)}</span>
                    <span class="queue-item-status ${statusClass}">${statusLabel}</span>
                </div>
                <div class="progress-bar-track">
                    <div class="progress-bar-fill ${barClass}" style="width: ${item.status === 'completed' ? 100 : item.percent}%"></div>
                </div>
                ${metaHtml ? `<div class="queue-item-meta"><span>${metaHtml}</span></div>` : ''}
                ${item.error ? `<div class="queue-item-error">${escapeHtml(item.error)}</div>` : ''}
                ${isActive ? `
                    <div class="queue-item-actions">
                        <button class="btn btn-danger btn-sm" onclick="cancelItem('${item.id}')">✕ Cancel</button>
                    </div>` : ''}
                ${item.status === 'cancelled' ? `
                    <div class="queue-item-actions">
                        <button class="btn btn-primary btn-sm" onclick="resumeItem('${item.id}')">▶ Resume</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteItem('${item.id}')">🗑 Delete</button>
                    </div>` : ''}
            </div>`;
    }).join('');
}

async function cancelItem(id) {
    await API.cancel(id);
}

async function resumeItem(id) {
    await API.resume(id);
}

async function deleteItem(id) {
    await API.delete(id);
}

async function clearFinished() {
    await API.clear();
}

// ── Utility ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ── Log viewer ───────────────────────────────────────────────────────────

let logOpen = false;
let logInterval = null;

function toggleLogs() {
    logOpen = !logOpen;
    const body = document.getElementById('log-body');
    const toggle = document.getElementById('log-toggle');
    body.style.display = logOpen ? '' : 'none';
    toggle.textContent = logOpen ? '▼' : '▶';
    if (logOpen) {
        fetchLogs();
        logInterval = setInterval(fetchLogs, 5000);
    } else if (logInterval) {
        clearInterval(logInterval);
        logInterval = null;
    }
}

async function fetchLogs() {
    try {
        const r = await fetch('/api/logs?n=200');
        const data = await r.json();
        const el = document.getElementById('log-content');
        if (data.logs && data.logs.length > 0) {
            el.innerHTML = data.logs.map(line => {
                if (line.includes('[ERROR]')) return `<span class="log-error">${escapeHtml(line)}</span>`;
                if (line.includes('[WARNING]')) return `<span class="log-warn">${escapeHtml(line)}</span>`;
                return escapeHtml(line);
            }).join('\n');
            el.scrollTop = el.scrollHeight;
        } else {
            el.textContent = 'No log entries yet.';
        }
    } catch (err) {
        document.getElementById('log-content').textContent = 'Failed to load logs: ' + err.message;
    }
}

// ── Init ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    let startPath = '/';
    try {
        const resp = await fetch('/api/last-path');
        const data = await resp.json();
        if (data.path) startPath = data.path;
    } catch (_) {}
    browseTo(startPath);
    connectSSE();
    clearBtn.addEventListener('click', clearFinished);
});
