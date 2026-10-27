/**
 * Auction Ethiopia LMS — Realtime Search
 * 1. Global Command Palette (Ctrl+K) & Topbar Search
 * 2. Instant Live Table Search for Letter Lists (letters/ & archive/)
 */
(function () {
  'use strict';

  // =========================================================================
  // Helper Utilities
  // =========================================================================
  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function highlightMatches(text, query) {
    if (!text) return '';
    const safeText = escapeHtml(text);
    if (!query) return safeText;
    const cleanQuery = query.trim();
    if (!cleanQuery) return safeText;

    try {
      // Split query terms to highlight multiple words
      const terms = cleanQuery.split(/\s+/).filter(t => t.length > 0).map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      if (terms.length === 0) return safeText;
      const regex = new RegExp('(' + terms.join('|') + ')', 'gi');
      return safeText.replace(regex, '<mark class="search-highlight">$1</mark>');
    } catch (e) {
      return safeText;
    }
  }

  // =========================================================================
  // 1. Global Command Palette / Spotlight Search (Ctrl + K)
  // =========================================================================
  function initGlobalSearch() {
    const modalEl = document.getElementById('globalSearchModal');
    if (!modalEl) return;

    const bsModal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const searchInput = document.getElementById('globalSearchInput');
    const searchSpinner = document.getElementById('globalSearchSpinner');
    const searchClearBtn = document.getElementById('globalSearchClearBtn');
    const resultsList = document.getElementById('globalSearchResultsList');
    const initialState = document.getElementById('globalSearchInitialState');
    const emptyState = document.getElementById('globalSearchEmptyState');
    const emptyQueryText = document.getElementById('globalSearchEmptyQueryText');
    const resultCountBadge = document.getElementById('globalSearchResultCount');
    const viewAllWrapper = document.getElementById('globalSearchViewAllWrapper');
    const viewAllLink = document.getElementById('globalSearchViewAllLink');
    const filterChips = document.querySelectorAll('.global-filter-chip');

    let currentFilterType = 'ALL';
    let currentResults = [];
    let selectedIndex = -1;
    let abortController = null;

    // Trigger buttons
    document.querySelectorAll('#openGlobalSearchBtn, #openGlobalSearchBtnMobile').forEach(btn => {
      btn.addEventListener('click', () => {
        bsModal.show();
      });
    });

    // Keyboard shortcut (Ctrl+K, Cmd+K, or '/')
    document.addEventListener('keydown', function (e) {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const isCmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;

      if (isCmdOrCtrl && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        bsModal.show();
        return;
      }

      // Open on pressing '/' when not typing in an input
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
        if (!modalEl.classList.contains('show')) {
          e.preventDefault();
          bsModal.show();
        }
      }
    });

    // Auto focus search input when modal opens
    modalEl.addEventListener('shown.bs.modal', function () {
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    });

    // Reset when modal closes
    modalEl.addEventListener('hidden.bs.modal', function () {
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
      selectedIndex = -1;
    });

    // Filter chip switching
    filterChips.forEach(chip => {
      chip.addEventListener('click', function () {
        filterChips.forEach(c => c.classList.remove('active'));
        this.classList.add('active');
        currentFilterType = this.getAttribute('data-type') || 'ALL';
        executeGlobalSearch();
      });
    });

    // Clear button
    if (searchClearBtn) {
      searchClearBtn.addEventListener('click', function () {
        searchInput.value = '';
        searchInput.focus();
        executeGlobalSearch();
      });
    }

    // Input typing with debounce
    const debouncedSearch = debounce(executeGlobalSearch, 220);
    searchInput.addEventListener('input', debouncedSearch);

    // Keyboard navigation in search results
    searchInput.addEventListener('keydown', function (e) {
      if (!currentResults.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % currentResults.length;
        updateActiveResultItem();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
        updateActiveResultItem();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
          window.location.href = currentResults[selectedIndex].url;
        } else if (currentResults.length > 0) {
          window.location.href = currentResults[0].url;
        }
      }
    });

    function updateActiveResultItem() {
      const items = resultsList.querySelectorAll('.search-result-item');
      items.forEach((item, idx) => {
        if (idx === selectedIndex) {
          item.classList.add('active');
          item.scrollIntoView({ block: 'nearest' });
        } else {
          item.classList.remove('active');
        }
      });
    }

    function executeGlobalSearch() {
      const query = (searchInput.value || '').trim();

      // Show/hide clear button
      if (searchClearBtn) {
        if (query.length > 0) {
          searchClearBtn.classList.remove('d-none');
        } else {
          searchClearBtn.classList.add('d-none');
        }
      }

      // If empty query, show initial state
      if (!query) {
        if (abortController) abortController.abort();
        if (searchSpinner) searchSpinner.classList.add('d-none');
        resultsList.classList.add('d-none');
        emptyState.classList.add('d-none');
        initialState.classList.remove('d-none');
        resultCountBadge.classList.add('d-none');
        viewAllWrapper.classList.add('d-none');
        currentResults = [];
        selectedIndex = -1;
        return;
      }

      // Prepare request
      if (abortController) abortController.abort();
      abortController = new AbortController();

      if (searchSpinner) searchSpinner.classList.remove('d-none');
      initialState.classList.add('d-none');

      const url = `/api/letters/search/?q=${encodeURIComponent(query)}&type=${encodeURIComponent(currentFilterType)}&limit=20`;

      fetch(url, {
        signal: abortController.signal,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
        .then(res => res.json())
        .then(data => {
          if (searchSpinner) searchSpinner.classList.add('d-none');
          currentResults = data.results || [];
          selectedIndex = -1;

          // Update count badge
          const count = data.count || currentResults.length;
          resultCountBadge.textContent = `${count} result${count === 1 ? '' : 's'}`;
          resultCountBadge.classList.remove('d-none');

          // Update "View all" link
          if (viewAllWrapper && viewAllLink) {
            viewAllLink.href = `/letters/?search=${encodeURIComponent(query)}`;
            viewAllWrapper.classList.remove('d-none');
          }

          if (currentResults.length === 0) {
            resultsList.classList.add('d-none');
            emptyQueryText.textContent = `No letters found matching "${query}". Try searching by another keyword or Ethiopian date.`;
            emptyState.classList.remove('d-none');
          } else {
            emptyState.classList.add('d-none');
            renderGlobalSearchResults(currentResults, query);
            resultsList.classList.remove('d-none');
          }
        })
        .catch(err => {
          if (err.name === 'AbortError') return;
          if (searchSpinner) searchSpinner.classList.add('d-none');
          console.error('Global search error:', err);
        });
    }

    function renderGlobalSearchResults(letters, query) {
      resultsList.innerHTML = '';

      letters.forEach((letter, idx) => {
        const item = document.createElement('a');
        item.href = letter.url;
        item.className = 'search-result-item';
        item.setAttribute('data-index', idx);

        // Direction badge styles
        let dirBadge = '';
        if (letter.is_old_archive) {
          dirBadge = `<span class="badge bg-warning-subtle text-warning border border-warning-subtle fw-medium" style="font-size: 0.68rem;"><i class="bi bi-archive-fill me-1"></i>Archive</span>`;
        } else if (letter.direction === 'INCOMING') {
          dirBadge = `<span class="badge bg-info-subtle text-info border border-info-subtle fw-medium" style="font-size: 0.68rem;"><i class="bi bi-arrow-down-left-circle me-1"></i>Incoming</span>`;
        } else {
          dirBadge = `<span class="badge bg-primary-subtle text-primary border border-primary-subtle fw-medium" style="font-size: 0.68rem;"><i class="bi bi-arrow-up-right-circle me-1"></i>Outgoing</span>`;
        }

        // Status badge
        let statusBadge = '';
        if (letter.status) {
          const statusLower = letter.status.toLowerCase();
          let bgClass = 'bg-secondary-subtle text-secondary';
          if (statusLower.includes('receive')) bgClass = 'bg-success-subtle text-success';
          else if (statusLower.includes('review')) bgClass = 'bg-info-subtle text-info';
          else if (statusLower.includes('draft')) bgClass = 'bg-warning-subtle text-warning';
          else if (statusLower.includes('archive')) bgClass = 'bg-dark-subtle text-dark';
          statusBadge = `<span class="badge ${bgClass} fw-normal" style="font-size: 0.68rem;">${escapeHtml(letter.status_display || letter.status)}</span>`;
        }

        // Overdue warning
        let overdueBadge = '';
        if (letter.is_overdue) {
          overdueBadge = `<span class="badge bg-danger-subtle text-danger" style="font-size: 0.68rem;"><i class="bi bi-exclamation-triangle-fill me-1"></i>Overdue</span>`;
        }

        const refHighlighted = highlightMatches(letter.reference_no, query);
        const subjectHighlighted = highlightMatches(letter.subject, query);
        const partyHighlighted = highlightMatches(letter.party, query);

        item.innerHTML = `
          <div class="d-flex align-items-start justify-content-between gap-3">
            <div class="flex-grow-1 min-w-0">
              <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
                <span class="ref-badge"><i class="bi bi-file-earmark-text"></i> ${refHighlighted}</span>
                ${dirBadge}
                ${statusBadge}
                ${overdueBadge}
              </div>
              <div class="search-result-title text-truncate">
                ${subjectHighlighted}
              </div>
              <div class="search-result-meta mt-1">
                ${letter.party ? `
                  <span class="search-result-meta-item">
                    <i class="bi bi-person-circle opacity-75"></i> ${partyHighlighted}
                  </span>
                ` : ''}
                ${letter.date ? `
                  <span class="search-result-meta-item">
                    <i class="bi bi-calendar2 opacity-75"></i> ${escapeHtml(letter.date)}
                    ${letter.ethiopian_date ? `<small class="text-primary fw-medium">(${escapeHtml(letter.ethiopian_date)})</small>` : ''}
                  </span>
                ` : ''}
                ${letter.department ? `
                  <span class="search-result-meta-item">
                    <i class="bi bi-building opacity-75"></i> ${escapeHtml(letter.department)}
                  </span>
                ` : ''}
              </div>
            </div>
            <div class="search-result-arrow align-self-center">
              <i class="bi bi-arrow-right-short"></i>
            </div>
          </div>
        `;

        item.addEventListener('mouseenter', () => {
          selectedIndex = idx;
          updateActiveResultItem();
        });

        resultsList.appendChild(item);
      });
    }
  }

  // =========================================================================
  // 2. Real-time In-Table Search for Letter Lists (letters/ & archive/)
  // =========================================================================
  function initTableLiveSearch() {
    // Normal letter list search input
    const searchInput = document.getElementById('search-input');
    const searchSpinner = document.getElementById('search-spinner');
    const searchClearBtn = document.getElementById('search-clear-btn');
    const filterForm = document.getElementById('filter-form');
    const tableContainer = document.getElementById('letter-table-container');
    const subtitleCount = document.getElementById('letters-count-subtitle');

    // Archive list elements
    const archiveSearchInput = document.getElementById('archive-search-input');
    const archiveSearchSpinner = document.getElementById('archive-search-spinner');
    const archiveClearBtn = document.getElementById('archive-search-clear-btn');
    const archiveContainer = document.getElementById('archive-table-container');

    // Setup for letter_list.html
    if (searchInput && tableContainer) {
      setupTableSearch({
        input: searchInput,
        spinner: searchSpinner,
        clearBtn: searchClearBtn,
        form: filterForm,
        container: tableContainer,
        subtitleCount: subtitleCount,
        isArchive: false
      });
    }

    // Setup for old_archive_list.html
    if (archiveSearchInput && archiveContainer) {
      setupTableSearch({
        input: archiveSearchInput,
        spinner: archiveSearchSpinner,
        clearBtn: archiveClearBtn,
        form: archiveSearchInput.closest('form'),
        container: archiveContainer,
        subtitleCount: null,
        isArchive: true
      });
    }
  }

  function setupTableSearch(cfg) {
    let abortController = null;

    const performSearch = function () {
      const query = (cfg.input.value || '').trim();

      // Show/hide clear button
      if (cfg.clearBtn) {
        if (query.length > 0) {
          cfg.clearBtn.classList.remove('d-none');
        } else {
          cfg.clearBtn.classList.add('d-none');
        }
      }

      if (cfg.spinner) cfg.spinner.classList.remove('d-none');

      if (abortController) abortController.abort();
      abortController = new AbortController();

      // Gather form parameters
      const url = new URL(window.location.href);
      const params = new URLSearchParams();

      if (cfg.form) {
        const formData = new FormData(cfg.form);
        for (const [key, val] of formData.entries()) {
          const cleanVal = val.trim();
          if (cleanVal && key !== 'csrfmiddlewaretoken') {
            params.set(key, cleanVal);
          }
        }
      }

      // Explicitly set the active search term
      if (query) {
        params.set('search', query);
      } else {
        params.delete('search');
      }

      // Reset to page 1 on new search term
      params.delete('page');

      // Request URL with ajax flag
      const fetchParams = new URLSearchParams(params);
      fetchParams.set('ajax', '1');
      const fetchUrl = `${url.pathname}?${fetchParams.toString()}`;

      fetch(fetchUrl, {
        signal: abortController.signal,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
        .then(res => {
          if (!res.ok) throw new Error('Search failed');
          return res.json();
        })
        .then(data => {
          if (cfg.spinner) cfg.spinner.classList.add('d-none');

          // Swap table HTML
          if (data.table_html) {
            cfg.container.innerHTML = data.table_html;
          }

          // Update subtitle count
          if (cfg.subtitleCount && data.count_text) {
            cfg.subtitleCount.textContent = data.count_text;
          }

          // Update browser address bar without reload
          const cleanQueryString = params.toString();
          const newUrl = cleanQueryString ? `${url.pathname}?${cleanQueryString}` : url.pathname;
          window.history.replaceState({ search: query }, '', newUrl);

          // Re-bind table interaction events
          bindTableInteractions(cfg);
        })
        .catch(err => {
          if (err.name === 'AbortError') return;
          if (cfg.spinner) cfg.spinner.classList.add('d-none');
          console.error('Live search error:', err);
        });
    };

    const debouncedSearch = debounce(performSearch, 260);

    cfg.input.addEventListener('input', debouncedSearch);

    // Escape clears search
    cfg.input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (cfg.input.value) {
          cfg.input.value = '';
          performSearch();
        }
      }
    });

    // Clear button click
    if (cfg.clearBtn) {
      cfg.clearBtn.addEventListener('click', function () {
        cfg.input.value = '';
        cfg.input.focus();
        performSearch();
      });
    }

    // Intercept form submission so pressing Enter doesn't trigger full reload
    if (cfg.form) {
      cfg.form.addEventListener('submit', function (e) {
        e.preventDefault();
        performSearch();
      });
    }

    // Bind initial table events
    bindTableInteractions(cfg);
  }

  function bindTableInteractions(cfg) {
    const container = cfg.container;
    if (!container) return;

    // 1. Bulk Select All & Checkbox bindings
    const selectAll = container.querySelector('#select-all');
    const checkboxes = container.querySelectorAll('.letter-checkbox');
    const bulkBar = container.querySelector('#bulk-actions-bar');
    const selectedCount = container.querySelector('#selected-count');
    const clearSelection = container.querySelector('#clear-selection');

    function updateBulkBar() {
      const checked = container.querySelectorAll('.letter-checkbox:checked');
      const count = checked.length;
      if (selectedCount) selectedCount.textContent = count;
      if (bulkBar) {
        if (count > 0) {
          bulkBar.classList.remove('d-none');
        } else {
          bulkBar.classList.add('d-none');
        }
      }
    }

    if (selectAll) {
      selectAll.addEventListener('change', function () {
        checkboxes.forEach(cb => (cb.checked = this.checked));
        updateBulkBar();
      });
    }

    checkboxes.forEach(cb => {
      cb.addEventListener('change', updateBulkBar);
    });

    if (clearSelection) {
      clearSelection.addEventListener('click', function () {
        checkboxes.forEach(cb => (cb.checked = false));
        if (selectAll) selectAll.checked = false;
        updateBulkBar();
      });
    }

    // 2. Smooth AJAX Pagination
    container.querySelectorAll('.pagination .page-link').forEach(link => {
      link.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (!href || href === '#' || href.startsWith('javascript:')) return;
        e.preventDefault();

        // Extract query parameters from pagination link
        const targetUrl = new URL(href, window.location.origin);
        targetUrl.searchParams.set('ajax', '1');

        if (cfg.spinner) cfg.spinner.classList.remove('d-none');

        fetch(targetUrl.toString(), {
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
          .then(res => res.json())
          .then(data => {
            if (cfg.spinner) cfg.spinner.classList.add('d-none');
            if (data.table_html) {
              container.innerHTML = data.table_html;
            }
            if (cfg.subtitleCount && data.count_text) {
              cfg.subtitleCount.textContent = data.count_text;
            }

            // Update URL
            targetUrl.searchParams.delete('ajax');
            window.history.replaceState({}, '', targetUrl.pathname + targetUrl.search);

            // Re-bind
            bindTableInteractions(cfg);

            // Smooth scroll to top of table
            container.scrollIntoView({ behavior: 'smooth', block: 'start' });
          })
          .catch(err => {
            if (cfg.spinner) cfg.spinner.classList.add('d-none');
            console.error('Pagination AJAX error:', err);
            // Fallback to normal navigation
            window.location.href = href;
          });
      });
    });
  }

  // =========================================================================
  // Initialize on DOM Ready
  // =========================================================================
  document.addEventListener('DOMContentLoaded', function () {
    initGlobalSearch();
    initTableLiveSearch();
  });
})();
