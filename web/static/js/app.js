// NovelMaster WebUI JavaScript v2.0

// ==================== 全局状态 ====================
let currentBook = null;
let currentChapter = null;
let providersData = null;
let providerTemplates = {};
let isTaskRunning = false;
let chatHistory = [];  // 对话历史
let chatSessionId = null;  // 当前对话会话ID
let currentTaskId = null;
let taskPollInterval = null;
let lockedChapters = {};  // {chapterNum: taskId}
let autoSaveTimer = null;  // 自动保存定时器
const AUTO_SAVE_INTERVAL = 30000;  // 30秒自动保存一次

// ==================== 页面切换 ====================

// 初始化页面状态
async function initPageState() {
    // 获取书籍列表
    const res = await api('/api/books');
    
    if (res.success && res.books && res.books.length > 0) {
        // 有书籍，自动进入写作页面
        // 优先使用上次选择的书籍
        const lastBookId = localStorage.getItem('lastSelectedBookId');
        let bookToSelect = res.books[0];
        
        if (lastBookId) {
            const lastBook = res.books.find(b => b.id === lastBookId);
            if (lastBook) bookToSelect = lastBook;
        }
        
        await selectBook(bookToSelect.id, true);
    } else {
        // 没有书籍，显示书籍管理页
        showBookManagerPage();
    }
}

// 显示书籍管理页
function showBookManagerPage() {
    const bookManagerPage = document.getElementById('book-manager-page');
    const writingPage = document.getElementById('writing-page');
    const navBackBtn = document.getElementById('btn-back-to-manager-nav');
    const resizeHandle = document.getElementById('resize-handle');

    if (bookManagerPage) bookManagerPage.style.display = 'block';
    if (writingPage) writingPage.style.display = 'none';
    // 隐藏顶部导航栏的返回按钮
    if (navBackBtn) navBackBtn.style.display = 'none';
    // 隐藏分隔条（书籍管理页不需要）
    if (resizeHandle) resizeHandle.style.display = 'none';

    // 加载书籍列表
    loadBookManagerList();
}

// 显示写作页面
function showWritingPage() {
    const bookManagerPage = document.getElementById('book-manager-page');
    const writingPage = document.getElementById('writing-page');
    const navBackBtn = document.getElementById('btn-back-to-manager-nav');
    const resizeHandle = document.getElementById('resize-handle');

    if (bookManagerPage) bookManagerPage.style.display = 'none';
    if (writingPage) writingPage.style.display = 'flex';
    // 显示顶部导航栏的返回按钮
    if (navBackBtn) navBackBtn.style.display = 'inline-flex';
    // 显示分隔条
    if (resizeHandle) resizeHandle.style.display = 'block';
}

// 返回书籍管理页
function goBackToBookManager() {
    // 清空当前书籍
    currentBook = null;
    currentChapter = null;
    chatHistory = [];
    chatSessionId = null;
    
    // 清空对话区域
    const messages = document.getElementById('chat-messages');
    if (messages) {
        messages.innerHTML = `
            <div class="chat-welcome" id="chat-welcome">
                <div class="welcome-icon">📝</div>
                <h2>欢迎使用 NovelMaster</h2>
                <p>开始一场创作之旅</p>
                <div class="welcome-actions">
                    <button class="btn btn-primary" onclick="startNewBook()">
                        📚 创建新书
                    </button>
                    <button class="btn btn-secondary" onclick="selectExistingBook()">
                        📖 选择已有书籍
                    </button>
                </div>
                <div class="welcome-tips">
                    <p>💡 你可以随时在下方输入框中输入指令，与AI进行创作对话</p>
                </div>
            </div>
        `;
    }
    
    // 隐藏章节列表区域
    const chapterListSection = document.getElementById('chapter-list-section');
    if (chapterListSection) chapterListSection.style.display = 'none';

    // 隐藏书籍信息区域
    const bookInfoSection = document.getElementById('book-info-section');
    if (bookInfoSection) bookInfoSection.style.display = 'none';

    // 清除localStorage中的书籍选择
    localStorage.removeItem('lastSelectedBookId');
    
    // 隐藏分隔条（书籍管理页不需要）
    const resizeHandle = document.getElementById('resize-handle');
    if (resizeHandle) resizeHandle.style.display = 'none';
    
    // 显示书籍管理页
    showBookManagerPage();
}

// ==================== 书籍管理列表 ====================

// 加载书籍管理列表
async function loadBookManagerList() {
    const res = await api('/api/books');
    const tbody = document.getElementById('book-manager-table-body');
    const emptyDiv = document.getElementById('book-manager-empty');
    const wrapper = document.querySelector('.book-manager-table-wrapper');
    
    if (!tbody) return;
    
    if (!res.success || !res.books || res.books.length === 0) {
        tbody.innerHTML = '';
        if (emptyDiv) emptyDiv.style.display = 'block';
        if (wrapper) wrapper.style.display = 'none';
        return;
    }
    
    if (emptyDiv) emptyDiv.style.display = 'none';
    if (wrapper) wrapper.style.display = 'table';
    
    // 获取每个书籍的统计信息
    let html = '';
    for (const book of res.books) {
        // 获取章节信息
        const chaptersRes = await api(`/api/books/${book.id}/chapters`);
        let totalWords = 0;
        let chapterCount = 0;
        let latestChapter = '-';
        
        if (chaptersRes.success && chaptersRes.chapters) {
            chapterCount = chaptersRes.chapters.length;
            // 计算总字数
            totalWords = chaptersRes.chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0);
            // 获取最新章节名
            if (chaptersRes.chapters.length > 0) {
                const latest = chaptersRes.chapters.reduce((a, b) => a.number > b.number ? a : b);
                latestChapter = latest.title || `第${latest.number}章`;
            }
        }
        
        const planWords = book.words_per_chapter ? `${book.words_per_chapter}字` : '-';
        
        html += `
            <tr>
                <td class="book-name-cell">${escapeHtml(book.name)}</td>
                <td>${escapeHtml(book.genre || '-')}</td>
                <td>${escapeHtml(book.platform || '-')}</td>
                <td>${planWords}</td>
                <td>${chapterCount} 章</td>
                <td class="word-count">${formatNumber(totalWords)} 字</td>
                <td class="latest-chapter" title="${escapeHtml(latestChapter)}">${escapeHtml(latestChapter)}</td>
                <td class="book-manager-actions-cell">
                    <button class="btn btn-sm btn-primary" onclick="selectBookFromManager('${book.id}')">打开</button>
                    <button class="btn btn-sm btn-secondary" onclick="renameBookFromManager('${book.id}', '${escapeHtml(book.name)}')">改名</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteBookFromManager('${book.id}', '${escapeHtml(book.name)}')">删除</button>
                </td>
            </tr>
        `;
    }
    
    tbody.innerHTML = html;
}

// 从书籍管理页选择书籍
async function selectBookFromManager(bookId) {
    await selectBook(bookId, true);
    showWritingPage();
    addSystemMessage(`已选择书籍《${currentBook.name}》，可以开始创作了。`);
}

// 从书籍管理页删除书籍
async function deleteBookFromManager(bookId, bookName) {
    if (!confirm(`确定要删除书籍《${bookName}》吗？\n此操作不可恢复！`)) {
        return;
    }
    
    const res = await api(`/api/books/${bookId}`, { method: 'DELETE' });
    
    if (res.success) {
        addSystemMessage(`✅ 书籍《${bookName}》已删除`);
        await loadBookManagerList();
    } else {
        addSystemMessage(`❌ 删除失败: ${res.message}`);
    }
}

// 从书籍管理页改名书籍
async function renameBookFromManager(bookId, bookName) {
    const newName = prompt('请输入新书名：', bookName);
    if (!newName || newName.trim() === bookName.trim()) {
        return;
    }
    
    if (!newName.trim()) {
        addSystemMessage('❌ 书名不能为空');
        return;
    }
    
    const res = await api(`/api/books/${bookId}/rename`, {
        method: 'PUT',
        body: { new_name: newName.trim() }
    });
    
    if (res.success) {
        addSystemMessage(`✅ 书籍已改名为《${res.new_name}》`);
        await loadBookManagerList();
    } else {
        addSystemMessage(`❌ 改名失败: ${res.detail || res.message}`);
    }
}

// 格式化数字
function formatNumber(num) {
    if (num >= 10000) {
        return (num / 10000).toFixed(1) + '万';
    }
    return num.toLocaleString();
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', async () => {
    // 检查LLM配置状态
    await checkLLMStatus();

    // 初始化页面状态（显示书籍管理页）
    initPageState();

    // 设置输入框事件
    setupChatInput();

    // 初始化分隔条拖动
    initResizeHandle();

    // 初始化章节选择器
    updateChapterHintUI();

    // 页面关闭前自动保存
    window.addEventListener('beforeunload', () => {
        if (chatHistory.length > 0) {
            // 同步保存（可能不完美，但聊胜于无）
            autoSaveChatLog();
        }
    });

    // 定时自动保存（每30秒）
    setInterval(() => {
        if (currentBook && chatHistory.length > 0) {
            autoSaveChatLog();
        }
    }, AUTO_SAVE_INTERVAL);

    // 绑定章节列表点击事件（事件委托）
    document.getElementById('chapter-list')?.addEventListener('click', async (e) => {
        const chapterItem = e.target.closest('.chapter-item[data-chapter-id]');
        if (chapterItem) {
            const chapterId = chapterItem.dataset.chapterId;
            await selectChapter(chapterId);
        }
    });
});

// 恢复上次选中的书籍（已禁用，改为每次打开都显示书籍管理页）
// async function restoreLastSelectedBook() {
//     const lastBookId = localStorage.getItem('lastSelectedBookId');
//     if (lastBookId) {
//         const res = await api(`/api/books/${lastBookId}`);
//         if (res.success) {
//             await selectBook(lastBookId, true);
//         }
//     }
// }

// ==================== 通用API ====================
async function api(url, options = {}) {
    try {
        // 对 URL 中的路径参数进行编码（处理中文 book_id 等）
        const encodedUrl = url.replace(/\/books\/([^/]+)\//g, (match, id) => {
            return `/books/${encodeURIComponent(id)}/`;
        });
        
        // 自动序列化 body 对象为 JSON
        if (options.body && typeof options.body === 'object') {
            options.body = JSON.stringify(options.body);
        }
        
        const res = await fetch(encodedUrl, {
            headers: { 'Content-Type': 'application/json' },
            ...options
        });
        return await res.json();
    } catch (e) {
        console.error('API Error:', e);
        return { success: false, message: e.message };
    }
}

// ==================== LLM状态检查 ====================
async function checkLLMStatus() {
    const res = await api('/api/llm/status');
    if (!res.configured) {
        // LLM未配置，显示设置
        setTimeout(() => showSettings(), 500);
    }
}

// ==================== 欢迎界面 ====================
function initWelcomeView() {
    const chatWelcome = document.getElementById('chat-welcome');
    if (chatWelcome) {
        chatWelcome.style.display = 'flex';
    }
}

function hideWelcomeView() {
    const chatWelcome = document.getElementById('chat-welcome');
    const resizeHandle = document.getElementById('resize-handle');
    if (chatWelcome) {
        chatWelcome.style.display = 'none';
    }
    // 隐藏分隔条（欢迎页不需要）
    if (resizeHandle) {
        resizeHandle.style.display = 'none';
    }
}

// ==================== 书籍管理 ====================

// 更新当前书籍显示
function updateCurrentBookDisplay() {
    const display = document.getElementById('current-book-display');
    const nameEl = document.getElementById('current-book-name');
    
    if (!display || !nameEl) return;
    
    if (currentBook) {
        nameEl.textContent = currentBook.name;
    } else {
        nameEl.textContent = '未选择';
    }
}

// 保留 loadBookList 以兼容其他功能
async function loadBookList() {
    // 不再需要加载书籍列表，更新当前书籍显示即可
    updateCurrentBookDisplay();
}

async function selectBook(bookId, silent = false) {
    const res = await api(`/api/books/${bookId}`);
    if (res.success) {
        currentBook = res.book;
        currentChapter = null;  // 重置当前章节
        selectedTargetChapter = null;  // 重置目标章节
        // 保存到 localStorage
        localStorage.setItem('lastSelectedBookId', bookId);

        await loadBookList();
        await loadChapterList();
        await updateDocStatus();
        updateChapterHintUI();  // 更新章节提示
        updateBookInfoSection();  // 更新书籍信息区域

        // 加载最新的聊天记录
        await loadLatestChatLog();
        
        // 检查是否有正在进行的创建任务
        await checkAndResumeCreatingTask(bookId);
        
        // 显示写作页面
        showWritingPage();

        if (!silent) {
            addSystemMessage(`已选择书籍《${currentBook.name}》，可以开始创作了。`);
        }
    } else {
        console.error('Failed to load book:', res);
        if (!silent) {
            addSystemMessage(`加载书籍失败: ${res.message || '未知错误'}`);
        }
    }
}

// 检查并恢复正在进行的创建任务
async function checkAndResumeCreatingTask(bookId) {
    try {
        const res = await api('/api/tasks');
        if (res.success && res.tasks) {
            // 查找与当前书籍相关的创建任务
            const createTask = res.tasks.find(task => 
                task.type === 'create_book' && 
                task.book_id === bookId &&
                task.status === 'running'
            );
            
            if (createTask) {
                addSystemMessage(`📚 检测到书籍仍在创建中，正在恢复进度...`);
                startTaskPolling(createTask.task_id);
            }
        }
    } catch (e) {
        console.error('检查创建任务失败:', e);
    }
}

// 更新书籍信息区域
function updateBookInfoSection() {
    const bookInfoSection = document.getElementById('book-info-section');
    if (!bookInfoSection || !currentBook) {
        if (bookInfoSection) bookInfoSection.style.display = 'none';
        return;
    }

    bookInfoSection.style.display = 'block';

    // 更新书籍信息
    document.getElementById('book-info-genre').textContent = currentBook.genre || '-';
    document.getElementById('book-info-platform').textContent = currentBook.platform || '-';

    const wordsPerChapter = currentBook.words_per_chapter;
    document.getElementById('book-info-words').textContent = wordsPerChapter ? `${wordsPerChapter}字` : '-';

    const totalChapters = currentBook.total_chapters;
    document.getElementById('book-info-chapters').textContent = totalChapters ? `${totalChapters}章` : '-';
}

// 聊天记录状态
let loadedLogFiles = [];  // 已加载的日志文件
let allLoadedLogs = [];   // 所有已加载的消息
let displayStartIndex = 0; // 当前显示的起始索引
const DEFAULT_DISPLAY_COUNT = 50;  // 默认显示条数

// 加载最新的聊天记录（默认50条）
async function loadLatestChatLog() {
    if (!currentBook) return;
    
    try {
        // 获取聊天日志列表
        const res = await api(`/api/books/${currentBook.id}/chat-logs`);
        if (!res.success || !res.logs || res.logs.length === 0) {
            showWelcomeView();
            return;
        }
        
        // 重置状态
        loadedLogFiles = [];
        allLoadedLogs = [];
        displayStartIndex = 0;
        
        // 优先加载自动保存的文件，如果没有则加载最新的
        let autoLog = res.logs.find(log => log.filename.includes('_auto.json'));
        let logsToLoad = autoLog ? [autoLog] : res.logs.slice(0, 1);
        
        // 收集日志文件的消息
        for (const logFile of logsToLoad) {
            const logRes = await api(`/api/books/${currentBook.id}/chat-logs/${logFile.filename}`);
            if (logRes.success) {
                try {
                    const logData = JSON.parse(logRes.content);
                    if (logData.messages && logData.messages.length > 0) {
                        loadedLogFiles.push({
                            filename: logFile.filename,
                            data: logData
                        });
                        // 合并消息（保持时间顺序）
                        allLoadedLogs = [...allLoadedLogs, ...logData.messages];
                    }
                } catch (e) {
                    console.error('解析聊天记录失败:', e);
                }
            }
        }
        
        if (allLoadedLogs.length === 0) {
            showWelcomeView();
            return;
        }
        
        // 按时间排序（从早到晚）
        allLoadedLogs.sort((a, b) => {
            const timeA = new Date(a.fullTime || a.time);
            const timeB = new Date(b.fullTime || b.time);
            return timeA - timeB;
        });
        
        // 清空当前显示
        const messages = document.getElementById('chat-messages');
        if (messages) messages.innerHTML = '';
        chatHistory = [];
        
        // 恢复session ID
        chatSessionId = loadedLogFiles[0]?.data.sessionId || new Date().getTime().toString(36);
        
        // 只显示最新的50条
        displayStartIndex = Math.max(0, allLoadedLogs.length - DEFAULT_DISPLAY_COUNT);
        const messagesToShow = allLoadedLogs.slice(displayStartIndex);
        
        hideWelcomeView();
        
        for (const msg of messagesToShow) {
            renderMessage(msg.type, msg.content, msg.time);
            chatHistory.push(msg);
        }
        
        // 添加"加载更多"按钮（如果有更早的记录）
        if (displayStartIndex > 0) {
            addLoadMoreButton();
        }
        
        // 滚动到底部
        if (messages) {
            messages.scrollTop = messages.scrollHeight;
        }
        
        // 保存提示
        const totalCount = allLoadedLogs.length;
        if (totalCount > DEFAULT_DISPLAY_COUNT) {
            addSystemMessage(`已加载最近 ${DEFAULT_DISPLAY_COUNT}/${totalCount} 条记录`);
        }
    } catch (e) {
        console.error('加载聊天记录失败:', e);
        showWelcomeView();
    }
}

// 添加"加载更多"按钮
function addLoadMoreButton() {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    
    // 移除已存在的按钮
    const existingBtn = messages.querySelector('.load-more-btn');
    if (existingBtn) existingBtn.remove();
    
    const remaining = displayStartIndex;
    const html = `
        <div class="load-more-container">
            <button class="btn btn-sm load-more-btn" onclick="loadMoreMessages()">
                📜 加载更多（还有 ${remaining} 条）
            </button>
        </div>
    `;
    
    messages.insertAdjacentHTML('afterbegin', html);
}

// 加载更多消息
async function loadMoreMessages() {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    
    // 移除加载按钮
    const btn = messages.querySelector('.load-more-btn');
    if (btn) btn.remove();
    
    // 计算新的显示范围
    const newStartIndex = Math.max(0, displayStartIndex - DEFAULT_DISPLAY_COUNT);
    const messagesToShow = allLoadedLogs.slice(newStartIndex, displayStartIndex);
    
    // 在顶部插入消息
    const firstMsg = messages.querySelector('.chat-message');
    for (const msg of messagesToShow.reverse()) {
        renderMessage(msg.type, msg.content, msg.time, true);
        chatHistory.unshift(msg);
    }
    
    displayStartIndex = newStartIndex;
    
    // 添加新的"加载更多"按钮
    if (displayStartIndex > 0) {
        addLoadMoreButton();
    }
    
    // 滚动到加载的位置
    messages.scrollTop = firstMsg ? (firstMsg.offsetTop - 20) : 0;
}

// 直接渲染消息到DOM
function renderMessage(type, content, time, prepend = false) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;

    const now = time ? new Date(time) : new Date();
    const timeStr = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

    let avatar, name;
    switch(type) {
        case 'user':
            avatar = '👤';
            name = '你';
            break;
        case 'ai':
            avatar = '🤖';
            name = 'AI助手';
            break;
        case 'system':
            avatar = 'ℹ️';
            name = '系统';
            break;
        default:
            avatar = '💬';
            name = '消息';
    }

    const html = `
        <div class="chat-message ${type}">
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-name">${name}</span>
                    <span class="message-time">${timeStr}</span>
                </div>
                <div class="message-body">
                    ${formatMessageContent(content)}
                </div>
            </div>
        </div>
    `;

    if (prepend) {
        // 在"加载更多"按钮后插入
        const loadMoreContainer = messages.querySelector('.load-more-container');
        if (loadMoreContainer) {
            loadMoreContainer.insertAdjacentHTML('afterend', html);
        } else {
            messages.insertAdjacentHTML('afterbegin', html);
        }
    } else {
        messages.insertAdjacentHTML('beforeend', html);
    }
}

function startNewBook() {
    document.getElementById('create-book-modal').classList.add('show');
}

function closeCreateBook() {
    document.getElementById('create-book-modal').classList.remove('show');
}



function selectExistingBook() {
    // 滚动到书籍管理页的书籍列表
    document.getElementById('book-manager-table-body')?.closest('.book-manager-list-section')?.scrollIntoView({ behavior: 'smooth' });
}

function showCreateBook() {
    document.getElementById('create-book-modal').classList.add('show');
}

// ==================== 导航栏操作处理 ====================
document.addEventListener('click', async (e) => {
    const navItem = e.target.closest('.nav-item[data-action]');
    if (!navItem) return;
    
    const action = navItem.dataset.action;
    
    switch (action) {
        case 'select-book':
            // 滚动到书籍列表
            document.getElementById('book-list')?.scrollIntoView({ behavior: 'smooth' });
            break;
        case 'manage-books':
            // 显示书籍列表并刷新
            await loadBookList();
            document.getElementById('book-list')?.scrollIntoView({ behavior: 'smooth' });
            break;
    }
});

// ==================== 对话功能 ====================
function setupChatInput() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    
    // 自动调整高度
    input.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
    
    // Ctrl+Enter 发送
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
}

function addUserMessage(content) {
    addMessage('user', content);
}

function addAIMessage(content) {
    // 过滤掉 AI 思考过程内容
    content = filterAIContent(content);
    addMessage('ai', content);
}

function addSystemMessage(content) {
    addMessage('system', content);
}

// ==================== 引导功能 ====================

// 标准工作流定义
const workflowSteps = {
    'planning': { name: '创作简报', icon: '📋', next: 'story_bible' },
    'story_bible': { name: '世界观设定', icon: '🌍', next: 'book_rules' },
    'book_rules': { name: '书籍规则', icon: '📜', next: 'chapter_outline' },
    'chapter_outline': { name: '章节大纲', icon: '📑', next: 'write' },
    'write': { name: '创作章节', icon: '✍️', next: null }
};

// 步骤顺序
const stepOrder = ['planning', 'story_bible', 'book_rules', 'chapter_outline', 'write'];

// 获取当前工作流进度
async function getWorkflowProgress() {
    if (!currentBook) return null;

    const res = await api(`/api/books/${currentBook.id}`);
    if (!res.success) return null;

    const book = res.book;
    const progress = [];

    // 检查每一步是否完成
    for (const step of stepOrder) {
        let exists = false;
        if (step === 'write') {
            // 检查是否有章节
            const chaptersRes = await api(`/api/books/${currentBook.id}/chapters`);
            exists = chaptersRes.success && chaptersRes.chapters && chaptersRes.chapters.length > 0;
        } else {
            const docKey = step + '_exists';
            exists = book[docKey] === true;
        }
        progress.push({ key: step, ...workflowSteps[step], completed: exists });
    }

    return progress;
}

// 显示引导提示
async function showGuidance(context, currentDocKey = null) {
    if (!currentBook) return;

    const progress = await getWorkflowProgress();
    if (!progress) return;

    // 找出下一步
    const nextStep = progress.find(p => !p.completed);
    if (!nextStep) {
        // 所有步骤都完成了，检查是否有章节
        const chaptersRes = await api(`/api/books/${currentBook.id}/chapters`);
        const hasChapters = chaptersRes.success && chaptersRes.chapters && chaptersRes.chapters.length > 0;
        
        if (hasChapters) {
            // 有章节，显示续写/评审引导
            addAIMessage(`📚 书籍《${currentBook.name}》已就绪，输入"续写"开始创作下一章`);
        } else {
            // 没有章节，显示新书引导
            addAIMessage(`🎉 基础设定已完成，输入"续写"开始创作正文`);
        }
        return;
    }

    // 根据上下文生成不同的引导
    let guidance = '';
    const currentStep = progress.find(p => p.completed);
    const currentStepIndex = currentStep ? stepOrder.indexOf(currentStep.key) : -1;

    if (context === 'task_completed') {
        if (nextStep.key === 'story_bible') {
            guidance = `🌍 输入"生成世界观"创建故事背景`;
        } else if (nextStep.key === 'book_rules') {
            guidance = `📖 输入"生成规则"创建创作规则`;
        } else if (nextStep.key === 'chapter_outline') {
            guidance = `📜 输入"生成大纲"创建章节大纲`;
        } else if (nextStep.key === 'write') {
            guidance = `✍️ 输入"续写"开始创作正文`;
        }
    } else if (context === 'chapter_completed') {
        guidance = `✍️ 章节创作完成！输入"续写"继续，输入"评审"检查质量`;
    } else if (context === 'doc_viewed') {
        // 查看了某个文档后的引导
        if (!nextStep) {
            // 所有步骤都完成了
            guidance = `🎉 全部设定完成，输入"续写"开始正文创作`;
        } else {
            guidance = `✅ 继续输入"${nextStep.key === 'write' ? '续写' : '继续'}"进行下一步`;
        }
    }

    if (guidance) {
        addAIMessage(guidance);
    }
}

function addMessage(type, content) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;

    hideWelcomeView();

    const now = new Date();
    const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const fullTime = now.toLocaleString('zh-CN');

    // 初始化会话ID
    if (!chatSessionId) {
        chatSessionId = now.getTime().toString(36);
    }

    let avatar, name;
    switch(type) {
        case 'user':
            avatar = '👤';
            name = '你';
            break;
        case 'ai':
            avatar = '🤖';
            name = 'AI助手';
            break;
        case 'system':
            avatar = 'ℹ️';
            name = '系统';
            break;
    }

    const html = `
        <div class="chat-message ${type}">
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-name">${name}</span>
                    <span class="message-time">${time}</span>
                </div>
                <div class="message-body">
                    ${formatMessageContent(content)}
                </div>
            </div>
        </div>
    `;

    messages.insertAdjacentHTML('beforeend', html);
    messages.scrollTop = messages.scrollHeight;

    // 保存完整信息到历史
    chatHistory.push({
        type,
        content,
        time,
        fullTime,
        sessionId: chatSessionId,
        bookId: currentBook?.id,
        bookName: currentBook?.name,
        chapterId: currentChapter?.id,
        chapterNum: currentChapter?.number
    });

    // 触发自动保存
    triggerAutoSave();
}

// 显示章节简报
function displayChapterBrief(brief) {
    if (!brief) return;

    let briefDetail = `\n📋 **第${brief.chapter_num}章 章节简报**\n`;

    // 当前状态
    if (brief.current_state) {
        briefDetail += `\n📍 **当前状态**：${brief.current_state}`;
    }

    // 伏笔信息
    if (brief.pending_hooks && brief.pending_hooks.length > 0) {
        briefDetail += `\n\n🎯 **待回收伏笔**（${brief.pending_hooks.length}条）：\n`;
        brief.pending_hooks.slice(0, 5).forEach(hook => {
            briefDetail += `- ${hook.id}：${hook.content.substring(0, 40)}${hook.content.length > 40 ? '...' : ''} [${hook.status}]\n`;
        });
        if (brief.pending_hooks.length > 5) {
            briefDetail += `- ...还有${brief.pending_hooks.length - 5}条伏笔\n`;
        }
    } else {
        briefDetail += `\n🎯 **伏笔**：暂无待回收伏笔`;
    }

    // 资源摘要
    if (brief.particle_summary && brief.particle_summary.length > 0) {
        briefDetail += `\n\n💰 **资源变化**：\n`;
        brief.particle_summary.slice(0, 3).forEach(item => {
            briefDetail += `${item}\n`;
        });
    }

    briefDetail += `\n---\n💡 输入"续写"继续创作下一章`;

    addAIMessage(briefDetail);
}

// 显示完整评审报告
function displayAuditReport(reportContent) {
    if (!reportContent) return;

    // 将markdown格式的报告转换为可显示的内容
    let report = `\n📊 **章节评审报告**\n`;
    report += `━━━━━━━━━━━━━━━━━━━━\n`;

    // 简化展示，只显示关键信息
    const lines = reportContent.split('\n');
    let skipSection = false;
    let showCoreIssues = false;

    for (const line of lines) {
        // 跳过标题行
        if (line.startsWith('# ')) continue;

        // 标记核心漏洞部分
        if (line.includes('核心漏洞')) {
            showCoreIssues = true;
            report += `\n🔴 **核心漏洞**：\n`;
            continue;
        }

        // 跳过问题列表标题
        if (line.includes('问题列表') || line.includes('质量指标')) continue;

        // 处理核心漏洞
        if (showCoreIssues) {
            if (line.trim().startsWith('-') || (line.includes('[') && line.includes(']'))) {
                report += `   ${line.trim()}\n`;
            } else if (line.trim() === '' || line.trim().startsWith('##') || line.trim().startsWith('无')) {
                showCoreIssues = false;
            }
            continue;
        }

        // 处理评分概览表格行
        if (line.includes('|')) {
            if (line.includes('综合评分') || line.includes('决策')) {
                const parts = line.split('|').filter(p => p.trim());
                if (parts.length >= 2) {
                    const label = parts[0].replace(/\*\*/g, '').trim();
                    const value = parts[1].replace(/\*\*/g, '').trim();
                    report += `• ${label}：${value}\n`;
                }
            }
            continue;
        }

        // 处理问题项
        if (line.match(/^\d+\./) || line.includes('🔴') || line.includes('🟡') || line.includes('🟢')) {
            report += `${line.trim()}\n`;
        }

        // 处理修订建议
        if (line.includes('修订建议')) {
            report += `\n💡 ${line.replace(/^.*修订建议/, '修订建议：').trim()}\n`;
        }
    }

    addAIMessage(report);
}

// 显示黄金三章评审结果
function displayGoldenAudit(golden) {
    if (!golden) return;

    const score = golden.golden_score || 0;
    const decision = golden.decision || '';
    const decisionType = golden.decision_type || '';

    let scoreIcon = '🟢';
    if (decisionType === 'revision') scoreIcon = '🟡';
    else if (decisionType === 'rewrite') scoreIcon = '🔴';

    let goldenDetail = `\n${scoreIcon} **✨ 黄金三章评审**\n`;
    goldenDetail += `━━━━━━━━━━━━━━━━━━━━\n`;
    goldenDetail += `📊 **综合评分**：${score}分\n`;
    goldenDetail += `📋 **评审结论**：${decision}\n`;

    // 显示各维度评分
    const dims = golden.dimensions || {};
    if (Object.keys(dims).length > 0) {
        goldenDetail += `\n📈 **各维度评分**：\n`;
        const dimNames = {
            'opening_hook': '开篇钩子',
            'expectation_building': '期待感建立',
            'rhythm_density': '节奏密度',
            'information_progression': '信息递进',
            'character_anchor': '人设锚点',
            'hook_density': '伏笔密度'
        };
        for (const [key, value] of Object.entries(dims)) {
            const name = dimNames[key] || key;
            goldenDetail += `   • ${name}：${value}/25\n`;
        }
    }

    // 显示亮点
    const highlights = golden.highlights || [];
    if (highlights.length > 0) {
        goldenDetail += `\n✨ **本章亮点**：\n`;
        highlights.forEach(h => {
            goldenDetail += `   • ${h}\n`;
        });
    }

    // 显示问题
    const issues = golden.issues || [];
    if (issues.length > 0) {
        goldenDetail += `\n⚠️ **存在问题**：\n`;
        issues.forEach(issue => {
            goldenDetail += `   • ${issue}\n`;
        });
    }

    // 建议
    goldenDetail += `\n━━━━━━━━━━━━━━━━━━━━\n`;
    if (decisionType === 'pass') {
        goldenDetail += `✅ 黄金三章审核通过！您的开篇已具备良好的吸引力，建议继续创作后续章节。`;
    } else if (decisionType === 'revision') {
        goldenDetail += `💡 建议对上述问题进行修订，修订后可重新进行黄金三章评审。`;
    } else {
        goldenDetail += `⚠️ 建议重新审视前三章结构，确保开篇具有足够的吸引力。`;
    }

    addAIMessage(goldenDetail);
}

// 触发自动保存（防抖）
function triggerAutoSave() {
    if (autoSaveTimer) {
        clearTimeout(autoSaveTimer);
    }
    autoSaveTimer = setTimeout(() => {
        autoSaveChatLog();
    }, 2000);  // 2秒后保存
}

// 自动保存聊天记录
async function autoSaveChatLog() {
    if (!currentBook || chatHistory.length === 0) return;
    
    try {
        const today = new Date().toISOString().split('T')[0];
        const fileName = `chat_log_${today}_auto.json`;
        
        const exportData = {
            sessionId: chatSessionId,
            exportTime: new Date().toLocaleString('zh-CN'),
            book: { id: currentBook.id, name: currentBook.name },
            chapter: currentChapter ? { id: currentChapter.id, number: currentChapter.number } : null,
            messageCount: chatHistory.length,
            messages: chatHistory
        };

        await api(`/api/books/${currentBook.id}/chat-logs`, {
            method: 'POST',
            body: JSON.stringify({ filename: fileName, content: JSON.stringify(exportData, null, 2) })
        });
        
        console.log(`聊天记录已自动保存: ${chatHistory.length} 条`);
    } catch (e) {
        console.error('自动保存聊天记录失败:', e);
    }
}

function formatMessageContent(content) {
    if (typeof content !== 'string') {
        content = JSON.stringify(content, null, 2);
    }

    // 先转义 HTML
    let html = escapeHtml(content);

    // 支持基本 Markdown 格式（在转义后处理）
    // 粗体 **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // 斜体 *text*
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // 行内代码 `code`
    html = html.replace(/`(.+?)`/g, '<code>$1</code>');

    // 换行处理
    html = html.replace(/\n/g, '<br>');

    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 添加 AI 风格的详细操作记录
function addAIInstructionMessage(action, target, brief = '') {
    const actionNames = {
        'continue': '续写',
        'review': '评审',
        'revise': '修订',
        'regenerate': '重新生成',
        'planning': '创作简报生成',
        'story_bible': '世界观生成',
        'book_rules': '书籍规则生成',
        'chapter_outline': '章节大纲生成'
    };

    const actionName = actionNames[action] || action;
    const bookName = currentBook?.name || '未知书籍';
    const targetName = target?.name || `第${target?.number}章` || '未指定';

    let message = `📋 **操作指令**\n\n`;
    message += `**任务**: ${actionName}\n`;
    message += `**书籍**: ${bookName}\n`;
    message += `**目标**: ${targetName}\n`;
    if (brief) {
        message += `**说明**: ${brief}`;
    }

    addMessage('ai', message);
}

// 过滤 AI 思考过程内容（<think>...</think> 块）
function filterAIContent(content) {
    if (typeof content !== 'string') return content;
    // 移除<think>...</think>块（支持多行和嵌套）
    return content.replace(/<think>[\s\S]*?<\/think>/gi, '')
                  .replace(/<think>[\s\S]*?<\/think>/gi, '')
                  .trim();
}

// 内容预览相关变量
let currentPreviewContent = null;
let currentPreviewTitle = '';

// 显示内容预览弹窗
function showContentPreview(content, title = '内容预览') {
    currentPreviewContent = content;
    currentPreviewTitle = title;

    const modal = document.getElementById('content-preview-modal');
    const titleEl = document.getElementById('content-preview-title');
    const contentEl = document.getElementById('content-preview-body');

    if (modal && titleEl && contentEl) {
        titleEl.textContent = title;
        // 渲染 markdown 内容
        contentEl.innerHTML = renderMarkdown(content);
        modal.classList.add('show');
    }
}

// 关闭内容预览弹窗
function closeContentPreview() {
    document.getElementById('content-preview-modal').classList.remove('show');
    currentPreviewContent = null;
}

// 简单的 Markdown 渲染（支持标题、粗体、代码块、列表等）
function renderMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);

    // 代码块
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 标题
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    // 粗体
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // 斜体
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // 列表
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    // 段落
    html = html.split('\n\n').map(p => {
        if (p.startsWith('<') || !p.trim()) return p;
        return `<p>${p}</p>`;
    }).join('');

    return html;
}

function sendChatMessage() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    
    const content = input.value.trim();
    if (!content) return;
    
    input.value = '';
    input.style.height = 'auto';
    
    addUserMessage(content);
    processUserCommand(content);
}

function processUserCommand(content) {
    if (content.includes('创建') && content.includes('书')) {
        startNewBook();
    } else if (content.includes('续写')) {
        executeWrite('continue');
    } else if (content.includes('评审')) {
        executeWrite('review');
    } else if (content.includes('修订')) {
        executeWrite('revise');
    } else {
        handleUserQuery(content);
    }
}

async function handleUserQuery(query) {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }

    if (isTaskRunning) {
        addSystemMessage('⚠️ 任务正在执行中，请稍候...');
        return;
    }

    // 显示正在思考
    addSystemMessage('正在分析您的请求...');
    isTaskRunning = true;
    updateChatStatus('处理中...');

    try {
        const res = await api('/api/chat/handle', {
            method: 'POST',
            body: JSON.stringify({
                book_id: currentBook.id,
                query: query
            })
        });

        if (res.success && res.task_id) {
            // 重置进度跟踪变量
            lastProgress = 0;
            lastStep = '';
            completedSteps = [];

            // 启动轮询显示进度
            startTaskPolling(res.task_id);
        } else {
            addSystemMessage(`❌ ${res.message || '无法处理该请求'}`);
            isTaskRunning = false;
            updateChatStatus('');
        }
    } catch (e) {
        addSystemMessage(`❌ 处理失败: ${e.message}`);
        isTaskRunning = false;
        updateChatStatus('');
    }
}

// ==================== 工具栏功能 ====================
function toggleToolbox(id) {
    const toolbox = document.getElementById(id);
    if (toolbox) {
        toolbox.classList.toggle('collapsed');
    }
}

// 切换工具栏标签页
function switchToolbarTab(tabName) {
    // 更新按钮状态
    document.querySelectorAll('.toolbar-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    // 更新内容显示
    document.querySelectorAll('.toolbar-tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });
}

async function updateDocStatus() {
    if (!currentBook) return;
    
    const res = await api(`/api/books/${currentBook.id}`);
    if (!res.success) return;
    
    const book = res.book;
    
    // 更新新卡片样式
    const docKeys = ['planning', 'story_bible', 'book_rules', 'chapter_outline'];
    docKeys.forEach(key => {
        const statusEl = document.getElementById(`status-${key}`);
        if (statusEl) {
            const exists = book[key + '_exists'];
            statusEl.textContent = exists ? '✓' : '+';
            statusEl.className = `doc-status ${exists ? 'status-created' : 'status-none'}`;
        }
    });
    
    // 兼容旧样式
    const docStatusList = document.getElementById('doc-status-list');
    if (!docStatusList) return;
    
    const docs = [
        { key: 'planning', name: '创作简报', icon: '📋' },
        { key: 'story_bible', name: '世界观', icon: '🌍' },
        { key: 'book_rules', name: '规则', icon: '📜' },
        { key: 'chapter_outline', name: '大纲', icon: '📑' }
    ];
    
    docStatusList.innerHTML = docs.map(doc => {
        const status = book[doc.key + '_exists'] ? 'created' : 'none';
        const statusClass = status === 'created' ? 'status-ok' : 'status-none';
        return `<span class="doc-tag" data-doc="${doc.key}" onclick="handleDocClick('${doc.key}')">${doc.icon} ${doc.name} <span class="${statusClass}">${status === 'created' ? '✓' : '+'}</span></span>`;
    }).join('');
}

// 处理文档项点击 - 查看或创建文档（无需确认）
async function handleDocClick(docKey) {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }
    
    const docNames = {
        'planning': '创作简报',
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    };
    
    const docName = docNames[docKey] || docKey;
    
    // 先检查文档是否存在
    const res = await api(`/api/books/${currentBook.id}/docs/${docKey}`);
    
    if (res.success && res.content) {
        // 文档已存在，查看
        viewDoc(docKey);
    } else {
        // 文档不存在，创建
        if (docKey === 'planning') {
            showPlanningModal();
        } else {
            addSystemMessage(`正在创建"${docName}"...`);
            await api('/api/docs/regenerate', {
                method: 'POST',
                body: JSON.stringify({ book_id: currentBook.id, doc_key: docKey })
            });
            addSystemMessage(`✅ "${docName}"创建完成`);
            await updateDocStatus();
            await viewDoc(docKey);
            // 显示引导提示
            setTimeout(() => showGuidance('task_completed'), 500);
        }
    }
}

async function viewDoc(docKey) {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }

    const docNames = {
        'planning': '创作简报',
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    };

    const res = await api(`/api/books/${currentBook.id}/docs/${docKey}`);
    const previewContent = document.getElementById('preview-content');
    const previewTitle = document.getElementById('preview-title');

    // 获取评审报告
    let auditHtml = '';
    if (['story_bible', 'book_rules', 'chapter_outline'].includes(docKey)) {
        try {
            const auditRes = await api(`/api/docs/${currentBook.id}/${docKey}/audit`);
            if (auditRes && auditRes.found) {
                const statusIcon = auditRes.passed ? '✅' : '⚠️';
                const statusText = auditRes.passed ? '通过' : '需修订';
                auditHtml = `<div class="doc-audit-badge">${statusIcon} 评审：${statusText}</div>`;
            }
        } catch (e) {
            // 忽略错误
        }
    }

    if (res.success && res.content) {
        previewTitle.textContent = docNames[docKey] || docKey;
        previewContent.innerHTML = auditHtml + `<div class="preview-doc">${marked(res.content)}</div>`;
        // 查看文档后显示引导（传递当前查看的文档键）
        setTimeout(() => showGuidance('doc_viewed', docKey), 500);
    } else {
        previewTitle.textContent = docNames[docKey] || docKey;
        previewContent.innerHTML = auditHtml + '<div class="preview-empty"><p>暂无内容</p></div>';
    }
}

async function regenerateDoc(docKey) {
    if (!currentBook) return;

    const docNames = {
        'planning': '创作简报',
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    };

    const docName = docNames[docKey] || docKey;

    if (!confirm(`确定要重新生成"${docName}"吗？这将覆盖现有内容。`)) {
        return;
    }

    // 添加 AI 风格的操作指令记录
    addAIInstructionMessage(docKey, null, `重新生成 ${docName}`);

    const res = await api('/api/docs/regenerate', {
        method: 'POST',
        body: JSON.stringify({ book_id: currentBook.id, doc_key: docKey })
    });

    // 创作简报需要用户输入
    if (res.need_input) {
        addSystemMessage(`📝 "${docName}"需要用户输入`);
        showPlanningModal();
        return;
    }

    if (res.success && res.task_id) {
        // 异步任务：开始轮询任务状态
        addSystemMessage(`🔄 开始重新生成"${docName}"...`);
        
        // 启动文档生成轮询
        startDocRegeneratePolling(res.task_id, docKey, docName);
    } else {
        addSystemMessage(`❌ 重新生成失败: ${res.message}`);
    }
}

// 文档重新生成轮询
let docRegenerateTaskId = null;
let docRegenerateDocKey = null;
let docRegenerateDocName = null;

async function startDocRegeneratePolling(taskId, docKey, docName) {
    docRegenerateTaskId = taskId;
    docRegenerateDocKey = docKey;
    docRegenerateDocName = docName;
    
    // 立即检查一次
    await checkDocRegenerateStatus();
}

async function checkDocRegenerateStatus() {
    if (!docRegenerateTaskId) return;
    
    const res = await api(`/api/tasks/${docRegenerateTaskId}`);
    if (!res.success) {
        docRegenerateTaskId = null;
        return;
    }
    
    const task = res.task;
    
    // 更新进度显示
    if (task.progress !== undefined) {
        updateChatStatus(`正在处理: ${task.message || docRegenerateDocName} (${task.progress}%)`);
    }
    
    // 任务完成
    if (task.status === 'success' || task.status === 'failed') {
        stopDocRegeneratePolling();
        
        if (task.status === 'success' && task.result) {
            const result = task.result;
            
            // 显示步骤进度
            if (result.steps && result.steps.length > 0) {
                let stepsHtml = `📋 **${docRegenerateDocName}生成进度**\n`;
                result.steps.forEach((step, idx) => {
                    const icon = step.status === 'completed' ? '✅' : '🔄';
                    const passed = step.passed === true ? ' ✅通过' : (step.passed === false ? ' ⚠️需修订' : '');
                    const score = step.score !== undefined ? ` (${step.score}分)` : '';
                    stepsHtml += `${icon} ${step.name}${score}${passed}\n`;
                });
                addAIMessage(stepsHtml);
            } else {
                addSystemMessage(`✅ "${docRegenerateDocName}"重新生成完成`);
            }
            
            // 显示评审结果
            if (result.audit_passed !== undefined) {
                const auditIcon = result.audit_passed ? '✅' : '⚠️';
                const auditMsg = result.audit_passed ? '评审通过' : '评审未通过';
                const score = result.audit_score !== undefined ? `（${result.audit_score}分）` : '';
                addSystemMessage(`${auditIcon} 评审结果: ${auditMsg}${score}`);
            }
            
            await updateDocStatus();
            if (docRegenerateDocKey) {
                await viewDoc(docRegenerateDocKey);
            }
            // 显示引导提示
            setTimeout(() => showGuidance('task_completed'), 500);
        } else {
            addSystemMessage(`❌ 重新生成失败: ${task.message || '未知错误'}`);
        }
        updateChatStatus('');
        return;
    }
    
    // 继续轮询
    setTimeout(checkDocRegenerateStatus, 2000);
}

function stopDocRegeneratePolling() {
    docRegenerateTaskId = null;
    docRegenerateDocKey = null;
    docRegenerateDocName = null;
}

async function createDoc(docKey) {
    if (!currentBook) return;

    const docNames = {
        'planning': '创作简报',
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    };

    const docName = docNames[docKey] || docKey;

    // 创作简报需要用户输入
    if (docKey === 'planning') {
        showPlanningModal();
        return;
    }

    // 添加 AI 风格的操作指令记录
    addAIInstructionMessage(docKey, null, `创建 ${docName}`);

    const res = await api('/api/docs/regenerate', {
        method: 'POST',
        body: JSON.stringify({ book_id: currentBook.id, doc_key: docKey })
    });

    if (res.success) {
        addSystemMessage(`✅ "${docName}"创建完成`);
        await updateDocStatus();
        await viewDoc(docKey);
        // 显示引导提示
        setTimeout(() => showGuidance('task_completed'), 500);
    } else if (res.need_input) {
        // 需要用户输入，显示输入弹窗
        if (docKey === 'planning') {
            showPlanningModal();
        } else {
            addSystemMessage(`⚠️ ${res.message}`);
        }
    } else {
        addSystemMessage(`❌ 创建失败: ${res.message}`);
    }
}

// 显示创作简报输入弹窗
function showPlanningModal() {
    const modal = document.getElementById('planning-modal');
    if (modal) {
        modal.classList.add('show');
    } else {
        // 动态创建弹窗
        const modalHtml = `
            <div class="modal show" id="planning-modal">
                <div class="modal-content modal-large">
                    <div class="modal-header">
                        <h3>创作简报</h3>
                        <button class="btn-close" onclick="closePlanningModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label>创作构想</label>
                            <textarea id="planning-content" rows="12" placeholder="描述你的创作构想...

例如：
- 都市玄幻小说，主角获得上古传承
- 修仙世界，废材逆袭成为一代仙帝
- 现代都市，商业天才的崛起之路"></textarea>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="closePlanningModal()">取消</button>
                        <button class="btn btn-primary" onclick="savePlanning()">保存</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    }
}

function closePlanningModal() {
    const modal = document.getElementById('planning-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

async function savePlanning() {
    const content = document.getElementById('planning-content').value.trim();
    if (!content) {
        alert('请输入创作构想');
        return;
    }

    closePlanningModal();

    // 添加 AI 风格的操作指令记录
    addAIInstructionMessage('planning', null, '根据用户提供的创作构想生成创作简报');

    const res = await api('/api/docs/planning/save', {
        method: 'POST',
        body: JSON.stringify({ book_id: currentBook.id, content })
    });

    if (res.success) {
        await updateDocStatus();
        await viewDoc('planning');
        // 显示引导提示
        setTimeout(() => showGuidance('task_completed'), 500);
    } else {
        addSystemMessage(`❌ 保存失败: ${res.message}`);
    }
}

function marked(text) {
    if (!text) return '';
    return text
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

// ==================== 撰写工具 ====================
let selectedTargetChapter = null;  // 用户选择的目标章节
let pendingDeleteChapter = null;   // 待删除的章节信息

const writeActions = {
    'continue': { name: '续写', icon: '▶️', confirmMsg: '确定要续写吗？' },
    'review': { name: '评审', icon: '🔍', confirmMsg: '确定要评审吗？' },
    'revise': { name: '修订', icon: '🔧', confirmMsg: '确定要修订吗？' },
    'regenerate': { name: '重新生成', icon: '🔄', confirmMsg: '确定要重新生成吗？这将覆盖现有内容。' }
};

// 获取操作目标章节信息
function getTargetChapterInfo() {
    // 优先使用用户选择的章节
    if (selectedTargetChapter) {
        return selectedTargetChapter;
    }
    // 否则使用当前选中的章节
    if (currentChapter) {
        return {
            id: currentChapter.id,
            number: currentChapter.number,
            name: currentChapter.name || (currentChapter.number === 0 ? '序章' : `第${currentChapter.number}章`)
        };
    }
    return null;
}

// 从侧边栏章节列表选章
function selectChapterForWrite(chapterId, chapterNum, chapterTitleEncoded, event) {
    event.stopPropagation();
    
    // 切换到写作工具标签页
    switchToolbarTab('write');
    
    const chapterTitle = decodeURIComponent(chapterTitleEncoded);
    const select = document.getElementById('target-chapter-select');
    if (select) {
        const optionValue = `${chapterId}|${chapterNum}|${encodeURIComponent(chapterTitle)}`;
        // 查找匹配的选项
        const options = select.options;
        for (let i = 0; i < options.length; i++) {
            const opt = options[i];
            if (opt.value.startsWith(chapterId + '|') || opt.value.startsWith(chapterNum + '|')) {
                select.selectedIndex = i;
                break;
            }
        }
        // 触发change事件
        select.dispatchEvent(new Event('change'));
    }
}

// 章节下拉选择改变时的回调
function onTargetChapterChange() {
    const select = document.getElementById('target-chapter-select');
    const deleteBtn = document.getElementById('delete-chapter-btn');
    const value = select.value;

    if (!value) {
        selectedTargetChapter = null;
        updateChapterHintUI();
        if (deleteBtn) deleteBtn.style.display = 'none';
        return;
    }

    // 解析选择的值：格式 "chapter_id|chapter_num" 或 "new_0" 等
    if (value.startsWith('new_')) {
        // 新章节选项
        const chapterNum = parseInt(value.replace('new_', ''));
        selectedTargetChapter = {
            id: null,
            number: chapterNum,
            name: chapterNum === 0 ? '序章（未生成）' : `第${chapterNum}章（未生成）`
        };
        if (deleteBtn) deleteBtn.style.display = 'none';
    } else {
        // 已有章节
        const parts = value.split('|');
        const chapterId = parts[0];
        const chapterNum = parseInt(parts[1]);
        const chapterName = parts[2] ? decodeURIComponent(parts[2]) : (chapterNum === 0 ? '序章' : `第${chapterNum}章`);
        selectedTargetChapter = {
            id: chapterId,
            number: chapterNum,
            name: chapterName
        };
        if (deleteBtn) deleteBtn.style.display = 'inline-block';
    }

    updateChapterHintUI();
}

// 更新章节选择提示UI
function updateChapterHintUI() {
    const hint = document.getElementById('current-chapter-hint');
    const target = getTargetChapterInfo();
    if (hint) {
        if (target) {
            hint.textContent = `已选: ${target.name}`;
            hint.style.color = 'var(--primary)';
        } else {
            hint.textContent = '请选择章节';
            hint.style.color = 'var(--text-secondary)';
        }
    }
}

// 通过ID选中章节（不触发预览）
async function selectChapterById(chapterId) {
    if (!chapterId || chapterId === 'null' || chapterId === 'undefined') {
        console.warn('无效的章节ID');
        return;
    }
    
    const res = await api(`/api/chapters/${encodeURIComponent(chapterId)}`);
    if (res.success) {
        selectedTargetChapter = {
            id: res.chapter.id,
            number: res.chapter.number,
            name: res.chapter.name || (res.chapter.number === 0 ? '序章' : `第${res.chapter.number}章`)
        };
        updateChapterHintUI();
    }
}

// 更新章节选择下拉框选项
async function updateChapterSelect() {
    const select = document.getElementById('target-chapter-select');
    if (!select || !currentBook) return;

    const res = await api(`/api/books/${currentBook.id}/chapters`);
    const deleteBtn = document.getElementById('delete-chapter-btn');

    if (!res.success || !res.chapters || res.chapters.length === 0) {
        // 没有章节时，显示第0章（未生成）选项
        select.innerHTML = '<option value="new_0">序章（未生成）</option>';
        selectedTargetChapter = null;
        updateChapterHintUI();
        if (deleteBtn) deleteBtn.style.display = 'none';
        return;
    }

    // 按章节号排序
    const chapters = res.chapters.sort((a, b) => a.number - b.number);

    let optionsHtml = '<option value="">-- 选择章节 --</option>';
    let foundCurrentChapter = false;
    
    // 默认选择最后一章（最大的章节号）
    const lastChapter = chapters[chapters.length - 1];
    let defaultSelectedId = null;

    chapters.forEach(ch => {
        const chapterTitle = ch.name || (ch.number === 0 ? '序章' : `第${ch.number}章`);
        // 优先选择最后一章
        const isSelected = (ch.id === lastChapter.id) ? 'selected' : '';
        if (isSelected) {
            foundCurrentChapter = true;
            defaultSelectedId = ch.id;
        }
        // 格式：chapter_id|chapter_num|chapter_name(可选)
        optionsHtml += `<option value="${ch.id}|${ch.number}|${encodeURIComponent(chapterTitle)}" ${isSelected}>${chapterTitle}</option>`;
    });

    select.innerHTML = optionsHtml;
    
    // 设置默认选择为最后一章
    if (defaultSelectedId) {
        const parts = lastChapter.id.split('|');
        selectedTargetChapter = {
            id: parts[0],
            number: lastChapter.number,
            name: lastChapter.name || (lastChapter.number === 0 ? '序章' : `第${lastChapter.number}章`)
        };
    }

    // 检查是否需要显示删除按钮
    if (currentChapter && foundCurrentChapter) {
        if (deleteBtn) deleteBtn.style.display = 'inline-block';
    } else if (deleteBtn) {
        deleteBtn.style.display = 'none';
    }

    updateChapterHintUI();
}

async function executeWrite(action) {
    if (!currentBook) {
        addSystemMessage('请先选择或创建一本书');
        return;
    }

    if (isTaskRunning) {
        addSystemMessage('⚠️ 任务正在执行中，请稍候...');
        return;
    }

    let target = getTargetChapterInfo();

    // 如果没有选中章节，尝试自动确定目标
    if (!target) {
        const chaptersRes = await api(`/api/books/${currentBook.id}/chapters`);
        const chapters = chaptersRes.success ? (chaptersRes.chapters || []) : [];
        
        if (action === 'continue') {
            // 续写：找到最后一章，下一章自动+1
            if (chapters.length === 0) {
                // 新书，默认创作序章（第0章）
                target = { id: null, number: 0, name: '序章' };
                addSystemMessage('📝 未选择章节，默认创作序章（第0章）');
            } else {
                // 已有章节，找到最大编号，续写下一章
                const maxChapter = Math.max(...chapters.map(ch => ch.number));
                target = { id: null, number: maxChapter + 1, name: `第${maxChapter + 1}章` };
                addSystemMessage(`📝 未选择章节，默认续写第${maxChapter + 1}章`);
            }
        } else {
            // 评审/修订需要指定章节
            addSystemMessage('请先在左侧章节列表选择要操作的章节');
            return;
        }
    } else if (action === 'continue') {
        // 续写逻辑：如果目标章节已生成，则自动改为生成下一章
        const chaptersRes = await api(`/api/books/${currentBook.id}/chapters`);
        if (chaptersRes.success && chaptersRes.chapters) {
            // 检查目标章节是否已存在
            const existingChapter = chaptersRes.chapters.find(ch => ch.number === target.number);
            if (existingChapter) {
                // 章节已存在，自动改为生成下一章
                const nextChapterNum = target.number + 1;
                target.number = nextChapterNum;
                target.id = null;  // 新章节没有ID
                target.name = `第${nextChapterNum}章`;
                addSystemMessage(`📝 第${target.number - 1}章已存在，自动转为续写第${nextChapterNum}章`);
            }
        }
    }

    const info = writeActions[action] || { name: action, icon: '⚡', confirmMsg: `确定要执行${action}吗？` };

    // 增加确认步骤，包含章节信息
    const chapterInfo = `【${target.name}】`;
    const actionName = action === 'continue' ? '续写' : (action === 'review' ? '评审' : (action === 'revise' ? '修订' : '重新生成'));
    const confirmMsg = action === 'regenerate'
        ? `确定要重新生成 ${chapterInfo} 吗？这将覆盖现有内容。`
        : `确定要对 ${chapterInfo} 执行${actionName}吗？`;

    if (!confirm(confirmMsg)) {
        return;
    }

    isTaskRunning = true;
    updateChatStatus('任务执行中...');

    // 添加 AI 风格的操作指令记录
    addAIInstructionMessage(action, target);

    try {
        const res = await api('/api/write/execute', {
            method: 'POST',
            body: JSON.stringify({
                book_id: currentBook.id,
                action,
                chapter_id: target.id,
                chapter_num: target.number
            })
        });

        if (res.status === 409) {
            // 章节被锁定
            addSystemMessage(`⚠️ ${res.detail || '该章节正在被其他操作锁定，请稍后再试'}`);
            isTaskRunning = false;
            updateChatStatus('');
            return;
        }

        if (res.success && res.task_id) {
            // 异步任务模式
            const chapterNum = res.chapter_num;
            if (chapterNum) {
                lockedChapters[chapterNum] = res.task_id;
                await loadChapterList();
            }
            startTaskPolling(res.task_id);
        } else if (res.success) {
            addSystemMessage(`✅ ${info.name}完成！`);
            await loadChapterList();
        } else {
            addSystemMessage(`❌ ${info.name}失败: ${res.message}`);
        }
    } catch (e) {
        addSystemMessage(`❌ 执行出错: ${e.message}`);
    } finally {
        // 不在这里重置 isTaskRunning，由任务完成时重置
    }
}

// ==================== 章节列表 ====================
async function loadChapterList() {
    if (!currentBook) {
        const section = document.getElementById('chapter-list-section');
        if (section) section.style.display = 'none';
        return;
    }

    const res = await api(`/api/books/${currentBook.id}/chapters`);
    const section = document.getElementById('chapter-list-section');
    const list = document.getElementById('chapter-list');

    if (!list) return;

    if (section) section.style.display = 'block';

    // 获取章节锁状态
    await refreshChapterLocks();

    if (res.success && res.chapters && res.chapters.length > 0) {
        list.innerHTML = res.chapters.map(ch => {
            const isLocked = lockedChapters[ch.number];
            const lockClass = isLocked ? 'locked' : '';
            const lockIcon = isLocked ? '<span class="chapter-lock" title="章节被锁定">🔒</span>' : '';
            // 章节名
            const chapterTitle = ch.title ? `<span class="chapter-title">${escapeHtml(ch.title)}</span>` : '';
            
            // 状态显示逻辑 - 优化评审结果显示
            let statusBadge = '';
            if (ch.finalized) {
                // 已终审通过
                statusBadge = '<span class="status-badge finalized" title="已终审通过">✅ 通过</span>';
            } else if (ch.audit_score > 0) {
                // 有评审分 - 根据分数显示不同颜色
                const scoreColor = ch.audit_score >= 75 ? 'color: #52c41a;' : (ch.audit_score >= 60 ? 'color: #faad14;' : 'color: #f5222d;');
                const scoreLabel = ch.status === 'draft' ? '初评' : '修订';
                statusBadge = `<span class="status-badge" style="${scoreColor} font-weight: bold;" title="${scoreLabel}评分：${ch.audit_score}分">📊 ${ch.audit_score}分</span>`;
            } else {
                // 无评审分
                statusBadge = '<span class="status-badge draft">📝 待评审</span>';
            }

            // 字数 - 更清晰显示
            const wordCount = ch.word_count || 0;
            const wordCountDisplay = wordCount >= 1000
                ? `${(wordCount / 1000).toFixed(1)}k`
                : wordCount;
            const wordCountColor = wordCount >= 2000 ? 'color: #52c41a;' : (wordCount >= 1000 ? 'color: #1890ff;' : 'color: #999;');
            
            // 章节标题用于下拉框
            const chapterFullTitle = ch.title || (ch.number === 0 ? '序章' : `第${ch.number}章`);
            
            return `
                <div class="chapter-item ${currentChapter && currentChapter.id === ch.id ? 'active' : ''} ${lockClass}"
                     data-chapter-id="${ch.id}"
                     onclick="selectChapter('${ch.id}')">
                    <div class="chapter-row-main">
                        <span class="chapter-status ${ch.status || 'draft'}"></span>
                        <span class="chapter-number">第${ch.number}章</span>
                        ${chapterTitle}
                        ${lockIcon}
                    </div>
                    <div class="chapter-row-info">
                        ${statusBadge}
                        <span class="chapter-words" style="${wordCountColor}">📝 ${wordCountDisplay}字</span>
                        <button class="chapter-select-btn" onclick="selectChapterForWrite('${ch.id}', '${ch.number}', '${encodeURIComponent(chapterFullTitle)}', event)" title="选为当前章节">📌选</button>
                    </div>
                </div>
            `;
        }).join('');

        // 更新撰写工具的章节选择器
        await updateChapterSelect();
        
        // 如果已有章节，切换到写作工具标签页
        switchToolbarTab('write');
    } else {
        list.innerHTML = '<div style="font-size: 0.8rem; color: var(--text-secondary); padding: 0.5rem;">暂无章节</div>';
    }
}

// 刷新章节锁状态
async function refreshChapterLocks() {
    if (!currentBook || !currentBook.id || currentBook.id === 'undefined') return;
    
    try {
        const res = await api(`/api/chapters/locks?book_id=${encodeURIComponent(currentBook.id)}`);
        if (res.success) {
            lockedChapters = {};
            (res.locked_chapters || []).forEach(item => {
                lockedChapters[item.chapter_num] = item.task_id;
            });
        }
    } catch (e) {
        console.warn('获取章节锁状态失败:', e);
    }
}

async function selectChapter(chapterId) {
    if (!chapterId || chapterId === 'null' || chapterId === 'undefined') {
        console.warn('无效的章节ID');
        return;
    }
    
    const res = await api(`/api/chapters/${encodeURIComponent(chapterId)}`);
    if (res.success) {
        currentChapter = res.chapter;
        selectedTargetChapter = null;  // 清空用户选择，使用当前章节
        await loadChapterList();
        viewChapterContent();
        updateChapterHintUI();  // 更新章节提示
    }
}

function viewChapterContent() {
    if (!currentChapter) return;
    
    const previewContent = document.getElementById('preview-content');
    const previewTitle = document.getElementById('preview-title');
    
    previewTitle.textContent = `第${currentChapter.number}章`;
    previewContent.innerHTML = `<div class="preview-doc">${marked(currentChapter.content || '暂无内容')}</div>`;
}

// ==================== 预览栏 ====================
function togglePreviewPanel() {
    const panel = document.getElementById('preview-panel');
    if (panel) {
        const isHidden = panel.classList.toggle('hidden');
        // 清除内联宽度，避免覆盖 .hidden 的 width: 0
        if (isHidden) {
            panel.style.width = '';
        }
    }
}

// ==================== 状态更新 ====================
function updateChatStatus(status) {
    const statusEl = document.getElementById('chat-status');
    if (statusEl) {
        statusEl.textContent = status;
        statusEl.className = 'chat-status' + (status ? ' running' : '');
    }
}

// ==================== 任务进度 ====================
function addTaskProgress(tasks) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    
    hideWelcomeView();
    
    const html = `
        <div class="task-progress">
            <div class="task-progress-header">
                <span>📊</span>
                <span>任务进度</span>
            </div>
            ${tasks.map(task => `
                <div class="task-progress-item">
                    <div class="task-status-icon ${task.status}">
                        ${task.status === 'done' ? '✓' : task.status === 'running' ? '⟳' : task.status === 'error' ? '✗' : '○'}
                    </div>
                    <div class="task-info">
                        <div class="task-name">${task.name}</div>
                        ${task.path ? `<div class="task-path">${task.path}</div>` : ''}
                    </div>
                    ${task.viewable ? `<span class="task-action" onclick="viewDoc('${task.docKey}')">查看</span>` : ''}
                </div>
            `).join('')}
        </div>
    `;
    
    messages.insertAdjacentHTML('beforeend', html);
    messages.scrollTop = messages.scrollHeight;
}



// ==================== 设置相关 ====================
function showSettings() {
    loadSettingsData();
    document.getElementById('settings-modal').classList.add('show');
}

function closeSettings() {
    document.getElementById('settings-modal').classList.remove('show');
}

async function loadSettingsData() {
    const res = await api('/api/llm/config');
    if (res.success) {
        providersData = res;
        providerTemplates = res.templates || {};
        renderProvidersList();
    }
}

function renderProvidersList() {
    const container = document.getElementById('providers-list');
    const providers = providersData?.config?.providers || [];
    const activeId = providersData?.config?.active_provider_id;
    
    if (providers.length === 0) {
        container.innerHTML = '<p style="color: var(--text-secondary);">暂无配置的提供商</p>';
        return;
    }
    
    container.innerHTML = providers.map(p => `
        <div class="provider-card ${p.id === activeId ? 'active' : ''}" onclick="editProvider('${p.id}')">
            <div class="provider-icon">${p.name.charAt(0).toUpperCase()}</div>
            <div class="provider-info">
                <div class="provider-name">${p.name}</div>
                <div class="provider-model">${p.model || '未设置模型'}</div>
                <div class="provider-actions">
                    <button class="btn btn-sm ${p.id === activeId ? 'btn-primary' : 'btn-secondary'}" 
                            onclick="event.stopPropagation(); activateProvider('${p.id}')">
                        ${p.id === activeId ? '使用中' : '激活'}
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); testProvider('${p.id}')">
                        测试
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); deleteProvider('${p.id}')">
                        删除
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function editProvider(providerId) {
    const provider = providersData?.config?.providers?.find(p => p.id === providerId);
    if (!provider) return;
    
    const form = document.getElementById('provider-config-form');
    form.innerHTML = `
        <div class="form-group">
            <label>提供商名称</label>
            <input type="text" id="edit-provider-name" value="${provider.name || ''}">
        </div>
        <div class="form-group">
            <label>API 密钥</label>
            <input type="password" id="edit-provider-api-key" placeholder="留空则不修改">
        </div>
        <div class="form-group">
            <label>Base URL</label>
            <input type="text" id="edit-provider-base-url" value="${provider.base_url || ''}">
        </div>
        <div class="form-group">
            <label>模型</label>
            <input type="text" id="edit-provider-model" value="${provider.model || ''}">
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Temperature</label>
                <input type="number" id="edit-provider-temp" step="0.1" min="0" max="2" value="${provider.temperature || 0.7}">
            </div>
            <div class="form-group">
                <label>Max Tokens</label>
                <input type="number" id="edit-provider-tokens" value="${provider.max_tokens || 8192}">
            </div>
        </div>
        <div class="form-group">
            <label class="checkbox-label">
                <input type="checkbox" id="edit-provider-stream" ${provider.stream ? 'checked' : ''}>
                启用流式输出
            </label>
        </div>
        <div class="modal-footer" style="padding:0; border:none; margin-top: 1rem;">
            <button class="btn btn-secondary" onclick="switchSettingsTab('providers')">返回</button>
            <button class="btn btn-primary" onclick="saveProviderConfig('${providerId}')">保存</button>
        </div>
    `;
    
    switchSettingsTab('provider-config');
}

function switchSettingsTab(tab) {
    document.querySelectorAll('.settings-tabs .tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.getElementById('tab-providers').style.display = tab === 'providers' ? 'block' : 'none';
    document.getElementById('tab-provider-config').style.display = tab === 'provider-config' ? 'block' : 'none';
    document.getElementById('tab-llm-logs').style.display = tab === 'llm-logs' ? 'block' : 'none';
    document.getElementById('tab-doc-files').style.display = tab === 'doc-files' ? 'block' : 'none';

    if (tab === 'llm-logs') {
        loadLogsList();
    } else if (tab === 'doc-files') {
        loadDocFilesList();
    }
}

async function saveProviderConfig(providerId) {
    const name = document.getElementById('edit-provider-name').value.trim();
    const apiKey = document.getElementById('edit-provider-api-key').value;
    const baseUrl = document.getElementById('edit-provider-base-url').value.trim();
    const model = document.getElementById('edit-provider-model').value.trim();
    const temp = parseFloat(document.getElementById('edit-provider-temp').value) || 0.7;
    const tokens = parseInt(document.getElementById('edit-provider-tokens').value) || 8192;
    const stream = document.getElementById('edit-provider-stream').checked;
    
    const provider = { id: providerId, name, base_url: baseUrl, model, temperature: temp, max_tokens: tokens, stream };
    if (apiKey) provider.api_key = apiKey;
    
    const res = await api('/api/llm/config', {
        method: 'PUT',
        body: JSON.stringify({ provider })
    });
    
    if (res.success) {
        alert('保存成功! 正在刷新...');
        setTimeout(() => location.reload(), 500);
    } else {
        alert('保存失败: ' + (res.message || '请重试'));
    }
}

async function testProvider(providerId) {
    alert('正在测试连接...');
    const res = await api('/api/llm/test', {
        method: 'POST',
        body: JSON.stringify({ provider_id: providerId })
    });
    alert(res.success ? '连接成功!' : '连接失败: ' + res.message);
}

async function activateProvider(providerId) {
    const res = await api(`/api/llm/providers/${providerId}/activate`, { method: 'POST' });
    if (res.success) {
        await loadSettingsData();
        alert('已激活');
    } else {
        alert('激活失败');
    }
}

async function deleteProvider(providerId) {
    if (!confirm('确定要删除这个提供商吗?')) return;
    const res = await api(`/api/llm/providers/${providerId}`, { method: 'DELETE' });
    if (res.success) {
        await loadSettingsData();
        alert('已删除');
    } else {
        alert('删除失败');
    }
}

async function showAddProvider() {
    const res = await api('/api/llm/templates');
    if (res.success && res.templates) {
        providerTemplates = res.templates;
        const select = document.getElementById('provider-template');
        select.innerHTML = '<option value="">-- 选择 --</option>';
        for (const [key, tpl] of Object.entries(res.templates)) {
            select.innerHTML += `<option value="${key}">${tpl.name}</option>`;
        }
    }
    document.getElementById('add-provider-modal').classList.add('show');
}

function closeAddProvider() {
    document.getElementById('add-provider-modal').classList.remove('show');
}

function onTemplateChange() {
    const templateKey = document.getElementById('provider-template').value;
    if (templateKey && providerTemplates[templateKey]) {
        const tpl = providerTemplates[templateKey];
        document.getElementById('provider-base-url').value = tpl.base_url || '';
        document.getElementById('provider-model').value = tpl.default_model || '';
        document.getElementById('provider-name').value = tpl.name || '';
    }
}

async function addProvider() {
    const templateKey = document.getElementById('provider-template').value;
    const name = document.getElementById('provider-name').value.trim();
    const apiKey = document.getElementById('provider-api-key').value.trim();
    const baseUrl = document.getElementById('provider-base-url').value.trim();
    const model = document.getElementById('provider-model').value.trim();
    const stream = document.getElementById('provider-stream').checked;
    
    if (!apiKey) {
        alert('请输入API密钥');
        return;
    }
    
    const providerName = name || (templateKey && providerTemplates[templateKey]?.name) || '自定义';
    
    const provider = {
        id: 'provider_' + Date.now(),
        name: providerName,
        api_key: apiKey,
        base_url: baseUrl,
        model: model,
        is_default: false,
        stream: stream
    };
    
    const res = await api('/api/llm/config', {
        method: 'PUT',
        body: JSON.stringify({ provider })
    });
    
    if (res.success) {
        closeAddProvider();
        alert('添加成功! 正在刷新...');
        setTimeout(() => location.reload(), 500);
    } else {
        alert('添加失败');
    }
}

// 日志相关
async function loadLogsList() {
    const res = await api('/api/llm/logs');
    const select = document.getElementById('log-file-select');
    select.innerHTML = '<option value="">-- 选择日志文件 --</option>';
    
    if (res.success && res.logs && res.logs.length > 0) {
        res.logs.forEach(log => {
            const option = document.createElement('option');
            option.value = log.name;
            option.textContent = `${log.name} (${formatFileSize(log.size)})`;
            select.appendChild(option);
        });
    } else {
        document.getElementById('log-content').textContent = '暂无日志记录';
    }
}

async function loadSelectedLog() {
    const select = document.getElementById('log-file-select');
    const filename = select.value;
    if (!filename) {
        document.getElementById('log-content').textContent = '请选择日志文件';
        return;
    }
    
    const res = await api(`/api/llm/logs/${filename}`);
    if (res.success) {
        document.getElementById('log-content').textContent = res.content;
    } else {
        document.getElementById('log-content').textContent = '加载失败: ' + (res.message || '未知错误');
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// 全局设置
function showGlobalSettings() {
    loadGlobalSettings();
    document.getElementById('global-settings-modal').classList.add('show');
}

function closeGlobalSettings() {
    document.getElementById('global-settings-modal').classList.remove('show');
}

function switchGlobalTab(tab) {
    document.querySelectorAll('#global-settings-modal .tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('#global-settings-modal .global-tab-content').forEach(el => {
        el.style.display = el.id === `tab-${tab}` ? 'block' : 'none';
    });
}

async function loadGlobalSettings() {
    const res = await api('/api/global/config');
    if (res.success) {
        const c = res.config || {};
        document.getElementById('global-banned-words').value = (c.banned_words || []).join('\n');
        document.getElementById('global-sensitive-topics').value = (c.sensitive_topics || []).join('\n');
        document.getElementById('global-system-prompt').value = c.system_prompt || '';
    }
}

async function saveGlobalSettings() {
    const bannedWords = document.getElementById('global-banned-words').value.split('\n').filter(w => w.trim());
    const sensitiveTopics = document.getElementById('global-sensitive-topics').value.split('\n').filter(t => t.trim());
    const systemPrompt = document.getElementById('global-system-prompt').value;
    
    const res = await api('/api/global/config', {
        method: 'PUT',
        body: JSON.stringify({
            banned_words: bannedWords,
            sensitive_topics: sensitiveTopics,
            system_prompt: systemPrompt
        })
    });
    
    if (res.success) {
        closeGlobalSettings();
        alert('保存成功');
    } else {
        alert('保存失败');
    }
}

function showToast(message, type = 'info') {
    console.log(`[${type}] ${message}`);
}

// ==================== 任务轮询 ====================
let lastProgress = 0;
let lastStep = '';

async function pollTaskStatus(taskId) {
    if (!taskId) return;

    const res = await api(`/api/tasks/${taskId}`);
    if (!res.success) return;

    const task = res.task;

    // 检测步骤变化：如果进度增加且有新步骤，则记录旧步骤为已完成
    if (task.progress !== undefined && task.progress > lastProgress && lastStep && task.step !== lastStep) {
        markStepCompleted(lastStep);
    }

    // 记录当前进度和步骤
    if (task.progress !== undefined) {
        lastProgress = task.progress;
    }
    if (task.step) {
        lastStep = task.step;
    }

    // 更新进度显示
    if (task.progress !== undefined) {
        updateTaskProgress(task);
    }

    // 检查是否完成
    if (task.status === 'success') {
        // 记录最后一个步骤为完成
        if (task.step) {
            markStepCompleted(task.step);
            updateTaskProgress(task);
        }
        stopTaskPolling();
        isTaskRunning = false;
        updateChatStatus('');
        clearTaskProgress();

        // 显示详细结果
        if (task.result) {
            if (task.result.success) {
                let resultMsg = task.result.message || '任务完成';

                // 显示评审结果详情
                if (task.result.audit_result) {
                    const ar = task.result.audit_result;
                    const totalScore = task.result.final_score || ar.total_score || ar.chapter_score || ar.score || 0;
                    const passed = task.result.passed !== false && totalScore >= 75;
                    const scoreColor = passed ? '🟢' : (totalScore >= 60 ? '🟡' : '🔴');

                    // 构建评审详情消息
                    let auditDetail = `\n${scoreColor} **自动评审结果**\n`;
                    auditDetail += `📊 总分：${totalScore}分\n`;

                    // 显示修订历史
                    if (task.result.revision_history && task.result.revision_history.length > 1) {
                        auditDetail += `\n📜 修订历程：\n`;
                        task.result.revision_history.forEach((r, i) => {
                            const passIcon = r.passed ? '✅' : '❌';
                            auditDetail += `   ${passIcon} 第${r.attempt}次：${r.score}分\n`;
                        });
                    }

                    // 添加各项评分（如果有）
                    const subScores = [];
                    if (ar.continuity_score) subScores.push(`连贯性:${ar.continuity_score}`);
                    if (ar.quality_score) subScores.push(`质量:${ar.quality_score}`);
                    if (ar.grammar_score) subScores.push(`语法:${ar.grammar_score}`);
                    if (ar.alignment_score) subScores.push(`一致性:${ar.alignment_score}`);
                    if (subScores.length > 0) {
                        auditDetail += `📋 ${subScores.join(' | ')}\n`;
                    }

                    // 显示字数
                    if (ar.word_count) {
                        auditDetail += `📝 字数：${ar.word_count}字\n`;
                    }

                    // 建议
                    if (passed) {
                        auditDetail += `\n✅ 质量达标，可继续创作下一章`;
                    } else if (task.result.suggest_revise) {
                        auditDetail += `\n⚠️ ${task.result.suggest_message || '建议修订以提升质量'}`;
                    }

                    addAIMessage(auditDetail);

                    // 显示完整评审报告（评审不通过时展示，让用户了解问题）
                    if (!passed && task.result.audit_report) {
                        displayAuditReport(task.result.audit_report);
                    }

                    // 显示章节简报（评审通过后）
                    if (passed && task.result.chapter_brief) {
                        displayChapterBrief(task.result.chapter_brief);
                    }

                    // 显示黄金三章评审结果
                    if (task.result.golden_audit) {
                        displayGoldenAudit(task.result.golden_audit);
                    }
                } else {
                    addSystemMessage(`✅ ${resultMsg}`);
                }

                // 新书创建成功：刷新书籍列表和设定文件状态
                if (task.result.book) {
                    currentBook = task.result.book;
                    await loadBookList();
                    await loadBookManagerList();
                    // 显示新书创建引导
                    setTimeout(() => showGuidance('task_completed'), 500);
                }

                // 对于文件保存类操作，显示文件链接而非大段文字
                if (task.result.content) {
                    const contentLength = task.result.content.length;
                    const isSaveOperation = task.result.saved || task.message?.includes('保存') || task.message?.includes('生成');
                    if (isSaveOperation && contentLength > 200) {
                        // 显示简洁的文件链接消息
                        const fileName = task.result.file_name || '章节内容';
                        addAIMessage(`📄 ${fileName} 已保存 (${contentLength} 字)\n<a href="javascript:void(0)" onclick="showContentPreview(${JSON.stringify(task.result.content).replace(/"/g, '&quot;')})">[点击查看内容]</a>`);
                    } else {
                        const preview = task.result.content.substring(0, 500);
                        addAIMessage(`内容预览:\n${preview}${contentLength > 500 ? '...' : ''}`);
                    }
                }
            } else {
                addSystemMessage(`❌ ${task.result.message || '任务失败'}`);
            }
        } else {
            addSystemMessage(`✅ 任务完成: ${task.message}`);
        }
        
        // 刷新章节列表和锁状态
        await loadChapterList();
        await updateDocStatus();

        // 根据任务类型显示引导
        setTimeout(async () => {
            const taskName = task.name || '';
            if (taskName.includes('续写') || taskName.includes('章')) {
                await showGuidance('chapter_completed');
            } else {
                await showGuidance('task_completed');
            }
        }, 500);
        
    } else if (task.status === 'failed') {
        stopTaskPolling();
        isTaskRunning = false;
        updateChatStatus('');
        clearTaskProgress();
        addSystemMessage(`❌ 任务失败: ${task.error || task.message}`);
        // 刷新章节锁状态
        await refreshChapterLocks();
        await loadChapterList();
        
    } else if (task.status === 'cancelled') {
        stopTaskPolling();
        isTaskRunning = false;
        updateChatStatus('');
        addSystemMessage(`⚠️ 任务已取消`);
        // 刷新章节锁状态
        await refreshChapterLocks();
        await loadChapterList();

    } else if (task.status === 'terminated') {
        stopTaskPolling();
        isTaskRunning = false;
        updateChatStatus('');
        clearTaskProgress();
        addSystemMessage(`⚠️ 任务已终止`);
        // 刷新章节锁状态
        await refreshChapterLocks();
        await loadChapterList();
    }
}

// ==================== 任务终止 ====================

async function terminateTask(taskId) {
    if (!taskId) return;

    const confirmed = confirm('确定要终止当前任务吗？');
    if (!confirmed) return;

    const res = await api(`/api/tasks/${taskId}`, { method: 'DELETE' });
    if (res.success) {
        addSystemMessage(`⏹️ 已发送终止请求: ${taskId}`);
    } else {
        addSystemMessage(`❌ 终止失败: ${res.message || '未知错误'}`);
    }
}

async function terminateAllTasks() {
    const confirmed = confirm('确定要终止所有运行中的任务吗？');
    if (!confirmed) return;

    const res = await api('/api/tasks/terminate-all', { method: 'POST' });
    if (res.success) {
        addSystemMessage(`⏹️ 已终止 ${res.terminated_count} 个任务`);
        // 停止轮询并清除进度显示
        stopTaskPolling();
        isTaskRunning = false;
        updateChatStatus('');
        clearTaskProgress();
        // 刷新章节锁状态
        await refreshChapterLocks();
        await loadChapterList();
    } else {
        addSystemMessage(`❌ 终止失败: ${res.message || '未知错误'}`);
    }
}

function startTaskPolling(taskId) {
    stopTaskPolling();
    currentTaskId = taskId;
    taskPollInterval = setInterval(() => pollTaskStatus(taskId), 5000);
    addSystemMessage(`🔄 任务已启动，ID: ${taskId}`);
}

function stopTaskPolling() {
    if (taskPollInterval) {
        clearInterval(taskPollInterval);
        taskPollInterval = null;
    }
    currentTaskId = null;
}

let taskProgressElement = null;
let taskStartTime = null;
let taskTimerInterval = null;

function formatDuration(seconds) {
    if (seconds < 60) {
        return `${Math.floor(seconds)}秒`;
    } else {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}分${secs}秒`;
    }
}

function updateTaskTimer() {
    if (!taskStartTime || !taskProgressElement) return;
    
    const elapsed = (Date.now() - taskStartTime) / 1000;
    const timeEl = taskProgressElement.querySelector('.task-time');
    if (timeEl) {
        timeEl.textContent = `⏱️ ${formatDuration(elapsed)}`;
    }
}

// 记录已完成步骤的列表
let completedSteps = [];

function updateTaskProgress(task) {
    // 记录任务开始时间
    if (!taskProgressElement && task.status === 'running') {
        taskStartTime = Date.now();
        completedSteps = []; // 重置已完成步骤列表
        // 启动计时器
        taskTimerInterval = setInterval(updateTaskTimer, 1000);
    }

    // 创建或更新进度显示
    if (!taskProgressElement) {
        const messages = document.getElementById('chat-messages');
        if (!messages) return;

        taskProgressElement = document.createElement('div');
        taskProgressElement.className = 'task-progress-live';
        taskProgressElement.innerHTML = `
            <div class="task-progress-header">
                <img src="/static/images/loading.gif" alt="loading" class="loading-gif" style="width: 24px; height: 24px; margin-right: 8px;">
                <span class="task-name">${task.name}</span>
                <span class="task-percent">0%</span>
                <span class="task-time">⏱️ 0秒</span>
                <button class="btn btn-danger btn-sm" onclick="terminateTask('${task.id}')" title="终止任务" style="margin-left: 8px; padding: 2px 8px; font-size: 12px;">终止</button>
                <button class="btn btn-danger btn-sm" onclick="terminateAllTasks()" title="终止所有任务" style="margin-left: 4px; padding: 2px 8px; font-size: 12px;">终止全部</button>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: 0%"></div>
            </div>
            <div class="task-step"></div>
            <div class="task-message"></div>
            <div class="task-completed-list"></div>
        `;
        messages.appendChild(taskProgressElement);
    }

    // 更新进度
    const fill = taskProgressElement.querySelector('.progress-fill');
    const percent = taskProgressElement.querySelector('.task-percent');
    const stepEl = taskProgressElement.querySelector('.task-step');
    const msgEl = taskProgressElement.querySelector('.task-message');
    const completedList = taskProgressElement.querySelector('.task-completed-list');

    if (fill) fill.style.width = task.progress + '%';
    if (percent) percent.textContent = task.progress + '%';

    // 处理当前步骤和已完成步骤
    const currentStep = task.step || '';
    const currentMsg = task.message || '';

    // 如果有新的步骤完成（进度增加且有新的step），记录到已完成列表
    if (currentStep && task.progress > 0) {
        // 检查是否已完成该步骤
        const lastCompleted = completedSteps[completedSteps.length - 1];
        if (!completedSteps.includes(currentStep) && currentStep !== task.step) {
            // 添加到已完成列表
        }

        // 显示当前正在进行
        if (stepEl) {
            stepEl.innerHTML = `<span class="step-running"><img src="/static/images/loading.gif" alt="loading" class="loading-inline"> 正在进行: ${currentStep}</span>`;
        }
        if (msgEl) {
            msgEl.textContent = currentMsg;
        }
    }

    // 如果有已完成步骤的记录，更新显示
    if (completedList && completedSteps.length > 0) {
        completedList.innerHTML = completedSteps.map(s => `<div class="step-done">✓ ${s}</div>`).join('');
    }

    // 滚动到底部
    const messages = document.getElementById('chat-messages');
    if (messages) messages.scrollTop = messages.scrollHeight;
}

// 记录完成的步骤
function markStepCompleted(stepName) {
    if (stepName && !completedSteps.includes(stepName)) {
        completedSteps.push(stepName);
    }
}

function clearTaskProgress() {
    if (taskTimerInterval) {
        clearInterval(taskTimerInterval);
        taskTimerInterval = null;
    }
    taskStartTime = null;
    if (taskProgressElement) {
        taskProgressElement.remove();
        taskProgressElement = null;
    }
}

// 创建新书（异步执行：先创建记录，后台执行工作流）
async function createNewBook() {
    const brief = document.getElementById('new-book-brief').value.trim();
    if (!brief) {
        alert('请输入创作简报');
        return;
    }
    
    closeCreateBook();
    addUserMessage(brief);
    addSystemMessage('正在创建新书...');
    
    try {
        // 创建书籍（异步执行工作流）
        const res = await api('/api/books', {
            method: 'POST',
            body: { brief }
        });
        
        if (res.success) {
            const bookId = res.book_id;
            const bookName = res.book_name;
            const taskId = res.task_id;
            
            // 设置当前书籍
            currentBook = { id: bookId, name: bookName };
            localStorage.setItem('lastBookId', bookId);
            
            // 显示写作页面
            hideWelcomeView();
            showWritingPage();
            
            addSystemMessage(`📚 书籍 "${bookName}" 创建中，正在生成创作资料...`);
            
            // 启动轮询监控创建进度
            if (taskId) {
                startTaskPolling(taskId);
            }
        } else {
            addSystemMessage(`❌ 创建失败: ${res.message}`);
        }
    } catch (error) {
        console.error('创建书籍失败:', error);
        addSystemMessage(`❌ 创建失败: ${error.message || '未知错误'}`);
    }
}

// 修改 startAutoWrite 使用异步任务
async function startAutoWrite() {
    if (!currentBook) {
        addSystemMessage('请先选择或创建一本书');
        return;
    }

    const chapterCount = parseInt(document.getElementById('auto-chapter-count').value) || 5;
    const autoReview = document.getElementById('auto-review').checked;
    const autoRevise = document.getElementById('auto-revise').checked;
    const reviewScore = parseInt(document.getElementById('auto-review-score').value) || 75;

    addSystemMessage(`🚀 开始自动续写任务（连续${chapterCount}章）`);

    const res = await api('/api/write/auto', {
        method: 'POST',
        body: JSON.stringify({
            book_id: currentBook.id,
            chapter_count: chapterCount,
            auto_review: autoReview,
            auto_revise: autoRevise,
            review_score: reviewScore
        })
    });

    if (res.success && res.task_id) {
        startTaskPolling(res.task_id);
    } else {
        addSystemMessage(`❌ 启动失败: ${res.message}`);
    }
}

// ==================== 分隔条拖动调整宽度 ====================
let isResizing = false;
let resizeStartX = 0;
let resizeStartWidth = 0;

function initResizeHandle() {
    const handle = document.getElementById('resize-handle');
    const previewPanel = document.getElementById('preview-panel');

    if (!handle || !previewPanel) return;

    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        resizeStartX = e.clientX;
        resizeStartWidth = previewPanel.offsetWidth;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        const delta = resizeStartX - e.clientX;
        const newWidth = Math.max(200, Math.min(800, resizeStartWidth + delta));
        previewPanel.style.width = newWidth + 'px';

        // 更新CSS变量
        document.documentElement.style.setProperty('--preview-width', newWidth + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            handle.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            // 保存宽度到 localStorage
            const previewPanel = document.getElementById('preview-panel');
            if (previewPanel) {
                localStorage.setItem('previewPanelWidth', previewPanel.offsetWidth);
            }
        }
    });

    // 恢复保存的宽度
    const savedWidth = localStorage.getItem('previewPanelWidth');
    if (savedWidth) {
        previewPanel.style.width = savedWidth + 'px';
        document.documentElement.style.setProperty('--preview-width', savedWidth + 'px');
    }
}

// ==================== Trash 回收站 ====================
let currentTrashItem = null;

function showTrashModal() {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }
    document.getElementById('trash-modal').classList.add('show');
    loadTrashList();
}

function closeTrashModal() {
    document.getElementById('trash-modal').classList.remove('show');
}

async function loadTrashList() {
    if (!currentBook) return;

    const res = await api(`/api/books/${currentBook.id}/trash`);
    const container = document.getElementById('trash-list');

    if (!res.success || !res.items || res.items.length === 0) {
        container.innerHTML = '<div class="trash-empty">🗑️ 回收站为空</div>';
        return;
    }

    container.innerHTML = res.items.map(item => {
        const chapterName = item.chapter_num === 0 ? '序章' : `第${item.chapter_num}章`;
        return `
        <div class="trash-item" onclick="viewTrashItem('${item.filename}')">
            <div class="trash-item-info">
                <div class="trash-item-chapter">${chapterName}</div>
                <div class="trash-item-meta">删除时间: ${item.time} | 大小: ${formatFileSize(item.size)}</div>
            </div>
            <div class="trash-item-actions">
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); viewTrashItem('${item.filename}')">查看</button>
            </div>
        </div>
    `}).join('');
}

async function viewTrashItem(filename) {
    if (!currentBook) return;

    const res = await api(`/api/books/${currentBook.id}/trash/${encodeURIComponent(filename)}`);
    if (res.success) {
        currentTrashItem = {
            filename: res.filename,
            content: res.content
        };

        document.getElementById('trash-preview-title').textContent = res.filename.replace('.md', '');
        document.getElementById('trash-preview-content').textContent = res.content;
        document.getElementById('trash-modal').classList.remove('show');
        document.getElementById('trash-preview-modal').classList.add('show');
    } else {
        addSystemMessage('加载失败: ' + res.message);
    }
}

function closeTrashPreview() {
    document.getElementById('trash-preview-modal').classList.remove('show');
    currentTrashItem = null;
}

async function restoreTrashItem() {
    if (!currentBook || !currentTrashItem) return;

    if (!confirm('确定要恢复此版本吗？\n当前章节内容（如果存在）将被移动到回收站。')) {
        return;
    }

    const res = await api(`/api/books/${currentBook.id}/trash/restore`, {
        method: 'POST',
        body: JSON.stringify({
            book_id: currentBook.id,
            filename: currentTrashItem.filename
        })
    });

    if (res.success) {
        addSystemMessage(`✅ ${res.message}`);
        closeTrashPreview();
        await loadChapterList();
    } else {
        addSystemMessage('恢复失败: ' + res.message);
    }
}

async function deleteTrashItem() {
    if (!currentBook || !currentTrashItem) return;

    if (!confirm('确定要永久删除此版本吗？\n此操作不可恢复！')) {
        return;
    }

    const res = await api(`/api/books/${currentBook.id}/trash/${encodeURIComponent(currentTrashItem.filename)}`, {
        method: 'DELETE'
    });

    if (res.success) {
        addSystemMessage('✅ 文件已永久删除');
        closeTrashPreview();
        await loadTrashList();
    } else {
        addSystemMessage('删除失败: ' + res.message);
    }
}

// ==================== 删除章节功能 ====================

// 显示删除章节确认弹窗
function deleteCurrentChapter() {
    console.log('deleteCurrentChapter called');
    const target = getTargetChapterInfo();
    console.log('Target chapter:', target);
    if (!target || !target.id) {
        addSystemMessage('请先选择一个已生成的章节');
        return;
    }

    pendingDeleteChapter = {
        id: target.id,
        number: target.number,
        name: target.name
    };
    console.log('Pending delete set:', pendingDeleteChapter);

    const message = document.getElementById('delete-chapter-message');
    message.textContent = `确定要删除【${target.name}】吗？`;

    document.getElementById('delete-chapter-modal').classList.add('show');
}

// 关闭删除章节弹窗
function closeDeleteChapterModal() {
    document.getElementById('delete-chapter-modal').classList.remove('show');
    pendingDeleteChapter = null;
}

// 确认删除章节
async function confirmDeleteChapter() {
    console.log('confirmDeleteChapter called', { currentBook, pendingDeleteChapter });
    if (!currentBook) {
        addSystemMessage('❌ 当前未选择任何书籍');
        return;
    }
    if (!pendingDeleteChapter) {
        addSystemMessage('❌ 未选择要删除的章节');
        return;
    }

    const chapterToDelete = pendingDeleteChapter;  // 保存引用
    const chapterName = chapterToDelete.name || '未知章节';

    closeDeleteChapterModal();
    addSystemMessage(`正在删除【${chapterName}】...`);

    try {
        const res = await api(`/api/books/${currentBook.id}/chapters/${chapterToDelete.number}`, {
            method: 'DELETE'
        });
        console.log('Delete response:', res);

        if (res.success) {
            addSystemMessage(`✅ ${res.message}`);
            // 清空当前章节选择
            currentChapter = null;
            selectedTargetChapter = null;
            // 刷新章节列表
            await loadChapterList();
        } else {
            addSystemMessage(`❌ 删除失败: ${res.message}`);
        }
    } catch (e) {
        console.error('Delete error:', e);
        addSystemMessage(`❌ 删除失败: ${e.message}`);
    }

    pendingDeleteChapter = null;
}

// ==================== 对话保存功能 ====================

// 显示对话导出菜单
function showChatExportMenu() {
    const modal = document.getElementById('chat-export-modal');
    if (modal) {
        // 更新消息数量
        const countEl = document.getElementById('export-message-count');
        if (countEl) {
            countEl.textContent = chatHistory.length;
        }

        // 显示/隐藏保存到书籍按钮
        const saveBtn = document.getElementById('save-to-book-btn');
        if (saveBtn) {
            saveBtn.style.display = currentBook ? 'block' : 'none';
        }

        modal.classList.add('show');
    }
}

function closeChatExportMenu() {
    const modal = document.getElementById('chat-export-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// 导出对话为 JSON 格式
function exportChatJSON() {
    if (chatHistory.length === 0) {
        addSystemMessage('当前对话为空，无需导出');
        closeChatExportMenu();
        return;
    }

    const exportData = {
        sessionId: chatSessionId,
        exportTime: new Date().toLocaleString('zh-CN'),
        book: currentBook ? {
            id: currentBook.id,
            name: currentBook.name
        } : null,
        chapter: currentChapter ? {
            id: currentChapter.id,
            number: currentChapter.number
        } : null,
        messageCount: chatHistory.length,
        messages: chatHistory
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    downloadBlob(blob, `对话记录_${getFileNameSuffix()}.json`);
    closeChatExportMenu();
    addSystemMessage('✅ 对话已导出为 JSON 格式');
}

// 导出对话为 Markdown 格式
function exportChatMarkdown() {
    if (chatHistory.length === 0) {
        addSystemMessage('当前对话为空，无需导出');
        closeChatExportMenu();
        return;
    }

    let md = `# 对话记录\n\n`;
    md += `**导出时间**: ${new Date().toLocaleString('zh-CN')}\n`;
    md += `**会话ID**: ${chatSessionId || '新会话'}\n`;

    if (currentBook) {
        md += `**书籍**: ${currentBook.name}\n`;
    }
    if (currentChapter) {
        md += `**章节**: 第${currentChapter.number}章\n`;
    }

    md += `---\n\n`;

    // 按时间分组显示
    let currentDate = '';
    chatHistory.forEach(msg => {
        // 日期分隔
        const msgDate = msg.fullTime?.split(' ')[0] || '';
        if (msgDate !== currentDate && msgDate) {
            currentDate = msgDate;
            md += `\n## ${currentDate}\n\n`;
        }

        const typeIcon = msg.type === 'user' ? '👤' : msg.type === 'ai' ? '🤖' : 'ℹ️';
        const typeName = msg.type === 'user' ? '用户' : msg.type === 'ai' ? 'AI助手' : '系统';

        md += `### ${typeIcon} ${typeName} - ${msg.time}\n\n`;
        md += `${msg.content}\n\n`;
        md += `---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    downloadBlob(blob, `对话记录_${getFileNameSuffix()}.md`);
    closeChatExportMenu();
    addSystemMessage('✅ 对话已导出为 Markdown 格式');
}

// 保存对话到书籍目录（分卷存储，每卷最多50条）
async function saveChatToBook() {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }

    if (chatHistory.length === 0) {
        addSystemMessage('当前对话为空，无需保存');
        return;
    }

    // 将消息按50条分卷
    const MESSAGES_PER_VOLUME = 50;
    const volumes = [];
    for (let i = 0; i < chatHistory.length; i += MESSAGES_PER_VOLUME) {
        volumes.push(chatHistory.slice(i, i + MESSAGES_PER_VOLUME));
    }

    let savedCount = 0;
    const today = new Date().toISOString().split('T')[0];

    for (let i = 0; i < volumes.length; i++) {
        const volume = volumes[i];
        const volumeNum = volumes.length > 1 ? `_v${i + 1}` : '';
        const fileName = `chat_log_${today}${volumeNum}.json`;

        const exportData = {
            sessionId: chatSessionId,
            exportTime: new Date().toLocaleString('zh-CN'),
            book: { id: currentBook.id, name: currentBook.name },
            chapter: currentChapter ? { id: currentChapter.id, number: currentChapter.number } : null,
            messageCount: volume.length,
            volumeIndex: i,
            totalVolumes: volumes.length,
            messages: volume
        };

        const res = await api(`/api/books/${currentBook.id}/chat-logs`, {
            method: 'POST',
            body: JSON.stringify({ filename: fileName, content: JSON.stringify(exportData, null, 2) })
        });

        if (res.success) {
            savedCount++;
        }
    }

    if (savedCount === volumes.length) {
        addSystemMessage(`✅ 对话已保存到书籍目录: 共 ${volumes.length} 卷`);
        closeChatExportMenu();
    } else {
        addSystemMessage(`❌ 保存失败: 成功 ${savedCount}/${volumes.length} 卷`);
    }
}

// 清空当前对话
function clearChatHistory() {
    if (chatHistory.length === 0) {
        addSystemMessage('当前对话为空');
        return;
    }

    if (!confirm(`确定要清空当前对话吗？\n共 ${chatHistory.length} 条消息将被清除。\n建议先导出保存。`)) {
        return;
    }

    chatHistory = [];
    chatSessionId = null;

    const messages = document.getElementById('chat-messages');
    if (messages) {
        messages.innerHTML = '';
    }

    showWelcomeView();
    addSystemMessage('对话已清空');
}

// 辅助函数：生成文件名后缀
function getFileNameSuffix() {
    const now = new Date();
    const date = now.toLocaleDateString('zh-CN').replace(/\//g, '-');
    const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }).replace(':', '');
    let suffix = `${date}_${time}`;
    if (currentBook) {
        suffix = `${currentBook.name}_${suffix}`;
    }
    return suffix;
}

// 辅助函数：下载 Blob 文件
function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// 开始新对话（重置会话）
function startNewChatSession() {
    if (chatHistory.length > 0) {
        if (!confirm('确定要开始新对话吗？\n当前对话内容将被保留在历史中。')) {
            return;
        }
    }

    chatSessionId = null;
    // 不清空 chatHistory，保留历史记录
    // 只重置会话ID，视觉上开始新对话
    addSystemMessage('已开始新对话会话');
}

// ==================== 设定文件管理 ====================
let currentSelectedDoc = null;  // 当前选中的设定文件

// 设定文件配置
const docFileConfig = {
    'planning': { name: '创作简报', category: 'main', icon: '📋' },
    'story_bible': { name: '世界观设定', category: 'main', icon: '🌍' },
    'book_rules': { name: '书籍规则', category: 'main', icon: '📜' },
    'chapter_outline': { name: '章节大纲', category: 'main', icon: '📑' },
    'current_state': { name: '当前状态', category: 'truth', icon: '📍' },
    'particle_ledger': { name: '资源账本', category: 'truth', icon: '💰' },
    'emotional_arcs': { name: '情感弧线', category: 'truth', icon: '💗' },
    'pending_hooks': { name: '伏笔总表', category: 'truth', icon: '🎣' },
    'subplot_board': { name: '支线进度板', category: 'truth', icon: '🌿' },
    'character_matrix': { name: '角色交互矩阵', category: 'truth', icon: '👥' },
    'chapter_summaries': { name: '章节摘要', category: 'truth', icon: '📖' }
};

// 加载设定文件列表
async function loadDocFilesList() {
    const container = document.getElementById('doc-files-list');
    console.log('loadDocFilesList called, currentBook:', currentBook);

    if (!currentBook) {
        container.innerHTML = '<div class="text-muted">请先选择一本书</div>';
        return;
    }

    try {
        const res = await api(`/api/truth-files`);
        console.log('API response:', res);

        if (!res.success) {
            container.innerHTML = '<div class="text-muted">加载失败: ' + (res.message || '未知错误') + '</div>';
            return;
        }

        const files = res.files || {};
        console.log('Files loaded:', Object.keys(files));
        let html = '';

        // 主设定文件
        const mainFiles = Object.entries(docFileConfig).filter(([k, v]) => v.category === 'main');
        html += '<div class="doc-files-section"><h4>📚 主设定文件</h4>';
        html += '<div class="doc-files-grid">';
        mainFiles.forEach(([key, cfg]) => {
            const content = files[key] || '';
            const wordCount = content.length;
            const isEmpty = wordCount < 10;
            const statusClass = isEmpty ? 'status-empty' : 'status-exists';
            const statusText = isEmpty ? '空' : `${Math.round(wordCount / 1000)}k字`;
            html += `
                <div class="doc-file-card ${statusClass}" onclick="viewDocFile('${key}')">
                    <div class="doc-file-icon">${cfg.icon}</div>
                    <div class="doc-file-info">
                        <div class="doc-file-name">${cfg.name}</div>
                        <div class="doc-file-meta">
                            <span class="doc-status-badge ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                    <div class="doc-file-actions">
                        <button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); regenerateDocFile('${key}')">重新生成</button>
                    </div>
                </div>
            `;
        });
        html += '</div></div>';

        // 真相文件
        const truthFiles = Object.entries(docFileConfig).filter(([k, v]) => v.category === 'truth');
        html += '<div class="doc-files-section"><h4>🔍 真相文件</h4>';
        html += '<div class="doc-files-grid">';
        truthFiles.forEach(([key, cfg]) => {
            const content = files[key] || '';
            const wordCount = content.length;
            const isEmpty = wordCount < 10;
            const statusClass = isEmpty ? 'status-empty' : 'status-exists';
            const statusText = isEmpty ? '空' : `${Math.round(wordCount / 1000)}k字`;
            html += `
                <div class="doc-file-card ${statusClass}" onclick="viewDocFile('${key}')">
                    <div class="doc-file-icon">${cfg.icon}</div>
                    <div class="doc-file-info">
                        <div class="doc-file-name">${cfg.name}</div>
                        <div class="doc-file-meta">
                            <span class="doc-status-badge ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';  // 关闭 grid
        // 添加重新生成全部真相文件的按钮
        html += '<div class="doc-files-actions"><button class="btn btn-warning" onclick="regenerateAllTruthFiles()">⚠️ 重新生成全部真相文件</button></div>';
        html += '</div>';  // 关闭 section

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="text-muted">加载失败: ' + e.message + '</div>';
    }
}

// 查看设定文件
async function viewDocFile(key) {
    if (!currentBook) return;

    const cfg = docFileConfig[key];
    if (!cfg) return;

    try {
        const res = await api('/api/truth-files');
        if (!res.success) {
            addSystemMessage('加载文件失败');
            return;
        }

        const content = res.files?.[key] || '';
        currentSelectedDoc = key;

        document.getElementById('doc-preview-title').textContent = cfg.icon + ' ' + cfg.name;
        document.getElementById('doc-preview-content').textContent = content || '(空文件)';
        document.getElementById('doc-preview-modal').classList.add('show');
    } catch (e) {
        addSystemMessage('加载文件失败: ' + e.message);
    }
}

// 关闭设定文件预览
function closeDocPreview() {
    document.getElementById('doc-preview-modal').classList.remove('show');
    currentSelectedDoc = null;
}

// 重新生成设定文件
async function regenerateDocFile(key) {
    if (!currentBook) return;

    const cfg = docFileConfig[key];
    if (!cfg) return;

    // 根据文件类型调用不同的API
    const docKeyMap = {
        'planning': 'planning',
        'story_bible': 'story_bible',
        'book_rules': 'book_rules',
        'chapter_outline': 'chapter_outline'
    };

    // 对于主设定文件，使用 regenerate API
    if (docKeyMap[key]) {
        if (!confirm(`确定要重新生成"${cfg.name}"吗？这将覆盖现有内容。`)) {
            return;
        }

        addSystemMessage(`正在重新生成"${cfg.name}"...`);

        try {
            const res = await api('/api/docs/regenerate', {
                method: 'POST',
                body: JSON.stringify({ book_id: currentBook.id, doc_key: key })
            });

            if (res.success) {
                // 显示步骤进度
                if (res.steps && res.steps.length > 0) {
                    let stepsHtml = `📋 **${cfg.name}生成进度**\n`;
                    res.steps.forEach((step, idx) => {
                        const icon = step.status === 'completed' ? '✅' : '🔄';
                        const passed = step.passed === true ? ' ✅通过' : (step.passed === false ? ' ⚠️需修订' : '');
                        stepsHtml += `${icon} ${step.name}${passed}\n`;
                    });
                    addAIMessage(stepsHtml);
                } else {
                    addSystemMessage(`✅ "${cfg.name}"重新生成完成`);
                }

                // 显示评审结果（世界观和规则）
                if (res.audit_passed !== undefined) {
                    const revisionInfo = res.revision_count > 0 ? `（修订${res.revision_count}次）` : '';
                    if (res.audit_passed) {
                        addSystemMessage(`📋 评审结果：✅ 通过${revisionInfo}`);
                    } else {
                        addSystemMessage(`📋 评审结果：⚠️ 需修订${revisionInfo}\n${res.audit_details || ''}`);
                    }
                }

                // 刷新列表
                if (document.getElementById('tab-doc-files').style.display !== 'none') {
                    await loadDocFilesList();
                }
            } else if (res.need_input) {
                // 需要用户输入，显示输入弹窗
                if (key === 'planning') {
                    showPlanningModal();
                } else {
                    addSystemMessage(`⚠️ ${res.message}`);
                }
            } else {
                addSystemMessage(`❌ 重新生成失败: ${res.message}`);
            }
        } catch (e) {
            addSystemMessage(`❌ 重新生成失败: ${e.message}`);
        }
    } else {
        // 对于真相文件，显示提示
        addSystemMessage(`💡 "${cfg.name}"由AI自动维护，可在创作章节后自动更新`);
    }
}

// 从预览模态框重新生成当前选中的文件
async function regenerateSelectedDoc() {
    if (currentSelectedDoc) {
        await regenerateDocFile(currentSelectedDoc);
        closeDocPreview();
    }
}

// 重新生成全部真相文件
async function regenerateAllTruthFiles() {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }

    const warningMsg = `⚠️ 警告：重新生成真相文件将导致小说前后文发生改变！

这意味着：
• 角色状态、物品、能力值等将被重新计算
• 伏笔记录将被重新生成
• 已生成的后续章节可能与新真相文件产生矛盾

建议：
• 如果是新书刚开始，可以重新生成
• 如果已经生成多章，建议只修复单个真相文件

确定要继续吗？`;

    if (!confirm(warningMsg)) {
        return;
    }

    // 二次确认
    if (!confirm('再次确认：此操作不可逆，确定要重新生成全部真相文件吗？')) {
        return;
    }

    addSystemMessage('正在重新生成真相文件，请稍候...');

    try {
        const res = await api('/api/truth-files/regenerate', { method: 'POST' });

        if (res.success) {
            addSystemMessage(`✅ ${res.message}`);
            // 刷新列表
            if (document.getElementById('tab-doc-files')?.style.display !== 'none') {
                await loadDocFilesList();
            }
            // 刷新设定管理模态框
            if (document.getElementById('doc-manager-modal')?.classList.contains('show')) {
                await loadDocManagerData();
            }
        } else {
            addSystemMessage(`❌ 重新生成失败: ${res.message}`);
        }
    } catch (e) {
        addSystemMessage(`❌ 重新生成失败: ${e.message}`);
    }
}

// ==================== 设定管理模态框 ====================

// 显示设定管理模态框
function showDocManager() {
    if (!currentBook) {
        addSystemMessage('请先选择一本书');
        return;
    }
    document.getElementById('doc-manager-modal').classList.add('show');
    loadDocManagerData();
}

// 关闭设定管理模态框
function closeDocManager() {
    document.getElementById('doc-manager-modal').classList.remove('show');
}

// 加载设定管理数据
async function loadDocManagerData() {
    if (!currentBook) return;

    const mainContainer = document.getElementById('doc-manager-main-list');
    const truthContainer = document.getElementById('doc-manager-truth-list');
    
    if (!mainContainer || !truthContainer) return;

    try {
        const res = await api('/api/truth-files');
        
        if (!res.success) {
            mainContainer.innerHTML = '<div class="text-muted">加载失败</div>';
            truthContainer.innerHTML = '<div class="text-muted">加载失败</div>';
            return;
        }

        const files = res.files || {};

        // 主设定文件
        let mainHtml = '';
        const mainFiles = Object.entries(docFileConfig).filter(([k, v]) => v.category === 'main');
        mainFiles.forEach(([key, cfg]) => {
            const content = files[key] || '';
            const wordCount = content.length;
            const isEmpty = wordCount < 10;
            const statusClass = isEmpty ? 'status-empty' : 'status-exists';
            const statusText = isEmpty ? '空' : `${Math.round(wordCount / 1000)}k字`;
            mainHtml += `
                <div class="doc-manager-card ${statusClass}">
                    <div class="doc-manager-card-header">
                        <span class="doc-manager-icon">${cfg.icon}</span>
                        <span class="doc-manager-name">${cfg.name}</span>
                    </div>
                    <div class="doc-manager-card-body">
                        <span class="doc-manager-status ${statusClass}">${statusText}</span>
                    </div>
                    <div class="doc-manager-card-actions">
                        <button class="btn btn-xs btn-secondary" onclick="viewDocFile('${key}'); closeDocManager();">查看</button>
                        <button class="btn btn-xs btn-primary" onclick="regenerateDocFile('${key}');">重新生成</button>
                    </div>
                </div>
            `;
        });
        mainContainer.innerHTML = mainHtml;

        // 真相文件
        let truthHtml = '';
        const truthFiles = Object.entries(docFileConfig).filter(([k, v]) => v.category === 'truth');
        truthFiles.forEach(([key, cfg]) => {
            const content = files[key] || '';
            const wordCount = content.length;
            const isEmpty = wordCount < 10;
            const statusClass = isEmpty ? 'status-empty' : 'status-exists';
            const statusText = isEmpty ? '空' : `${Math.round(wordCount / 1000)}k字`;
            truthHtml += `
                <div class="doc-manager-card ${statusClass}">
                    <div class="doc-manager-card-header">
                        <span class="doc-manager-icon">${cfg.icon}</span>
                        <span class="doc-manager-name">${cfg.name}</span>
                    </div>
                    <div class="doc-manager-card-body">
                        <span class="doc-manager-status ${statusClass}">${statusText}</span>
                    </div>
                    <div class="doc-manager-card-actions">
                        <button class="btn btn-xs btn-secondary" onclick="viewDocFile('${key}'); closeDocManager();">查看</button>
                    </div>
                </div>
            `;
        });
        truthContainer.innerHTML = truthHtml;

    } catch (e) {
        mainContainer.innerHTML = '<div class="text-muted">加载失败: ' + e.message + '</div>';
        truthContainer.innerHTML = '<div class="text-muted">加载失败</div>';
    }
}
