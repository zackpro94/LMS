/**
 * AE LMS — AI Assistant Frontend Controller
 * Manages floating widget & full-page interactive AI chat with Markdown rendering.
 */

document.addEventListener('DOMContentLoaded', function() {
  const conversationHistory = [];
  let selectedProvider = 'auto';  // Default: auto-failover across all providers

  // Provider label map for the dropdown button
  const providerLabels = {
    'auto': 'Auto',
    'gemini': 'Gemini',
    'groq': 'Groq',
    'deepseek': 'DeepSeek',
    'cohere': 'Cohere'
  };

  // ---------------------------------------------------------------------------
  // Model Selector Dropdown Handler
  // ---------------------------------------------------------------------------
  const modelSelectorLabel = document.getElementById('modelSelectorLabel');
  document.querySelectorAll('.ai-model-option').forEach(function(option) {
    option.addEventListener('click', function(e) {
      e.preventDefault();
      if (this.classList.contains('disabled')) return;

      const provider = this.getAttribute('data-provider');
      selectedProvider = provider;
      if (modelSelectorLabel) {
        modelSelectorLabel.textContent = providerLabels[provider] || provider;
      }

      // Mark active item
      document.querySelectorAll('.ai-model-option').forEach(opt => opt.classList.remove('active'));
      this.classList.add('active');
    });
  });
  // Helper: Get CSRF token from cookies
  function getCsrfToken() {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, 10) === 'csrftoken=') {
          cookieValue = decodeURIComponent(cookie.substring(10));
          break;
        }
      }
    }
    return cookieValue;
  }

  // Lightweight Markdown & HTML Sanitizer Renderer
  function parseMarkdown(str) {
    if (!str) return '';
    let html = str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Code blocks ```code```
    html = html.replace(/```([\s\S]*?)```/g, '<pre class="bg-dark text-light p-2 rounded small overflow-auto"><code>$1</code></pre>');
    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code class="bg-body-tertiary px-1 rounded">$1</code>');
    // Headers ### Title
    html = html.replace(/^### (.*$)/gim, '<h6 class="fw-bold mt-2 mb-1">$1</h6>');
    html = html.replace(/^## (.*$)/gim, '<h6 class="fw-bold fs-6 mt-2 mb-1">$1</h6>');
    // Bullet lists - item
    html = html.replace(/^\s*-\s+(.*)$/gim, '• $1<br>');
    // Linebreaks
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  // ---------------------------------------------------------------------------
  // Floating AI Chat Widget Logic
  // ---------------------------------------------------------------------------
  const widgetLauncher = document.getElementById('aiWidgetToggleBtn');
  const widgetPanel = document.getElementById('aiWidgetPanel');
  const widgetCloseBtn = document.getElementById('aiWidgetCloseBtn');
  const widgetClearBtn = document.getElementById('aiWidgetClearBtn');
  const widgetForm = document.getElementById('aiWidgetForm');
  const widgetInput = document.getElementById('aiWidgetInput');
  const widgetMessages = document.getElementById('aiWidgetMessages');
  const widgetTyping = document.getElementById('aiWidgetTyping');
  const providerBadge = document.getElementById('aiProviderBadge');

  if (widgetLauncher && widgetPanel) {
    widgetLauncher.addEventListener('click', function() {
      const isVisible = widgetPanel.style.display !== 'none';
      widgetPanel.style.display = isVisible ? 'none' : 'flex';
      if (!isVisible) {
        widgetInput.focus();
        scrollToBottom(widgetMessages);
      }
    });

    if (widgetCloseBtn) {
      widgetCloseBtn.addEventListener('click', function() {
        widgetPanel.style.display = 'none';
      });
    }

    if (widgetClearBtn) {
      widgetClearBtn.addEventListener('click', function() {
        conversationHistory.length = 0;
        widgetMessages.innerHTML = `
          <div class="ai-msg ai-msg-bot fade-in">
            <div class="ai-msg-avatar"><img src="/static/img/orange.png" alt="AE AI" class="ai-avatar-img"></div>
            <div class="ai-msg-content">
              <p class="mb-0">Chat history cleared. How can I help you with AE LMS?</p>
            </div>
          </div>
        `;
      });
    }

    if (widgetForm) {
      widgetForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const prompt = widgetInput.value.trim();
        if (!prompt) return;

        widgetInput.value = '';
        sendChatMessage(prompt, widgetMessages, widgetTyping, widgetInput, document.getElementById('aiWidgetSendBtn'));
      });
    }

    // Quick suggestion chips in widget
    document.querySelectorAll('.ai-suggestion-chip').forEach(function(chip) {
      chip.addEventListener('click', function() {
        const prompt = this.getAttribute('data-prompt');
        if (prompt) {
          sendChatMessage(prompt, widgetMessages, widgetTyping, widgetInput, document.getElementById('aiWidgetSendBtn'));
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Full-Page AI Assistant Logic
  // ---------------------------------------------------------------------------
  const fullPageForm = document.getElementById('fullPageChatForm');
  const fullPageInput = document.getElementById('fullPageInput');
  const fullPageMessages = document.getElementById('fullPageChatMessages');
  const fullPageTyping = document.getElementById('fullPageTyping');
  const fullPageClearBtn = document.getElementById('fullPageClearBtn');
  const fullPageExportBtn = document.getElementById('fullPageExportBtn');
  const faqSearchInput = document.getElementById('faqSearchInput');

  if (fullPageForm) {
    fullPageForm.addEventListener('submit', function(e) {
      e.preventDefault();
      const prompt = fullPageInput.value.trim();
      if (!prompt) return;

      fullPageInput.value = '';
      sendChatMessage(prompt, fullPageMessages, fullPageTyping, fullPageInput, document.getElementById('fullPageSendBtn'));
    });

    if (fullPageClearBtn) {
      fullPageClearBtn.addEventListener('click', function() {
        conversationHistory.length = 0;
        if (fullPageMessages) {
          fullPageMessages.innerHTML = `
            <div class="ai-msg ai-msg-bot mb-4">
              <div class="ai-msg-avatar shadow-sm"><img src="/static/img/orange.png" alt="AE AI" class="ai-avatar-img"></div>
              <div class="ai-msg-content p-3 rounded-4 bg-body-subtle border shadow-sm">
                <p class="mb-0 text-secondary">Chat history cleared. Ask me anything about AE LMS!</p>
              </div>
            </div>
          `;
        }
      });
    }

    if (fullPageExportBtn) {
      fullPageExportBtn.addEventListener('click', function() {
        if (conversationHistory.length === 0) {
          alert('No chat history to export yet.');
          return;
        }
        let exportText = "=== AE LMS AI Chat Export ===\n\n";
        conversationHistory.forEach(turn => {
          exportText += `[${turn.role.toUpperCase()}]:\n${turn.content}\n\n-----------------------------------\n\n`;
        });
        const blob = new Blob([exportText], { type: 'text/plain;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ae_lms_ai_chat_${new Date().toISOString().slice(0,10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
      });
    }

    document.querySelectorAll('.full-page-chip').forEach(function(chip) {
      chip.addEventListener('click', function() {
        const prompt = this.getAttribute('data-prompt');
        if (prompt) {
          sendChatMessage(prompt, fullPageMessages, fullPageTyping, fullPageInput, document.getElementById('fullPageSendBtn'));
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Instant Live Search Filter for Knowledge Base FAQs
  // ---------------------------------------------------------------------------
  if (faqSearchInput) {
    faqSearchInput.addEventListener('input', function() {
      const query = this.value.toLowerCase().trim();
      const faqItems = document.querySelectorAll('.faq-item');
      const noResults = document.getElementById('noFaqResults');
      let visibleCount = 0;

      faqItems.forEach(item => {
        const title = item.getAttribute('data-faq-title') || '';
        const answer = item.getAttribute('data-faq-answer') || '';
        
        if (title.includes(query) || answer.includes(query)) {
          item.style.display = 'block';
          visibleCount++;
        } else {
          item.style.display = 'none';
        }
      });

      if (noResults) {
        noResults.style.display = (visibleCount === 0 && query.length > 0) ? 'block' : 'none';
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Core AJAX Chat Dispatcher
  // ---------------------------------------------------------------------------
  function sendChatMessage(prompt, messagesContainer, typingElement, inputElement, sendButton) {
    if (!prompt || !messagesContainer) return;

    // Hide suggestions container if visible
    const suggestions = document.getElementById('aiQuickSuggestions');
    if (suggestions) suggestions.style.display = 'none';

    const fullPageSuggestions = document.getElementById('fullPageSuggestions');
    if (fullPageSuggestions) fullPageSuggestions.style.display = 'none';

    // 1. Append User Message Bubble
    appendMessageBubble(messagesContainer, 'user', prompt);
    scrollToBottom(messagesContainer);

    // 2. Show Typing Indicator
    if (typingElement) typingElement.style.display = 'flex';
    if (inputElement) inputElement.disabled = true;
    if (sendButton) sendButton.disabled = true;

    // 3. Dispatch POST Request
    fetch('/api/ai-assistant/chat/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({
        prompt: prompt,
        history: conversationHistory,
        provider: selectedProvider
      })
    })
    .then(response => response.json())
    .then(data => {
      if (typingElement) typingElement.style.display = 'none';
      if (inputElement) { inputElement.disabled = false; inputElement.focus(); }
      if (sendButton) sendButton.disabled = false;

      if (data.success) {
        // Record turns in memory history
        conversationHistory.push({ role: 'user', content: prompt });
        conversationHistory.push({ role: 'model', content: data.response });

        // Append Bot Response Bubble
        appendMessageBubble(messagesContainer, 'bot', data.response, data.provider, data.notice);
        
        // Update provider badge if present
        if (providerBadge && data.provider) {
          providerBadge.textContent = data.is_fallback ? 'Smart FAQ' : 'Live AI';
          providerBadge.className = data.is_fallback 
            ? 'badge bg-warning-subtle text-warning border border-warning-subtle rounded-pill'
            : 'badge bg-success-subtle text-success border border-success-subtle rounded-pill';
        }
      } else {
        appendMessageBubble(messagesContainer, 'bot', `⚠️ Sorry, an error occurred: ${data.error || 'Failed to generate response.'}`);
      }
      scrollToBottom(messagesContainer);
    })
    .catch(error => {
      console.error('AI Chat Error:', error);
      if (typingElement) typingElement.style.display = 'none';
      if (inputElement) { inputElement.disabled = false; inputElement.focus(); }
      if (sendButton) sendButton.disabled = false;
      appendMessageBubble(messagesContainer, 'bot', '⚠️ Connection error. Please check your network connection.');
      scrollToBottom(messagesContainer);
    });
  }

  function appendMessageBubble(container, type, text, providerName, noticeText) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `ai-msg ai-msg-${type} mb-3 fade-in`;

    const htmlContent = parseMarkdown(text);
    const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (type === 'user') {
      const userInitial = (document.body.dataset.userName || 'U').charAt(0).toUpperCase();
      msgDiv.innerHTML = `
        <div class="user-avatar-circle">${userInitial}</div>
        <div class="ai-msg-content user-bubble shadow-sm">
          ${htmlContent}
          <div class="text-white-50 text-end mt-1" style="font-size: 0.68rem;">${nowStr}</div>
        </div>
      `;
    } else {
      let footerMeta = providerName ? `<div class="d-flex align-items-center justify-content-between text-muted mt-2 pt-1 border-top" style="font-size: 0.7rem;"><span><i class="bi bi-cpu me-1"></i>${providerName}</span><span>${nowStr}</span></div>` : '';
      let noticeBanner = noticeText ? `<div class="alert alert-info py-1 px-2 my-2 small" style="font-size: 0.75rem;"><i class="bi bi-info-circle me-1"></i>${noticeText}</div>` : '';

      const uniqueId = 'msg-' + Math.random().toString(36).substr(2, 9);
      msgDiv.innerHTML = `
        <div class="ai-msg-avatar shadow-sm">
          <img src="/static/img/orange.png" alt="AE AI" class="ai-avatar-img">
        </div>
        <div class="ai-msg-content bot-bubble position-relative shadow-sm">
          <button class="btn btn-sm btn-light border position-absolute top-0 end-0 m-2 copy-btn rounded-2" onclick="navigator.clipboard.writeText(this.nextElementSibling.innerText); this.innerHTML='<i class=\\'bi bi-check2 text-success\\'></i>'; setTimeout(() => this.innerHTML='<i class=\\'bi bi-copy\\'></i>', 2000)" title="Copy answer">
            <i class="bi bi-copy"></i>
          </button>
          <div>${htmlContent}</div>
          ${noticeBanner}
          ${footerMeta}
        </div>
      `;
    }

    container.appendChild(msgDiv);
  }

  function scrollToBottom(container) {
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }

  // Load Status on initialization
  fetch('/api/ai-assistant/status/')
    .then(r => r.json())
    .then(data => {
      if (data.success && providerBadge) {
        providerBadge.textContent = data.is_live_ai_available ? 'Live AI' : 'Smart FAQ';
        providerBadge.title = data.active_engine;
      }
    })
    .catch(() => {});
});
