/**
 * Crawlavator - Multi-Site Batch Downloader Frontend
 */

// DOM Elements
const elements = {
    // Site selector
    siteSelect: document.getElementById('site-select'),
    
    // Config
    authFields: document.getElementById('auth-fields'),
    emailInput: document.getElementById('email'),
    passwordInput: document.getElementById('password'),
    downloadDirInput: document.getElementById('download-dir'),
    resetDirBtn: document.getElementById('reset-dir-btn'),
    exportToKcCheckbox: document.getElementById('export-to-kc'),
    kcDirWrapper: document.getElementById('kc-dir-wrapper'),
    kcDirInput: document.getElementById('kc-dir'),
    saveConfigBtn: document.getElementById('save-config-btn'),
    loginBtn: document.getElementById('login-btn'),
    authSection: document.getElementById('auth-section'),
    manualLoginBtn: document.getElementById('manual-login-btn'),
    authStatus: document.getElementById('auth-status'),
    configStatus: document.getElementById('config-status'),
    
    // Content
    contentSection: document.getElementById('content-section'),
    indexBtn: document.getElementById('index-btn'),
    indexStatus: document.getElementById('index-status'),
    categoryFilterSection: document.getElementById('category-filter-section'),
    categoryFilters: document.getElementById('category-filters'),
    typeFilters: document.getElementById('type-filters'),
    contentTable: document.getElementById('content-table'),
    contentTbody: document.getElementById('content-tbody'),
    selectAllCheckbox: document.getElementById('select-all-checkbox'),
    selectAllBtn: document.getElementById('select-all-btn'),
    selectNoneBtn: document.getElementById('select-none-btn'),
    selectedCount: document.getElementById('selected-count'),
    noContent: document.getElementById('no-content'),
    
    // Search
    searchInput: document.getElementById('search-input'),
    clearSearchBtn: document.getElementById('clear-search-btn'),
    
    // Download
    downloadBtn: document.getElementById('download-btn'),
    
    // Progress
    progressOverlay: document.getElementById('progress-overlay'),
    progressBar: document.getElementById('progress-bar'),
    progressText: document.getElementById('progress-text'),
    progressLog: document.getElementById('progress-log')
};

// State
let contentItems = [];
let selectedItemIds = new Set();
let currentSite = null;
let sites = [];

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await loadSites();
    await loadConfig();
    setupEventListeners();
});

async function loadSites() {
    try {
        const response = await fetch('/api/sites');
        sites = await response.json();
        
        // Populate site selector
        elements.siteSelect.innerHTML = '';
        sites.forEach(site => {
            const option = document.createElement('option');
            option.value = site.id;
            option.textContent = site.name;
            elements.siteSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load sites:', error);
    }
}

function setupEventListeners() {
    // Site selector
    elements.siteSelect.addEventListener('change', onSiteChange);
    
    // Config
    elements.saveConfigBtn.addEventListener('click', saveConfig);
    elements.loginBtn.addEventListener('click', login);
    elements.manualLoginBtn.addEventListener('click', manualLogin);
    elements.resetDirBtn.addEventListener('click', () => {
        elements.downloadDirInput.value = '';
    });
    
    // KC export toggle
    elements.exportToKcCheckbox.addEventListener('change', () => {
        elements.kcDirWrapper.style.display = elements.exportToKcCheckbox.checked ? 'block' : 'none';
    });
    
    // Content
    elements.indexBtn.addEventListener('click', indexContent);
    elements.selectAllBtn.addEventListener('click', selectAll);
    elements.selectNoneBtn.addEventListener('click', selectNone);
    elements.selectAllCheckbox.addEventListener('change', toggleSelectAll);
    
    // Search
    elements.searchInput.addEventListener('input', debounce(applyFilters, 300));
    elements.clearSearchBtn.addEventListener('click', () => {
        elements.searchInput.value = '';
        applyFilters();
    });
    
    // Download
    elements.downloadBtn.addEventListener('click', startDownload);
    
    // Update login button on input
    elements.emailInput.addEventListener('input', updateLoginButton);
    elements.passwordInput.addEventListener('input', updateLoginButton);
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Site change handler
async function onSiteChange() {
    const siteId = elements.siteSelect.value;
    currentSite = sites.find(s => s.id === siteId);
    
    // Clear content
    contentItems = [];
    selectedItemIds.clear();
    elements.contentTbody.innerHTML = '';
    elements.noContent.style.display = 'block';
    elements.contentTable.style.display = 'none';
    
    // Update UI based on site capabilities
    updateSiteUI();
    
    // Save active site and load config
    await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active_site: siteId })
    });
    
    await loadConfig();
}

function updateSiteUI() {
    if (!currentSite) return;
    
    // Show/hide auth fields
    const requiresAuth = currentSite.requires_auth;
    elements.authFields.style.display = requiresAuth ? 'block' : 'none';
    elements.authSection.style.display = requiresAuth ? 'block' : 'none';
    elements.loginBtn.style.display = requiresAuth ? 'inline-flex' : 'none';
    
    // Update category filters
    updateFilters();
    
    // Check auth for this site
    if (requiresAuth) {
        checkAuth();
    } else {
        updateAuthStatus(true, 'No authentication required');
        elements.contentSection.style.display = 'block';
    }
}

function updateFilters() {
    if (!currentSite) return;
    
    // Category filters
    const categories = currentSite.categories || [];
    elements.categoryFilters.innerHTML = '';
    
    if (categories.length <= 1) {
        elements.categoryFilterSection.style.display = 'none';
    } else {
        elements.categoryFilterSection.style.display = 'flex';
        categories.forEach(cat => {
            const label = document.createElement('label');
            label.className = 'filter-item';
            label.innerHTML = `
                <input type="checkbox" data-category="${cat}" checked>
                <span>${formatCategory(cat)}</span>
            `;
            label.querySelector('input').addEventListener('change', applyFilters);
            elements.categoryFilters.appendChild(label);
        });
    }
    
    // Type filters
    const types = currentSite.asset_types || [];
    elements.typeFilters.innerHTML = '';
    
    const typeIcons = {
        'video': '🎥',
        'article': '📝',
        'pdf': '📄',
        'audio': '🎧',
        'transcript': '📋'
    };
    
    types.forEach(type => {
        const label = document.createElement('label');
        label.className = 'filter-item';
        label.innerHTML = `
            <input type="checkbox" data-type="${type}" checked>
            <span>${typeIcons[type] || '📁'} ${formatCategory(type)}</span>
        `;
        label.querySelector('input').addEventListener('change', applyFilters);
        elements.typeFilters.appendChild(label);
    });
}

function formatCategory(str) {
    return str.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

// Config Functions
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        // Set active site
        const activeSite = config.active_site || 'eurodollar';
        elements.siteSelect.value = activeSite;
        currentSite = sites.find(s => s.id === activeSite);
        updateSiteUI();
        
        // Load site-specific config
        const siteConfig = config.sites?.[activeSite] || {};
        
        // Clear form fields first, then populate with site-specific values
        elements.emailInput.value = siteConfig.email || '';
        elements.passwordInput.value = siteConfig.password || '';
        elements.downloadDirInput.value = siteConfig.download_dir || '';
        elements.exportToKcCheckbox.checked = siteConfig.export_to_kc || false;
        elements.kcDirWrapper.style.display = siteConfig.export_to_kc ? 'block' : 'none';
        elements.kcDirInput.value = siteConfig.knowledge_chipper_dir || '';
        
        updateLoginButton();
        
        // Update auth status
        if (config.authenticated !== undefined) {
            updateAuthStatus(config.authenticated, config.auth_message);
            if (config.authenticated) {
                elements.contentSection.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

async function saveConfig() {
    const config = {
        site_id: elements.siteSelect.value,
        email: elements.emailInput.value.trim(),
        password: elements.passwordInput.value,
        download_dir: elements.downloadDirInput.value.trim(),
        export_to_kc: elements.exportToKcCheckbox.checked,
        knowledge_chipper_dir: elements.kcDirInput.value.trim()
    };
    
    elements.saveConfigBtn.disabled = true;
    elements.saveConfigBtn.textContent = 'Saving...';
    
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showStatus('config', 'success', 'Configuration saved!');
            updateLoginButton();
        } else {
            showStatus('config', 'error', result.error || 'Failed to save');
        }
    } catch (error) {
        showStatus('config', 'error', 'Failed to save: ' + error.message);
    } finally {
        elements.saveConfigBtn.disabled = false;
        elements.saveConfigBtn.textContent = 'Save Configuration';
    }
}

function updateLoginButton() {
    if (!currentSite?.requires_auth) {
        elements.loginBtn.disabled = true;
        return;
    }
    const hasCredentials = elements.emailInput.value.trim() && elements.passwordInput.value;
    elements.loginBtn.disabled = !hasCredentials;
}

// Auth Functions
async function checkAuth() {
    try {
        const response = await fetch('/api/check-auth');
        const result = await response.json();
        
        updateAuthStatus(result.authenticated, result.message);
        
        if (result.authenticated) {
            elements.contentSection.style.display = 'block';
        }
    } catch (error) {
        updateAuthStatus(false, 'Could not check auth status');
    }
}

function updateAuthStatus(isAuthenticated, message) {
    elements.authStatus.textContent = isAuthenticated 
        ? '✓ Authenticated - Ready to download'
        : message || 'Not authenticated';
    elements.authStatus.className = 'auth-status' + (isAuthenticated ? ' authenticated' : ' error');
    
    if (isAuthenticated) {
        elements.contentSection.style.display = 'block';
    }
}

async function login() {
    elements.loginBtn.disabled = true;
    elements.loginBtn.textContent = 'Logging in...';
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            updateAuthStatus(true, result.message);
            showStatus('config', 'success', 'Login successful!');
        } else {
            updateAuthStatus(false, result.error);
            showStatus('config', 'error', result.error);
        }
    } catch (error) {
        showStatus('config', 'error', 'Login failed: ' + error.message);
    } finally {
        elements.loginBtn.disabled = false;
        elements.loginBtn.textContent = 'Login';
        updateLoginButton();
    }
}

async function manualLogin() {
    elements.manualLoginBtn.disabled = true;
    elements.manualLoginBtn.textContent = 'Opening browser...';
    elements.authStatus.textContent = 'Browser opened - please log in manually';
    elements.authStatus.className = 'auth-status';
    
    try {
        const response = await fetch('/api/login-interactive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            updateAuthStatus(true, result.message);
            showStatus('config', 'success', 'Login successful!');
        } else {
            updateAuthStatus(false, result.error);
        }
    } catch (error) {
        updateAuthStatus(false, 'Manual login failed: ' + error.message);
    } finally {
        elements.manualLoginBtn.disabled = false;
        elements.manualLoginBtn.textContent = 'Open Browser for Manual Login';
    }
}

// Content Functions
async function indexContent() {
    elements.indexBtn.disabled = true;
    elements.indexBtn.textContent = 'Scanning...';
    showStatus('index', 'info', 'Scanning content... This may take a minute.');
    
    try {
        const response = await fetch('/api/index-content', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.error) {
            showStatus('index', 'error', result.error);
            return;
        }
        
        contentItems = result.items || [];
        renderContent();
        
        const summary = result.summary || {};
        const totalItems = summary.total_items || contentItems.length;
        const restricted = summary.restricted_count || 0;
        const errors = summary.error_count || 0;
        
        showStatus('index', 'success', 
            `Found ${totalItems} items.` +
            (restricted > 0 ? ` ${restricted} restricted.` : '') +
            (errors > 0 ? ` ${errors} errors.` : '')
        );
        
        if (contentItems.length > 0) {
            elements.noContent.style.display = 'none';
            elements.contentTable.style.display = 'table';
        } else {
            elements.noContent.style.display = 'block';
            elements.contentTable.style.display = 'none';
        }
        
    } catch (error) {
        showStatus('index', 'error', 'Indexing failed: ' + error.message);
    } finally {
        elements.indexBtn.disabled = false;
        elements.indexBtn.textContent = 'Scan Content';
    }
}

function renderContent() {
    elements.contentTbody.innerHTML = '';
    
    contentItems.forEach(item => {
        const row = document.createElement('tr');
        row.dataset.id = item.id;
        row.dataset.category = item.category;
        row.dataset.type = item.asset_type;
        
        const typeClass = `type-${item.asset_type}`;
        
        row.innerHTML = `
            <td class="checkbox-col">
                <input type="checkbox" data-id="${item.id}" class="content-checkbox">
            </td>
            <td class="content-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</td>
            <td><span class="content-type ${typeClass}">${item.asset_type}</span></td>
            <td class="content-category">${escapeHtml(item.category)}${item.subcategory ? ' / ' + item.subcategory : ''}</td>
            <td class="content-date">${item.date || '-'}</td>
        `;
        
        const checkbox = row.querySelector('.content-checkbox');
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                selectedItemIds.add(item.id);
            } else {
                selectedItemIds.delete(item.id);
            }
            updateSelectedCount();
        });
        
        elements.contentTbody.appendChild(row);
    });
    
    updateSelectedCount();
}

function applyFilters() {
    const searchQuery = elements.searchInput.value.toLowerCase();
    
    // Get selected categories
    const selectedCategories = new Set();
    document.querySelectorAll('#category-filters input:checked').forEach(cb => {
        selectedCategories.add(cb.dataset.category);
    });
    
    // Get selected types
    const selectedTypes = new Set();
    document.querySelectorAll('#type-filters input:checked').forEach(cb => {
        selectedTypes.add(cb.dataset.type);
    });
    
    const rows = elements.contentTbody.querySelectorAll('tr');
    
    rows.forEach(row => {
        const title = row.querySelector('.content-title')?.textContent.toLowerCase() || '';
        const type = row.dataset.type;
        const category = row.dataset.category;
        const categoryCell = row.querySelector('.content-category')?.textContent.toLowerCase() || '';
        
        // Search across title, type, and category
        const searchText = `${title} ${type} ${category} ${categoryCell}`;
        const matchesSearch = !searchQuery || searchText.includes(searchQuery);
        const matchesCategory = selectedCategories.size === 0 || selectedCategories.has(category);
        const matchesType = selectedTypes.size === 0 || selectedTypes.has(type);
        
        if (matchesSearch && matchesCategory && matchesType) {
            row.classList.remove('filtered-out');
        } else {
            row.classList.add('filtered-out');
        }
    });
    
    updateSelectedCount();
}

function selectAll() {
    document.querySelectorAll('.content-checkbox').forEach(cb => {
        const row = cb.closest('tr');
        if (!row.classList.contains('filtered-out')) {
            cb.checked = true;
            selectedItemIds.add(cb.dataset.id);
        }
    });
    updateSelectedCount();
}

function selectNone() {
    document.querySelectorAll('.content-checkbox').forEach(cb => {
        const row = cb.closest('tr');
        if (!row.classList.contains('filtered-out')) {
            cb.checked = false;
            selectedItemIds.delete(cb.dataset.id);
        }
    });
    updateSelectedCount();
}

function toggleSelectAll() {
    if (elements.selectAllCheckbox.checked) {
        selectAll();
    } else {
        selectNone();
    }
}

function updateSelectedCount() {
    const count = selectedItemIds.size;
    elements.selectedCount.textContent = `${count} selected`;
    elements.downloadBtn.disabled = count === 0;
    
    // Update header checkbox
    const visibleCheckboxes = Array.from(document.querySelectorAll('.content-checkbox')).filter(cb => {
        const row = cb.closest('tr');
        return !row.classList.contains('filtered-out');
    });
    
    const allChecked = visibleCheckboxes.length > 0 && visibleCheckboxes.every(cb => cb.checked);
    const someChecked = visibleCheckboxes.some(cb => cb.checked);
    
    elements.selectAllCheckbox.checked = allChecked;
    elements.selectAllCheckbox.indeterminate = someChecked && !allChecked;
}

// Download Functions
async function startDownload() {
    if (selectedItemIds.size === 0) return;
    
    const options = {
        videos: true,
        articles: true,
        pdfs: true,
        audio: true,
        transcripts: true
    };
    
    // Show progress
    elements.progressOverlay.style.display = 'flex';
    elements.progressBar.style.width = '0%';
    elements.progressBar.textContent = '0%';
    elements.progressText.textContent = 'Starting download...';
    elements.progressLog.innerHTML = '';
    
    try {
        const response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                item_ids: Array.from(selectedItemIds),
                options: options
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            logProgress('error', data.error);
            return;
        }
        
        // Connect to SSE
        const eventSource = new EventSource(`/api/progress/${data.session_id}`);
        
        eventSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            
            switch (msg.type) {
                case 'progress':
                    const percent = Math.round(msg.percent || 0);
                    elements.progressBar.style.width = `${percent}%`;
                    elements.progressBar.textContent = `${percent}%`;
                    elements.progressText.textContent = msg.message;
                    break;
                    
                case 'status':
                    logProgress('info', msg.message);
                    break;
                    
                case 'warning':
                    logProgress('warning', msg.message);
                    break;
                    
                case 'error':
                    logProgress('error', msg.message);
                    eventSource.close();
                    break;
                    
                case 'complete':
                    elements.progressBar.style.width = '100%';
                    elements.progressBar.textContent = '100%';
                    elements.progressText.textContent = msg.message;
                    logProgress('success', `Downloads saved to: ${msg.folder}`);
                    eventSource.close();
                    
                    setTimeout(() => {
                        elements.progressOverlay.style.display = 'none';
                    }, 5000);
                    break;
            }
        };
        
        eventSource.onerror = () => {
            logProgress('error', 'Connection lost');
            eventSource.close();
        };
        
    } catch (error) {
        logProgress('error', 'Failed to start download: ' + error.message);
    }
}

// Helpers
function showStatus(section, type, message) {
    const statusEl = section === 'config' ? elements.configStatus : elements.indexStatus;
    statusEl.className = `status-message ${type}`;
    statusEl.textContent = message;
    
    if (type === 'success' || type === 'info') {
        setTimeout(() => {
            statusEl.className = 'status-message';
        }, 5000);
    }
}

function logProgress(type, message) {
    const p = document.createElement('p');
    p.className = type;
    p.textContent = message;
    elements.progressLog.appendChild(p);
    elements.progressLog.scrollTop = elements.progressLog.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
