(function () {
  let bridge = null;
  let bridgeInitAttempts = 0;
  let bridgeInitScheduled = false;
  let state = {
    enabled: true,
    activeScope: "project",
    scopes: {
      project: { name: "Current Project", memoryDir: "", memories: [] },
      global: { name: "Global", memoryDir: "", memories: [] },
    },
  };
  let uiState = {
    query: "",
    type: "all",
    isSearchMode: false,
    searchQuery: "",
  };

  const els = {};

  function $(id) {
    return document.getElementById(id);
  }

  function resolveBridgeMethod(obj, names) {
    for (const name of names) {
      if (obj && typeof obj[name] === "function") {
        return obj[name].bind(obj);
      }
    }
    return null;
  }

  function callBridge(methodNames, args = [], timeoutMs = 6000) {
    const names = Array.isArray(methodNames) ? methodNames : [methodNames];
    return new Promise((resolve, reject) => {
      const fn = resolveBridgeMethod(bridge, names);
      if (!fn) {
        reject(new Error(`Bridge method unavailable: ${names.join(", ")}`));
        return;
      }

      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error(`Bridge call timeout: ${names[0]}`));
      }, timeoutMs);

      try {
        fn(...args, (result) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(result);
        });
      } catch (error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      }
    });
  }

  function scheduleBridgeInitRetry() {
    if (bridge || bridgeInitScheduled) {
      return;
    }
    bridgeInitScheduled = true;
    setTimeout(() => {
      bridgeInitScheduled = false;
      initBridge();
    }, 150);
  }

  function getWebChannelTransport() {
    const directQt = typeof qt !== "undefined" ? qt : null;
    const windowQt = typeof window !== "undefined" ? window.qt : null;
    const qtObj = directQt || windowQt;
    if (!qtObj) {
      return null;
    }
    return qtObj.webChannelTransport || null;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function badgeClass(type) {
    const key = String(type || "default").toLowerCase();
    return ["user", "feedback", "project", "reference", "skill"].includes(key) ? key : "default";
  }

  function render() {
    const scope = state.scopes?.[state.activeScope] || state.scopes.project;
    const allMemories = Array.isArray(scope.memories) ? scope.memories : [];
    const filteredMemories = uiState.isSearchMode ? allMemories : getFilteredMemories(allMemories);
    const staleCount = allMemories.filter((memory) => memory.stale).length;

    // Update search mode UI
    els.searchModeBar.classList.toggle("hidden", !uiState.isSearchMode);
    if (uiState.isSearchMode) {
      els.searchModeText.textContent = `Semantic search: "${uiState.searchQuery}"`;
    }

    els.countLabel.textContent = `${filteredMemories.length} of ${allMemories.length} memor${allMemories.length === 1 ? "y" : "ies"}`;
    els.staleCountLabel.textContent = staleCount ? `${staleCount} stale` : "All fresh";
    els.memoryDirLabel.textContent = scope.memoryDir || "No memory directory";
    els.projectRootLabel.textContent = scope.name || "No scope";
      const rulesScope = state.activeScope === "global" || state.activeScope === "shared" ? "Global" : "Project";
    if (els.openRulesBtn) {
      els.openRulesBtn.innerHTML = `<i class="fas fa-sliders-h"></i> ${rulesScope} Rules`;
    }
    els.enabledToggle.classList.toggle("is-on", !!state.enabled);
    els.enabledToggle.setAttribute("aria-pressed", state.enabled ? "true" : "false");
    els.searchInput.value = uiState.isSearchMode ? uiState.searchQuery : uiState.query;
    els.statusDot.classList.toggle("enabled", !!state.enabled);
    renderScopeTabs();
    renderTypeFilters(allMemories);

    const hasMemories = filteredMemories.length > 0;
    const hasSourceMemories = allMemories.length > 0;
    els.emptyState.classList.toggle("hidden", hasMemories);
    els.listView.classList.toggle("hidden", !hasMemories);

    if (!hasSourceMemories) {
      els.emptyState.querySelector("h3").textContent = "No memories saved yet";
      els.emptyState.querySelector("p").textContent = "The agent will populate this space as it learns your preferences and project rules.";
    } else if (!hasMemories) {
      els.emptyState.querySelector("h3").textContent = "No matching memories";
      els.emptyState.querySelector("p").textContent = "Try a different search phrase or switch the active filter.";
    }

    els.listView.innerHTML = filteredMemories.map(renderMemoryCard).join("");
    bindMemoryActions();
  }

  function getFilteredMemories(memories) {
    const query = uiState.query.trim().toLowerCase();
    return (memories || []).filter((memory) => {
      const typeKey = String(memory.type || "general").toLowerCase();
      const matchesType = uiState.type === "all" || typeKey === uiState.type;
      if (!matchesType) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = [
        memory.name,
        memory.filename,
        memory.description,
        memory.body,
        ...(Array.isArray(memory.keywords) ? memory.keywords : []),
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }

  function getTypeCounts(memories) {
    const counts = { all: (memories || []).length };
    (memories || []).forEach((memory) => {
      const key = String(memory.type || "general").toLowerCase();
      counts[key] = (counts[key] || 0) + 1;
    });
    return counts;
  }

  function renderTypeFilters(memories) {
    const counts = getTypeCounts(memories);
    const order = ["all", "user", "project", "reference", "feedback", "skill", "general"];
    const available = Object.keys(counts).sort((left, right) => {
      const leftIndex = order.indexOf(left);
      const rightIndex = order.indexOf(right);
      if (leftIndex === -1 && rightIndex === -1) {
        return left.localeCompare(right);
      }
      if (leftIndex === -1) {
        return 1;
      }
      if (rightIndex === -1) {
        return -1;
      }
      return leftIndex - rightIndex;
    });

    els.typeFilters.innerHTML = available.map((type) => {
      const activeClass = uiState.type === type ? "active" : "";
      const label = type === "all" ? "All" : type.charAt(0).toUpperCase() + type.slice(1);
      return `<button type="button" class="filter-chip ${activeClass}" data-type="${escapeHtml(type)}">${escapeHtml(label)} <span>${counts[type]}</span></button>`;
    }).join("");

    els.typeFilters.querySelectorAll(".filter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        uiState.type = chip.dataset.type || "all";
        render();
      });
    });
  }

  function renderMemoryCard(memory) {
    const keywords = Array.isArray(memory.keywords) ? memory.keywords : [];
    const tagMarkup = keywords.length
      ? `<div class="tag-row">${keywords.slice(0, 8).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>`
      : "";

    const staleClass = memory.stale ? "stale" : "";
    const typeText = escapeHtml(memory.type || "general");
    const safeName = escapeHtml(memory.name);
    const safeFilename = escapeHtml(memory.filename);
    const safeBody = escapeHtml(memory.body || "");
    const safePath = encodeURIComponent(memory.path || "");
    
    // Add similarity score badge for semantic search
    const similarityBadge = memory.similarity_score 
      ? `<span class="similarity-badge" title="Relevance score">${(memory.similarity_score * 100).toFixed(0)}%</span>`
      : "";

    return `
      <article class="memory-card" data-path="${safePath}">
        <div class="memory-head">
          <div class="memory-title-row">
            <div>
              <div class="memory-title">${safeName}</div>
            </div>
          </div>
          <div class="memory-meta">
            ${similarityBadge}
            <span class="badge ${badgeClass(memory.type)}">${typeText}</span>
            <span class="age ${staleClass}">${escapeHtml(memory.age || "")}</span>
          </div>
          <div class="memory-actions">
            <button class="icon-btn ghost toggle-details" type="button">Open</button>
            <button class="icon-btn danger delete-memory" type="button">Delete</button>
          </div>
        </div>
        <div class="memory-body">
          <div class="memory-body-inner">
            ${tagMarkup}
            <div class="kv">
              <label>File</label>
              <code>${safeFilename}</code>
            </div>
            <div class="content-block">
              <label>Content</label>
              <pre>${safeBody}</pre>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function bindMemoryActions() {
    document.querySelectorAll(".toggle-details").forEach((button) => {
      button.addEventListener("click", () => {
        const card = button.closest(".memory-card");
        const isExpanded = card.classList.toggle("expanded");
        button.textContent = isExpanded ? "Close" : "Open";
      });
    });

    document.querySelectorAll(".delete-memory").forEach((button) => {
      button.addEventListener("click", async () => {
        const card = button.closest(".memory-card");
        const rawPath = decodeURIComponent(card.dataset.path || "");
        const title = card.querySelector(".memory-title")?.textContent || "this memory";
        const approved = await confirmAction("Delete Memory", `Delete "${title}"? This cannot be undone.`, "Delete");
        if (!approved) {
          return;
        }
        const payload = await callBridge(["deleteMemory", "deleteMemory(QString,QString)"], [state.activeScope, rawPath]);
        receiveMemoryState(JSON.parse(payload));
      });
    });
  }

  async function refreshState() {
    if (!bridge) {
      return;
    }
    const payload = await callBridge(["refresh", "refresh()"]);
    receiveMemoryState(JSON.parse(payload));
  }

  async function onToggleChanged() {
    state.enabled = !state.enabled;
    els.enabledToggle.classList.toggle("is-on", state.enabled);
    els.enabledToggle.setAttribute("aria-pressed", state.enabled ? "true" : "false");
    els.statusDot.classList.toggle("enabled", state.enabled);

    if (!bridge || typeof bridge.setMemoryEnabled !== "function") {
      showToast("error", "Memory bridge is not ready yet.");
      render();
      return;
    }

    try {
      const payload = await callBridge(["setMemoryEnabled", "setMemoryEnabled(PyQt_PyObject)"], [Boolean(state.enabled)]);
      receiveMemoryState(JSON.parse(payload));
    } catch (error) {
      console.error("[MEMORY] Toggle update failed", error);
      showToast("error", "Failed to update memory setting.");
      render();
    }
  }

  async function onClearAll() {
    if (!bridge) {
      return;
    }
    const scope = state.scopes?.[state.activeScope] || state.scopes.project;
    const total = Array.isArray(scope.memories) ? scope.memories.length : 0;
    const approved = await confirmAction(
      "Clear All Memories",
      `Delete all ${total} memories in "${scope.name}"? This cannot be undone.`,
      "Clear All"
    );
    if (!approved) {
      return;
    }
    const payload = await callBridge(["clearAll", "clearAll(QString)"], [state.activeScope]);
    receiveMemoryState(JSON.parse(payload));
  }

  async function onSemanticSearch() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    const query = els.searchInput.value.trim();
    if (!query) {
      showToast("error", "Please enter a search query");
      return;
    }
    
    // Show loading state
    els.semanticSearchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    els.semanticSearchBtn.disabled = true;
    
    try {
      uiState.isSearchMode = true;
      uiState.searchQuery = query;
      
      const payload = await callBridge(["semanticSearch", "semanticSearch(QString)"], [query]);
      receiveMemoryState(JSON.parse(payload));
      
      showToast("success", "Semantic search complete");
    } catch (error) {
      console.error("[MEMORY] Semantic search failed", error);
      showToast("error", "Semantic search failed");
      uiState.isSearchMode = false;
    } finally {
      els.semanticSearchBtn.innerHTML = '<i class="fas fa-brain"></i>';
      els.semanticSearchBtn.disabled = false;
    }
  }

  async function onExitSearchMode() {
    if (!bridge) {
      return;
    }
    
    uiState.isSearchMode = false;
    uiState.searchQuery = "";
    
    const payload = await callBridge(["exitSearchMode", "exitSearchMode()"]);
    receiveMemoryState(JSON.parse(payload));
    showToast("success", "Exited search mode");
  }

  async function onShowStats() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    try {
      const statsJson = await callBridge(["getMemoryStats", "getMemoryStats(QString)"], [state.activeScope]);
      const stats = JSON.parse(statsJson);
      
      // Show stats modal
      showStatsModal(stats);
    } catch (error) {
      console.error("[MEMORY] Failed to load stats", error);
      showToast("error", "Failed to load memory statistics");
    }
  }

  function showStatsModal(stats) {
    els.modalHost.innerHTML = `
      <div class="modal stats-modal">
        <h3><i class="fas fa-chart-bar"></i> Memory Statistics</h3>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">${stats.total}</div>
            <div class="stat-label">Total Memories</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.fresh_count}</div>
            <div class="stat-label">Fresh (< 7 days)</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.stale_count}</div>
            <div class="stat-label">Stale (> 7 days)</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.total_size_kb} KB</div>
            <div class="stat-label">Total Size</div>
          </div>
        </div>
        <div class="stats-breakdown">
          <h4>Memory Types</h4>
          <div class="type-breakdown">
            ${Object.entries(stats.type_counts).map(([type, count]) => `
              <div class="type-row">
                <span class="type-badge ${badgeClass(type)}">${type}</span>
                <span class="type-count">${count}</span>
              </div>
            `).join("")}
          </div>
        </div>
        <div class="stats-timeline">
          <p><strong>Oldest:</strong> ${stats.oldest_age}</p>
          <p><strong>Newest:</strong> ${stats.newest_age}</p>
        </div>
        <div class="modal-actions">
          <button type="button" class="ghost" data-modal-action="close">Close</button>
        </div>
      </div>
    `;
    els.modalHost.classList.remove("hidden");
    
    els.modalHost.querySelectorAll("[data-modal-action]").forEach((button) => {
      button.addEventListener("click", () => {
        els.modalHost.classList.add("hidden");
        els.modalHost.innerHTML = "";
      });
    });
  }

  function showToast(level, message) {
    const toast = document.createElement("div");
    toast.className = `toast ${level || "success"}`;
    toast.textContent = message;
    els.toastHost.appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 2600);
  }

  async function onShowConsolidation() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    try {
      // Show loading state
      els.consolidateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
      els.consolidateBtn.disabled = true;
      
      // Run consolidation (scan only, no auto-merge)
      const reportJson = await callBridge(["runConsolidation", "runConsolidation(QString,bool)"], [state.activeScope, false]);
      const report = JSON.parse(reportJson);
      
      if (report.error) {
        showToast("error", report.error);
        return;
      }
      
      // Show consolidation report modal
      showConsolidationModal(report);
      
    } catch (error) {
      console.error("[MEMORY] Consolidation failed", error);
      showToast("error", "Failed to run consolidation");
    } finally {
      els.consolidateBtn.innerHTML = '<i class="fas fa-compress-arrows-alt"></i>';
      els.consolidateBtn.disabled = false;
    }
  }

  function showConsolidationModal(report) {
    // Build stats cards
    const statsHtml = `
      <div class="stat-card">
        <div class="stat-value">${report.total_memories_scanned}</div>
        <div class="stat-label">Scanned</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${report.duplicates_found}</div>
        <div class="stat-label">Duplicate Groups</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${report.memories_merged}</div>
        <div class="stat-label">Merged</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${report.space_saved_kb} KB</div>
        <div class="stat-label">Space Saved</div>
      </div>
    `;
    els.consolidationStats.innerHTML = statsHtml;
    
    // Build clusters list
    if (report.clusters && report.clusters.length > 0) {
      const clustersHtml = report.clusters.map((cluster) => `
        <div class="cluster-card">
          <div class="cluster-header">
            <h4>${cluster.cluster_id} (${cluster.memory_count} memories)</h4>
            <span class="cluster-badge ${cluster.recommended_action}">${cluster.recommended_action.replace('_', ' ')}</span>
          </div>
          <ul class="cluster-memories">
            ${cluster.memories.map((mem) => `
              <li><strong>${escapeHtml(mem.title || mem.filename)}</strong><br><small>${escapeHtml(mem.file_path)}</small></li>
            `).join('')}
          </ul>
        </div>
      `).join('');
      els.consolidationClusters.innerHTML = clustersHtml;
    } else {
      els.consolidationClusters.innerHTML = '<p style="text-align:center;color:var(--muted);">No duplicates found!</p>';
    }
    
    // Show modal
    els.consolidationModal.classList.remove("hidden");
  }

  function hideConsolidationModal() {
    els.consolidationModal.classList.add("hidden");
    els.consolidationStats.innerHTML = '';
    els.consolidationClusters.innerHTML = '';
  }

  async function onMergeAllDuplicates() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    try {
      // Show loading state
      els.mergeAllBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Merging...';
      els.mergeAllBtn.disabled = true;
      
      // Run consolidation with auto-merge
      const reportJson = await callBridge(["runConsolidation", "runConsolidation(QString,bool)"], [state.activeScope, true]);
      const report = JSON.parse(reportJson);
      
      if (report.error) {
        showToast("error", report.error);
        return;
      }
      
      showToast("success", `Merged ${report.memories_merged} duplicate memories!`);
      
      // Close modal and refresh
      hideConsolidationModal();
      refreshState();
      
    } catch (error) {
      console.error("[MEMORY] Merge failed", error);
      showToast("error", "Failed to merge duplicates");
    } finally {
      els.mergeAllBtn.innerHTML = 'Merge All Duplicates';
      els.mergeAllBtn.disabled = false;
    }
  }

  async function loadSharedMemories() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    try {
      const resultJson = await callBridge(["getGlobalMemories", "getGlobalMemories()"]);
      const result = JSON.parse(resultJson);
      
      if (result.error) {
        showToast("error", result.error);
        return;
      }
      
      // Update UI with shared memories
      state.scopes.shared = {
        name: "Shared Across Projects",
        memoryDir: "~/.cortex/global/memory",
        memories: result.memories.map(m => ({
          ...m,
          path: m.filename,
          name: m.title,
          stale: false,
        })),
      };
      state.activeScope = "shared";
      render();
      
      // Show promote button when viewing shared memories
      els.promoteBtn.style.display = "none";
      els.syncGlobalBtn.style.display = "inline-flex";
      
    } catch (error) {
      console.error("[MEMORY] Failed to load shared memories", error);
      showToast("error", "Failed to load shared memories");
    }
  }

  async function onSyncGlobalMemories() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    try {
      els.syncGlobalBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
      els.syncGlobalBtn.disabled = true;
      
      const projectRoot = state.scopes.project.memoryDir;
      const resultJson = await callBridge(["syncGlobalMemoriesToProject", "syncGlobalMemoriesToProject(QString,bool)"], [projectRoot, true]);
      const result = JSON.parse(resultJson);
      
      if (result.error) {
        showToast("error", result.error);
        return;
      }
      
      showToast("success", `Synced ${result.global_memories_loaded} global memories to project`);
      refreshState();
      
    } catch (error) {
      console.error("[MEMORY] Sync failed", error);
      showToast("error", "Failed to sync global memories");
    } finally {
      els.syncGlobalBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Sync';
      els.syncGlobalBtn.disabled = false;
    }
  }

  async function onPromoteToGlobal() {
    if (!bridge) {
      showToast("error", "Memory bridge is not ready");
      return;
    }
    
    // Get selected memory (from UI selection)
    const selectedMemory = document.querySelector('.memory-card.selected');
    if (!selectedMemory) {
      showToast("error", "Please select a memory to promote");
      return;
    }
    
    const memoryPath = selectedMemory.dataset.path;
    if (!memoryPath) {
      showToast("error", "Memory path not found");
      return;
    }
    
    try {
      els.promoteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
      els.promoteBtn.disabled = true;
      
      const resultJson = await callBridge(["promoteToGlobal", "promoteToGlobal(QString)"], [memoryPath]);
      const result = JSON.parse(resultJson);
      
      if (result.error) {
        showToast("error", result.error);
        return;
      }
      
      showToast("success", "Memory promoted to global scope!");
      refreshState();
      
    } catch (error) {
      console.error("[MEMORY] Promote failed", error);
      showToast("error", "Failed to promote memory");
    } finally {
      els.promoteBtn.innerHTML = '<i class="fas fa-arrow-up"></i> Promote';
      els.promoteBtn.disabled = false;
    }
  }

  function closeModal() {
    els.modalHost.classList.add("hidden");
    els.modalHost.innerHTML = "";
  }

  async function waitForBridgeReady(timeoutMs = 3200) {
    if (bridge) {
      return true;
    }
    initBridge();
    const start = Date.now();
    while (!bridge && Date.now() - start < timeoutMs) {
      await new Promise((resolve) => setTimeout(resolve, 120));
      if (!bridge) {
        initBridge();
      }
    }
    return !!bridge;
  }

  function showRulesEditorModal(rulesPayload) {
    const scopeLabel = rulesPayload.scope === "global" ? "Global" : "Project";
    const safePath = escapeHtml(rulesPayload.filePath || "");
    els.modalHost.innerHTML = `
      <div class="modal rules-editor-modal">
        <h3><i class="fas fa-sliders-h"></i> ${scopeLabel} Rules Setup</h3>
        <p>Edit rules directly in IDE. These rules are higher priority than memory.</p>
        <div class="kv">
          <label>File</label>
          <code>${safePath}</code>
        </div>
        <textarea id="rulesEditorInput" class="rules-editor-input" placeholder="Write rules here..."></textarea>
        <div class="modal-actions">
          <button type="button" class="ghost" data-modal-action="cancel">Cancel</button>
          <button type="button" class="primary-btn" data-modal-action="save">Save Rules</button>
        </div>
      </div>
    `;
    els.modalHost.classList.remove("hidden");

    const input = $("rulesEditorInput");
    if (input) {
      input.value = rulesPayload.content || "";
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }

    els.modalHost.querySelector('[data-modal-action="cancel"]')?.addEventListener("click", closeModal);
    els.modalHost.querySelector('[data-modal-action="save"]')?.addEventListener("click", async () => {
      const edited = $("rulesEditorInput")?.value ?? "";
      try {
        const saveJson = await callBridge(["saveRules", "saveRules(QString,QString)"], [state.activeScope, edited]);
        const saveResult = JSON.parse(saveJson);
        if (saveResult.error) {
          showToast("error", saveResult.error);
          return;
        }
        showToast("success", `${scopeLabel} rules saved`);
        closeModal();
      } catch (error) {
        console.error("[MEMORY] Failed to save rules", error);
        showToast("error", "Failed to save rules");
      }
    });
  }

  async function onOpenRulesFolder() {
    const preTransport = !!getWebChannelTransport();
    console.info(`[MEMORY] Rules click: bridge=${!!bridge}, transport=${preTransport}, QWebChannel=${typeof QWebChannel !== "undefined"}`);
    const ready = await waitForBridgeReady();
    if (!ready) {
      console.warn("[MEMORY] Bridge still unavailable after wait; continuing to retry in background.");
      initBridge();
      showToast("error", "Rules setup is not available yet. Please retry in a second.");
      return;
    }
    try {
      const resultJson = await callBridge(["loadRules", "loadRules(QString)"], [state.activeScope], 8000);
      const result = JSON.parse(resultJson);
      if (result.error) {
        showToast("error", result.error);
        return;
      }
      showRulesEditorModal(result);
    } catch (error) {
      const keys = bridge ? Object.keys(bridge).slice(0, 40).join(", ") : "none";
      console.warn(`[MEMORY] loadRules failed. Bridge keys: ${keys}`);
      console.error("[MEMORY] Failed to open rules editor", error);
      showToast("error", "Failed to open rules setup. Please reopen Memory Manager.");
    }
  }

  function receiveMemoryState(nextState) {
    state = nextState || state;
    render();
  }

  function renderScopeTabs() {
    if (!els.scopeSwitch) {
      return;
    }
    els.scopeSwitch.querySelectorAll(".scope-tab").forEach((tab) => {
      const scope = tab.dataset.scope;
      tab.classList.toggle("active", scope === state.activeScope);
      tab.setAttribute("aria-selected", scope === state.activeScope ? "true" : "false");
    });
  }

  function bindStaticActions() {
    els.refreshBtn.addEventListener("click", refreshState);
    els.clearBtn.addEventListener("click", onClearAll);
    els.enabledToggle.addEventListener("click", onToggleChanged);
    els.statsBtn.addEventListener("click", onShowStats);
    els.consolidateBtn.addEventListener("click", onShowConsolidation);
    els.closeConsolidationModal.addEventListener("click", hideConsolidationModal);
    els.closeConsolidationModalBtn.addEventListener("click", hideConsolidationModal);
    els.mergeAllBtn.addEventListener("click", onMergeAllDuplicates);
    els.syncGlobalBtn.addEventListener("click", onSyncGlobalMemories);
    els.promoteBtn.addEventListener("click", onPromoteToGlobal);
    els.openRulesBtn.addEventListener("click", onOpenRulesFolder);
    els.semanticSearchBtn.addEventListener("click", onSemanticSearch);
    els.exitSearchBtn.addEventListener("click", onExitSearchMode);
    if (els.scopeSwitch) {
      els.scopeSwitch.querySelectorAll(".scope-tab").forEach((tab) => {
        tab.addEventListener("click", async () => {
          const next = tab.dataset.scope || "project";
          uiState.query = "";
          uiState.type = "all";
          uiState.isSearchMode = false;
          uiState.searchQuery = "";
          
          // Handle shared memories scope
          if (next === "shared") {
            loadSharedMemories();
            return;
          }
          
          if (bridge && typeof bridge.setActiveScope === "function") {
            const payload = await callBridge(["setActiveScope", "setActiveScope(QString)"], [next]);
            receiveMemoryState(JSON.parse(payload));
          } else {
            state.activeScope = next;
            render();
          }
        });
      });
    }
    els.searchInput.addEventListener("input", (event) => {
      uiState.query = event.target.value || "";
      if (!uiState.isSearchMode) {
        render();
      }
    });
    els.searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        onSemanticSearch();
      }
    });
  }

  function cacheElements() {
    els.refreshBtn = $("refreshBtn");
    els.clearBtn = $("clearBtn");
    els.statsBtn = $("statsBtn");
    els.enabledToggle = $("enabledToggle");
    els.statusDot = $("statusDot");
    els.countLabel = $("countLabel");
    els.staleCountLabel = $("staleCountLabel");
    els.projectRootLabel = $("projectRootLabel");
    els.memoryDirLabel = $("memoryDirLabel");
    els.emptyState = $("emptyState");
    els.listView = $("listView");
    els.searchInput = $("searchInput");
    els.semanticSearchBtn = $("semanticSearchBtn");
    els.searchModeBar = $("searchModeBar");
    els.exitSearchBtn = $("exitSearchBtn");
    els.searchModeText = $("searchModeText");
    els.typeFilters = $("typeFilters");
    els.toastHost = $("toastHost");
    els.modalHost = $("modalHost");
    els.scopeSwitch = $("scopeSwitch");
    els.consolidateBtn = $("consolidateBtn");
    els.consolidationModal = $("consolidationModal");
    els.consolidationStats = $("consolidationStats");
    els.consolidationClusters = $("consolidationClusters");
    els.closeConsolidationModal = $("closeConsolidationModal");
    els.closeConsolidationModalBtn = $("closeConsolidationModalBtn");
    els.mergeAllBtn = $("mergeAllBtn");
    els.syncGlobalBtn = $("syncGlobalBtn");
    els.promoteBtn = $("promoteBtn");
    els.openRulesBtn = $("openRulesBtn");
  }

  function confirmAction(title, description, actionLabel) {
    return new Promise((resolve) => {
      els.modalHost.innerHTML = `
        <div class="modal">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(description)}</p>
          <div class="modal-actions">
            <button type="button" class="ghost" data-modal-action="cancel">Cancel</button>
            <button type="button" class="danger" data-modal-action="confirm">${escapeHtml(actionLabel)}</button>
          </div>
        </div>
      `;
      els.modalHost.classList.remove("hidden");

      const cleanup = (result) => {
        els.modalHost.classList.add("hidden");
        els.modalHost.innerHTML = "";
        resolve(result);
      };

    els.modalHost.querySelectorAll("[data-modal-action]").forEach((button) => {
        button.addEventListener("click", () => {
          cleanup(button.dataset.modalAction === "confirm");
        });
      });
    });
  }

  function initBridge() {
    if (bridge) {
      return;
    }
    if (typeof window !== "undefined" && window.memoryBridge) {
      bridge = window.memoryBridge;
      console.info("[MEMORY] Using pre-initialized window.memoryBridge");
      const dataChangedSignal = bridge.data_changed || bridge["data_changed(QString)"];
      if (dataChangedSignal && typeof dataChangedSignal.connect === "function") {
        dataChangedSignal.connect((payload) => receiveMemoryState(JSON.parse(payload)));
      }
      const toastSignal = bridge.toast_requested || bridge["toast_requested(QString,QString)"];
      if (toastSignal && typeof toastSignal.connect === "function") {
        toastSignal.connect(showToast);
      }
      callBridge(["loadInitialData", "loadInitialData()"])
        .then((payload) => receiveMemoryState(JSON.parse(payload)))
        .catch((error) => {
          console.warn("[MEMORY] Failed to bootstrap from pre-initialized bridge", error);
        });
      return;
    }
    bridgeInitAttempts += 1;
    if (typeof QWebChannel === "undefined") {
      console.warn("[MEMORY] QWebChannel script not ready yet");
      scheduleBridgeInitRetry();
      return;
    }
    const transport = getWebChannelTransport();
    if (!transport) {
      const hasWindowQt = typeof window !== "undefined" && !!window.qt;
      const hasDirectQt = typeof qt !== "undefined";
      console.warn(`[MEMORY] QWebChannel transport not ready yet (attempt=${bridgeInitAttempts}, window.qt=${hasWindowQt}, qt=${hasDirectQt})`);
      scheduleBridgeInitRetry();
      return;
    }

    try {
      let callbackFired = false;
      new QWebChannel(transport, async (channel) => {
        callbackFired = true;
        const objects = channel.objects || {};
        bridge = objects.memoryBridge || objects.MemoryBridge || (typeof window !== "undefined" ? window.memoryBridge : null) || Object.values(objects)[0] || null;
        if (!bridge) {
          console.warn("[MEMORY] Bridge object missing from QWebChannel");
          scheduleBridgeInitRetry();
          return;
        }
        console.info(`[MEMORY] Bridge ready. Methods/keys: ${Object.keys(bridge).slice(0, 30).join(", ")}`);

        const dataChangedSignal = bridge.data_changed || bridge["data_changed(QString)"];
        if (dataChangedSignal && typeof dataChangedSignal.connect === "function") {
          dataChangedSignal.connect((payload) => receiveMemoryState(JSON.parse(payload)));
        }

        const toastSignal = bridge.toast_requested || bridge["toast_requested(QString,QString)"];
        if (toastSignal && typeof toastSignal.connect === "function") {
          toastSignal.connect(showToast);
        }

        const loadInitialDataFn = resolveBridgeMethod(bridge, ["loadInitialData", "loadInitialData()"]);
        if (!loadInitialDataFn) {
          showToast("error", "Memory bridge API mismatch. Please reopen window.");
          return;
        }

        const payload = await callBridge(["loadInitialData", "loadInitialData()"]);
        receiveMemoryState(JSON.parse(payload));
      });
      setTimeout(() => {
        if (!bridge && !callbackFired) {
          console.warn("[MEMORY] QWebChannel callback did not fire; retrying bridge init");
          scheduleBridgeInitRetry();
        }
      }, 500);
    } catch (error) {
      console.warn("[MEMORY] QWebChannel init threw error", error);
      scheduleBridgeInitRetry();
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    cacheElements();
    bindStaticActions();
    initBridge();
  });

  window.receiveMemoryState = receiveMemoryState;
  window.showToast = showToast;
})();
