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
    downloadNewBtn: document.getElementById('download-new-btn'),
    
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
    
    // Ensure backend knows the current site selection
    await syncActiveSite();
});

// Helper to sync current dropdown selection with backend
async function syncActiveSite() {
    if (!currentSite) return;
    
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active_site: currentSite.id })
        });
        console.log('Backend synced to site:', currentSite.name);
    } catch (error) {
        console.error('Failed to sync active site:', error);
    }
}

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
    elements.downloadNewBtn.addEventListener('click', downloadAllNew);
    
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
    
    console.log('Site changed to:', currentSite?.name, '(id:', siteId, ')');
    
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
        
        // Use current dropdown value if set, otherwise use backend's active_site
        const currentDropdownValue = elements.siteSelect.value;
        const activeSite = currentDropdownValue || config.active_site || 'eurodollar';
        
        // Only update dropdown if it's not already set correctly
        if (elements.siteSelect.value !== activeSite) {
            elements.siteSelect.value = activeSite;
        }
        
        // IMPORTANT: Update currentSite based on dropdown value
        currentSite = sites.find(s => s.id === elements.siteSelect.value);
        
        console.log('Current site set to:', currentSite?.name, '(id:', elements.siteSelect.value, ')');
        updateSiteUI();
        
        // Load site-specific config for the CURRENT dropdown selection
        const siteConfig = config.sites?.[activeSite] || {};
        
        console.log(`Loading config for site: ${activeSite}`, siteConfig);
        
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
    const siteId = elements.siteSelect.value;
    const config = {
        site_id: siteId,
        active_site: siteId,  // Also update active_site to match
        email: elements.emailInput.value.trim(),
        password: elements.passwordInput.value,
        download_dir: elements.downloadDirInput.value.trim(),
        export_to_kc: elements.exportToKcCheckbox.checked,
        knowledge_chipper_dir: elements.kcDirInput.value.trim()
    };
    
    console.log(`Saving config for site: ${siteId}`, config);
    
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
    if (!currentSite) {
        showStatus('index', 'error', 'Please select a site first.');
        return;
    }
    
    console.log('Indexing content for site:', currentSite.name, '(id:', currentSite.id, ')');
    
    elements.indexBtn.disabled = true;
    elements.indexBtn.textContent = 'Scanning...';
    showStatus('index', 'info', `Scanning ${currentSite.name}... This may take a minute.`);
    
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
            elements.downloadNewBtn.disabled = false;
        } else {
            elements.noContent.style.display = 'block';
            elements.contentTable.style.display = 'none';
            elements.downloadNewBtn.disabled = true;
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
    const progressTitle = document.getElementById('progress-modal-title');
    if (progressTitle) progressTitle.textContent = 'Downloading...';
    
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

async function downloadAllNew() {
    if (!currentSite || contentItems.length === 0) {
        alert('Please scan content first before using "Download All New"');
        return;
    }
    
    // Get download directory from config
    const downloadDir = elements.downloadDirInput.value.trim() || `./downloads/${currentSite.id}`;
    
    // Show progress
    const progressTitle = document.getElementById('progress-modal-title');
    if (progressTitle) progressTitle.textContent = 'Checking local content...';
    
    elements.progressOverlay.style.display = 'flex';
    elements.progressBar.style.width = '0%';
    elements.progressBar.textContent = 'Scanning...';
    elements.progressText.textContent = 'Scanning local folder for existing content...';
    elements.progressLog.innerHTML = '';
    
    try {
        // Call backend to check what's new and download
        const response = await fetch('/api/download-new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                site_id: currentSite.id,
                search_dir: downloadDir
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            logProgress('error', data.error);
            elements.progressOverlay.style.display = 'none';
            return;
        }
        
        // Connect to SSE for progress
        const eventSource = new EventSource(`/api/progress/${data.session_id}`);
        
        eventSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            
            if (msg.type === 'status') {
                elements.progressText.textContent = msg.message;
                logProgress('info', msg.message);
            } else if (msg.type === 'info') {
                logProgress('info', msg.message);
            } else if (msg.type === 'success') {
                logProgress('success', msg.message);
            } else if (msg.type === 'progress') {
                elements.progressText.textContent = msg.message;
                if (msg.percent) {
                    elements.progressBar.style.width = `${msg.percent}%`;
                    elements.progressBar.textContent = `${Math.round(msg.percent)}%`;
                }
            } else if (msg.type === 'warning') {
                logProgress('warning', msg.message);
            } else if (msg.type === 'error') {
                logProgress('error', msg.message);
                eventSource.close();
                setTimeout(() => {
                    elements.progressOverlay.style.display = 'none';
                }, 3000);
            } else if (msg.type === 'complete') {
                logProgress('success', msg.message);
                if (msg.summary) {
                    logProgress('info', `Total indexed: ${msg.summary.indexed}`);
                    logProgress('info', `Already had: ${msg.summary.local}`);
                    logProgress('success', `Downloaded: ${msg.summary.downloaded}`);
                }
                eventSource.close();
                
                setTimeout(() => {
                    elements.progressOverlay.style.display = 'none';
                }, 5000);
            }
        };
        
        eventSource.onerror = () => {
            logProgress('error', 'Connection lost');
            eventSource.close();
            elements.progressOverlay.style.display = 'none';
        };
        
    } catch (error) {
        logProgress('error', 'Error: ' + error.message);
        elements.progressOverlay.style.display = 'none';
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

// ========================================
// Tab Management
// ========================================

function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.getAttribute('data-tab');
            
            // Update active tab button
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Show corresponding tab content
            tabContents.forEach(content => {
                if (content.getAttribute('data-tab') === tabName) {
                    content.classList.add('active');
                    content.style.display = 'block';
                } else {
                    content.classList.remove('active');
                    content.style.display = 'none';
                }
            });
            
            // Load data for specific tabs
            if (tabName === 'private-rss') {
                loadPrivateFeeds();
            } else if (tabName === 'sync') {
                loadSyncFolder();
            }
        });
    });
}

// Call setupTabs after DOM content loaded
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
});

// ========================================
// Private RSS Feeds Management
// ========================================

async function loadPrivateFeeds() {
    try {
        const response = await fetch('/api/private-feeds');
        const data = await response.json();
        const feeds = data.feeds || [];
        
        const feedsList = document.getElementById('feeds-list');
        const noFeeds = document.getElementById('no-feeds');
        
        if (feeds.length === 0) {
            feedsList.innerHTML = '';
            noFeeds.style.display = 'block';
        } else {
            noFeeds.style.display = 'none';
            feedsList.innerHTML = feeds.map(feed => `
                <div class="feed-item" data-feed-id="${escapeHtml(feed.id)}">
                    <div class="feed-header">
                        <div>
                            <div class="feed-title">${escapeHtml(feed.name)}</div>
                            ${feed.author ? `<div class="feed-author">by ${escapeHtml(feed.author)}</div>` : ''}
                        </div>
                        <div class="feed-actions">
                            <button class="btn-icon delete" onclick="deletePrivateFeed('${escapeHtml(feed.id)}')">Delete</button>
                        </div>
                    </div>
                    <div class="feed-url">${escapeHtml(feed.url)}</div>
                    <div class="feed-meta">
                        <span>Added: ${escapeHtml(feed.added_date || 'Unknown')}</span>
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Failed to load private feeds:', error);
        showStatus('add-feed-status', 'Failed to load feeds: ' + error.message, 'error');
    }
}

async function addPrivateFeed() {
    const nameInput = document.getElementById('feed-name');
    const urlInput = document.getElementById('feed-url');
    const authorInput = document.getElementById('feed-author');
    const statusDiv = document.getElementById('add-feed-status');
    
    const name = nameInput.value.trim();
    const url = urlInput.value.trim();
    const author = authorInput.value.trim();
    
    if (!name || !url) {
        showStatus('add-feed-status', 'Please enter both feed name and URL', 'error');
        return;
    }
    
    try {
        showStatus('add-feed-status', 'Validating RSS feed...', 'info');
        
        const response = await fetch('/api/private-feeds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url, author })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showStatus('add-feed-status', '✓ Feed added successfully!', 'success');
            nameInput.value = '';
            urlInput.value = '';
            authorInput.value = '';
            loadPrivateFeeds();
        } else {
            showStatus('add-feed-status', data.error || 'Failed to add feed', 'error');
        }
    } catch (error) {
        showStatus('add-feed-status', 'Error: ' + error.message, 'error');
    }
}

async function deletePrivateFeed(feedId) {
    if (!confirm('Are you sure you want to delete this feed?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/private-feeds/${feedId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadPrivateFeeds();
        } else {
            const data = await response.json();
            alert('Failed to delete feed: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// Setup private RSS feed event listeners
document.addEventListener('DOMContentLoaded', () => {
    const addFeedBtn = document.getElementById('add-feed-btn');
    if (addFeedBtn) {
        addFeedBtn.addEventListener('click', addPrivateFeed);
    }
});

// ========================================
// Sync All Sources
// ========================================

async function startSync() {
    const startSyncBtn = document.getElementById('start-sync-btn');
    const syncStatus = document.getElementById('sync-status');
    const syncResults = document.getElementById('sync-results');
    const syncFolder = document.getElementById('sync-folder');
    
    // Get the folder to check
    const searchDir = syncFolder.value.trim() || './downloads';
    
    // Save folder for next time
    saveSyncFolder(searchDir);
    
    startSyncBtn.disabled = true;
    syncResults.style.display = 'none';
    
    // Show progress overlay (same as download progress)
    const progressTitle = document.getElementById('progress-modal-title');
    if (progressTitle) progressTitle.textContent = 'Syncing All Sources...';
    
    elements.progressOverlay.style.display = 'flex';
    elements.progressBar.style.width = '0%';
    elements.progressBar.textContent = 'Starting...';
    elements.progressText.textContent = 'Initializing sync...';
    elements.progressLog.innerHTML = '';
    
    try {
        const response = await fetch('/api/sync-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                search_dir: searchDir
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            logProgress('error', data.error);
            elements.progressOverlay.style.display = 'none';
            showStatus('sync-status', data.error, 'error');
            startSyncBtn.disabled = false;
            return;
        }
        
        // Connect to SSE for progress updates
        const eventSource = new EventSource(`/api/progress/${data.session_id}`);
        
        eventSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            
            if (msg.type === 'status') {
                elements.progressText.textContent = msg.message;
                logProgress('info', msg.message);
                
                // Update progress bar based on source progress
                if (msg.source_progress && msg.total_sources) {
                    const percent = (msg.source_progress / msg.total_sources) * 100;
                    elements.progressBar.style.width = `${percent}%`;
                    elements.progressBar.textContent = `${Math.round(percent)}%`;
                }
            } else if (msg.type === 'info') {
                logProgress('info', msg.message);
            } else if (msg.type === 'success') {
                logProgress('success', msg.message);
            } else if (msg.type === 'progress') {
                elements.progressText.textContent = msg.message;
                if (msg.percent) {
                    elements.progressBar.style.width = `${msg.percent}%`;
                    elements.progressBar.textContent = `${Math.round(msg.percent)}%`;
                }
            } else if (msg.type === 'warning') {
                logProgress('warning', msg.message);
            } else if (msg.type === 'error') {
                logProgress('error', msg.message);
                eventSource.close();
                elements.progressOverlay.style.display = 'none';
                showStatus('sync-status', msg.message, 'error');
                startSyncBtn.disabled = false;
            } else if (msg.type === 'complete') {
                logProgress('success', msg.message);
                eventSource.close();
                
                // Hide progress overlay after a brief delay
                setTimeout(() => {
                    elements.progressOverlay.style.display = 'none';
                }, 2000);
                
                // Display results
                if (msg.results) {
                    displaySyncResults(msg.results);
                    showStatus('sync-status', `✓ Sync completed! Scanned folder: ${searchDir}`, 'success');
                }
                
                startSyncBtn.disabled = false;
            }
        };
        
        eventSource.onerror = (error) => {
            console.error('SSE Error:', error);
            eventSource.close();
            elements.progressOverlay.style.display = 'none';
            showStatus('sync-status', 'Connection error during sync', 'error');
            startSyncBtn.disabled = false;
        };
        
    } catch (error) {
        elements.progressOverlay.style.display = 'none';
        showStatus('sync-status', 'Error: ' + error.message, 'error');
        startSyncBtn.disabled = false;
    }
}

function displaySyncResults(results) {
    const syncResults = document.getElementById('sync-results');
    const syncSummary = document.getElementById('sync-summary');
    
    if (!results.details || results.details.length === 0) {
        syncSummary.innerHTML = `
            <div class="empty-state">
                <p><strong>No sources were found or all sources failed to index.</strong></p>
                <p>This could happen if:</p>
                <ul style="text-align: left; margin: 1rem 0;">
                    <li>Network connection issues prevented fetching RSS feeds</li>
                    <li>All podcast sites are temporarily unavailable</li>
                </ul>
                <p>Try again in a few minutes.</p>
            </div>
        `;
        syncResults.style.display = 'block';
        return;
    }
    
    let totalDownloaded = 0;
    let totalSkipped = 0;
    let totalErrors = 0;
    
    const itemsHtml = results.details.map(source => {
        const downloadedCount = source.downloaded || 0;
        const downloadErrors = source.download_errors || 0;
        totalDownloaded += downloadedCount;
        totalSkipped += (source.local || 0);
        totalErrors += downloadErrors;
        
        let statusText = '';
        if (downloadedCount > 0) {
            statusText = `✓ ${downloadedCount} downloaded`;
            if (downloadErrors > 0) {
                statusText += ` (${downloadErrors} errors)`;
            }
        } else if (source.error) {
            statusText = `❌ Error: ${source.error}`;
        } else {
            statusText = 'Up to date';
        }
        
        return `
            <div class="sync-item ${downloadedCount > 0 ? 'has-new' : 'no-new'}">
                <span class="sync-item-source">${escapeHtml(source.source_name)}</span>
                <span class="sync-item-count">${statusText}</span>
            </div>
        `;
    }).join('');
    
    syncSummary.innerHTML = `
        ${itemsHtml}
        <div class="sync-totals">
            <div class="sync-total-item">
                <span class="sync-total-value">${totalDownloaded}</span>
                <span class="sync-total-label">Downloaded</span>
            </div>
            <div class="sync-total-item">
                <span class="sync-total-value">${totalSkipped}</span>
                <span class="sync-total-label">Already Had</span>
            </div>
            <div class="sync-total-item">
                <span class="sync-total-value">${totalErrors}</span>
                <span class="sync-total-label">Errors</span>
            </div>
        </div>
    `;
    
    syncResults.style.display = 'block';
}

// Load saved sync folder on tab switch
function loadSyncFolder() {
    const syncFolder = document.getElementById('sync-folder');
    if (syncFolder) {
        // Load from localStorage
        const savedFolder = localStorage.getItem('crawlavator_sync_folder');
        if (savedFolder) {
            syncFolder.value = savedFolder;
        }
    }
}

// Save sync folder to localStorage
function saveSyncFolder(folder) {
    if (folder && folder.trim()) {
        localStorage.setItem('crawlavator_sync_folder', folder.trim());
    }
}

// Setup sync event listeners
document.addEventListener('DOMContentLoaded', () => {
    const startSyncBtn = document.getElementById('start-sync-btn');
    if (startSyncBtn) {
        startSyncBtn.addEventListener('click', startSync);
    }
    
    const viewLogBtn = document.getElementById('view-sync-log-btn');
    if (viewLogBtn) {
        viewLogBtn.addEventListener('click', () => {
            // Open log file in new window or download
            window.open('/downloads/sync_log.jsonl', '_blank');
        });
    }
    
    // Load saved folder when page loads
    loadSyncFolder();
});
