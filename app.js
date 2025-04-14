// --- START OF FILE static/js/app.js ---
// Wrap in IIFE to avoid polluting global scope
(function() {
    'use strict';

    // Wait for DOM to load
    document.addEventListener('DOMContentLoaded', () => {
        console.log("Ask JDXX Frontend JS Initializing...");

        // Get DOM Element References
        const chatLog = document.getElementById('chat-log');
        const chatForm = document.getElementById('chat-form');
        const userInput = document.getElementById('user-input');
        const sendButton = document.getElementById('send-button');
        const loadingIndicator = document.getElementById('loading-indicator');
        const typingIndicator = document.getElementById('typing-indicator');
        const themeToggleButton = document.getElementById('theme-toggle');
        const themeIcon = document.getElementById('theme-icon');
        const clearChatButton = document.getElementById('clear-chat-btn'); // Used on index/history
        const offlineModeCheckbox = document.getElementById('offlineMode');
        const manageSubscriptionForm = document.getElementById('manage-subscription-form'); // On subscription page

        // Check if Essential Chat Elements Exist (only critical if on chat page)
        if (document.body.contains(chatForm)) { // Check if chat form exists on this page
            if (!chatLog || !userInput || !sendButton) {
                console.error("Essential chat elements not found!");
                displayError("Error: Chat interface failed to load correctly.", chatLog);
            }
             // Initialize indicators state only on chat page
            hideIndicator(loadingIndicator);
            hideIndicator(typingIndicator);
        }

        // Configure Libraries (Marked, DOMPurify, Highlight.js)
        configureLibraries();

        // Setup Event Listeners
        setupThemeToggle(themeToggleButton, themeIcon);
        if (chatForm) setupChatForm(chatForm, userInput); // Only setup if form exists
        if (clearChatButton) setupClearChat(clearChatButton); // Setup if button exists
        if (manageSubscriptionForm) setupManageSubscription(manageSubscriptionForm);
        setupOnlineStatus(offlineModeCheckbox); // Setup online status listener

        // Initializations
        applyInitialTheme();
        updateOnlineStatus(); // Initial check

        console.log("Ask JDXX Frontend Initialized.");
    }); // End DOMContentLoaded

    // --- Library Configuration ---
    function configureLibraries() {
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            console.log("Marked.js configured.");
        } else console.warn("Marked.js not found.");
        if (typeof DOMPurify === 'undefined') console.error("DOMPurify not found! AI HTML rendering unsafe.");
        if (typeof hljs === 'undefined') console.warn("Highlight.js not found.");
    }

    // --- Helper Functions ---

    /** Appends message, parses MD, sanitizes, highlights code, scrolls */
    function addMessageToLog(text, sender, classes = []) {
        const chatLog = document.getElementById('chat-log');
        if (!chatLog) return;
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', `${sender}-message`, ...classes);
        let formattedHtml;
        if (sender === 'ai' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            try {
                formattedHtml = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
            } catch (e) { console.error("Markdown/Sanitize Error:", e); formattedHtml = escapeHtml(text).replace(/\n/g, '<br>'); }
        } else { formattedHtml = escapeHtml(text).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\*(.*?)\*/g, '<em>$1</em>').replace(/\n/g, '<br>'); }
        messageDiv.innerHTML = formattedHtml;
        chatLog.appendChild(messageDiv);
        if (sender === 'ai' && typeof hljs !== 'undefined') {
             messageDiv.querySelectorAll('pre code:not(.hljs)').forEach((block) => { try { hljs.highlightElement(block); block.classList.add('hljs'); } catch (err) { console.error("hljs error:", err); } });
        }
        chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: 'smooth' });
    }

    /** Basic HTML escaping */
    function escapeHtml(unsafe = '') {
        if (typeof unsafe !== 'string') { unsafe = String(unsafe); }
        return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    /** Toggles input/button disabled state and indicators */
    function setChatInputDisabled(disabled) {
        const userInput = document.getElementById('user-input');
        const sendButton = document.getElementById('send-button');
        const typingIndicator = document.getElementById('typing-indicator');
        const loadingIndicator = document.getElementById('loading-indicator');
        const chatForm = document.getElementById('chat-form');
        if (userInput) userInput.disabled = disabled;
        if (sendButton) sendButton.disabled = disabled;
        if (chatForm) chatForm.classList.toggle('processing', disabled);
        // Prefer typing indicator if available
        const indicatorToShow = typingIndicator || loadingIndicator;
        const indicatorToHide = typingIndicator ? loadingIndicator : null;
        toggleIndicator(indicatorToShow, disabled);
        hideIndicator(indicatorToHide);
    }

    /** Helper to show/hide indicator elements */
    function toggleIndicator(indicator, show) { if (indicator) { indicator.classList.toggle('d-none', !show); indicator.classList.toggle('d-flex', show); } }
    function hideIndicator(indicator) { if(indicator) { indicator.classList.add('d-none'); indicator.classList.remove('d-flex'); } }

    /** Displays fetch errors clearly in the chat log */
    function displayError(message, chatLogElement) {
        const chatLog = chatLogElement || document.getElementById('chat-log');
        if (!message || !chatLog) return;
        let displayMessage = "An unexpected error occurred.";
        if (message instanceof Error && message.message) {
            if (message.message.includes("Failed to fetch") || message.message.includes("NetworkError")) { displayMessage = "Cannot connect to the server. Check internet connection."; }
            else { displayMessage = message.message; }
        } else if (typeof message === 'string') { displayMessage = message; }
        addMessageToLog(`⚠️ **Error:**<br>${escapeHtml(displayMessage)}`, 'system', ['error-message', 'alert', 'alert-danger']);
    }

    // --- Theme Toggling Logic ---
    function applyTheme(theme, themeIcon) {
        document.documentElement.setAttribute('data-bs-theme', theme);
        if (themeIcon) themeIcon.textContent = theme === 'dark' ? '🌙' : '☀️';
        console.log(`Theme applied: ${theme}`);
        try { localStorage.setItem('askjdxx_theme', theme); } catch (e) { console.warn("LocalStorage theme saving failed.") }
    }
    function applyInitialTheme() {
        const themeIcon = document.getElementById('theme-icon'); let currentTheme = 'light';
        try { currentTheme = localStorage.getItem('askjdxx_theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch (e) { console.warn("LocalStorage theme loading failed.") }
        applyTheme(currentTheme, themeIcon);
    }
    function setupThemeToggle(button, icon) {
        if (button && icon) { button.addEventListener('click', () => { let newTheme = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark'; applyTheme(newTheme, icon); }); }
        else { console.warn("Theme toggle elements not found."); }
    }

    // --- Online/Offline Status ---
    function updateOnlineStatus(checkbox) {
        const isOnline = navigator.onLine;
        // console.log("Network status:", isOnline ? "Online" : "Offline"); // Less verbose logging
        if (checkbox) { checkbox.checked = !isOnline; checkbox.disabled = true; }
    }
    function setupOnlineStatus(checkbox) {
        window.addEventListener('online', () => updateOnlineStatus(checkbox));
        window.addEventListener('offline', () => updateOnlineStatus(checkbox));
    }

    // --- Event Listener Setups ---
    function setupChatForm(form, input) {
        if (form && input) {
            form.addEventListener('submit', handleChatSubmit);
            input.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && !event.shiftKey && !input.disabled) {
                    event.preventDefault(); form.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            });
        }
    }
    function setupClearChat(button) {
        if (button) { button.addEventListener('click', handleClearChat); }
    }
    function setupManageSubscription(form) {
         if (form) { form.addEventListener('submit', handleManageSubscriptionSubmit); }
    }

    // --- Event Handlers (Core Logic) ---

    /** Handles chat form submission */
    async function handleChatSubmit(event) {
        event.preventDefault();
        const userInput = document.getElementById('user-input');
        const chatLog = document.getElementById('chat-log');
        if (!userInput || !chatLog) { console.error("Chat submit aborted: Missing elements."); return; }
        const messageText = userInput.value.trim(); if (!messageText) return;

        if (!navigator.onLine) { displayError("You appear to be offline. Cannot send message.", chatLog); return; }

        const responseMode = document.querySelector('input[name="responseMode"]:checked')?.value || 'balanced';
        const factVerification = document.getElementById('factVerification')?.checked || false;

        addMessageToLog(messageText, 'user'); // Display user message
        userInput.value = ''; // Clear input
        setChatInputDisabled(true); // Disable form, show indicator

        // Hide previous errors
        chatLog.querySelectorAll('.error-message').forEach(el => el.remove());

        try {
            // Check for required global vars from base.html
            if (typeof askEndpointUrl === 'undefined' || typeof csrfToken === 'undefined') throw new Error("JS Config error: API URL/CSRF missing.");

            const payload = { text: messageText, responseMode, factVerification };
            const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
            if (csrfToken) { headers['X-CSRFToken'] = csrfToken; } // Add CSRF only if available

            const response = await fetch(askEndpointUrl, { method: 'POST', headers: headers, body: JSON.stringify(payload) });

            if (!response.ok) {
                let errorMsg = `Server error (${response.status} ${response.statusText})`; let detail = `Request failed.`;
                try { const errorData = await response.json(); detail = errorData.error || detail; } catch (e) { try { detail = await response.text(); } catch (e2) {} }
                throw new Error(`${detail} (Status: ${response.status})`);
            }

            const data = await response.json();
            addMessageToLog(data.response || "[Received empty response]", 'ai');
            // if (data.diag_tokens_used !== undefined) console.log("Tokens (diag):", data.diag_tokens_used);

        } catch (error) {
            console.error("Chat Submit Error:", error);
            displayError(error, chatLog); // Display error in chat log
        } finally {
            setChatInputDisabled(false); // Re-enable input
            if (userInput) userInput.focus();
        }
    } // End handleChatSubmit

    /** Handles clearing chat log display and optionally backend history */
    async function handleClearChat() {
        const chatLog = document.getElementById('chat-log');
        if (chatLog) {
            console.log("Clearing chat log display.");
            const initialSystemMessage = chatLog.querySelector('.system-message'); // Keep initial welcome?
            chatLog.innerHTML = ''; // Remove all content
            if(initialSystemMessage) chatLog.appendChild(initialSystemMessage); // Add back welcome message
            addMessageToLog("Chat display cleared.", "system");

            if (typeof clearHistoryUrl !== 'undefined' && clearHistoryUrl && confirm("Also clear conversation history on the server? This cannot be undone.")) {
                console.log("Attempting to clear server history...");
                setChatInputDisabled(true); // Optional: Disable chat input during clear
                try {
                    if (typeof csrfToken === 'undefined') throw new Error("CSRF token missing for clear request.");
                    const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
                    if (csrfToken) { headers['X-CSRFToken'] = csrfToken; }
                    const response = await fetch(clearHistoryUrl, { method: 'POST', headers: headers });
                    if (!response.ok) { let errorMsg = `Server error (${response.status})`; try { const d = await response.json(); errorMsg = d.error || errorMsg; } catch(e){} throw new Error(errorMsg); }
                    const data = await response.json();
                    addMessageToLog(data.message || "Server history cleared.", "system", ["alert", "alert-success"]);
                } catch(error) { console.error("Error clearing server history:", error); displayError(error, chatLog); }
                 finally { if(document.getElementById('chat-form')) setChatInputDisabled(false); } // Re-enable if disabled
            }
        }
    } // End handleClearChat

    /** Handles submission of the manage subscription form (simple redirect) */
    function handleManageSubscriptionSubmit(event) {
        const manageButton = event.target.querySelector('button[type="submit"], input[type="submit"]');
        if (manageButton) { manageButton.disabled = true; manageButton.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Redirecting...`; }
        console.log("Redirecting to Stripe Customer Portal...");
        // Allow default form submission (POST) to proceed
    } // End handleManageSubscriptionSubmit

})(); // End IIFE
// --- END OF FILE static/js/app.js ---