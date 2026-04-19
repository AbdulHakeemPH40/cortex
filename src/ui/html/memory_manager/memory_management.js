(function () {
  let bridge = null;
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
  };

  const els = {};

  function $(id) {
    return document.getElementById(id);
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
    const filteredMemories = getFilteredMemories(allMemories);
    const staleCount = allMemories.filter((memory) => memory.stale).length;

    els.countLabel.textContent = `${filteredMemories.length} of ${allMemories.length} memor${allMemories.length === 1 ? "y" : "ies"}`;
    els.staleCountLabel.textContent = staleCount ? `${staleCount} stale` : "All fresh";
    els.memoryDirLabel.textContent = scope.memoryDir || "No memory directory";
    els.projectRootLabel.textContent = scope.name || "No scope";
    els.enabledToggle.classList.toggle("is-on", !!state.enabled);
    els.enabledToggle.setAttribute("aria-pressed", state.enabled ? "true" : "false");
    els.searchInput.value = uiState.query;
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

    return `
      <article class="memory-card" data-path="${safePath}">
        <div class="memory-head">
          <div class="memory-title-row">
            <div>
              <div class="memory-title">${safeName}</div>
            </div>
          </div>
          <div class="memory-meta">
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
        const payload = await bridge.deleteMemory(state.activeScope, rawPath);
        receiveMemoryState(JSON.parse(payload));
      });
    });
  }

  async function refreshState() {
    if (!bridge) {
      return;
    }
    const payload = await bridge.refresh();
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
      const payload = await bridge.setMemoryEnabled(Boolean(state.enabled));
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
    const payload = await bridge.clearAll(state.activeScope);
    receiveMemoryState(JSON.parse(payload));
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
    if (els.scopeSwitch) {
      els.scopeSwitch.querySelectorAll(".scope-tab").forEach((tab) => {
        tab.addEventListener("click", async () => {
          const next = tab.dataset.scope || "project";
          uiState.query = "";
          uiState.type = "all";
          if (bridge && typeof bridge.setActiveScope === "function") {
            const payload = await bridge.setActiveScope(next);
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
      render();
    });
  }

  function cacheElements() {
    els.refreshBtn = $("refreshBtn");
    els.clearBtn = $("clearBtn");
    els.enabledToggle = $("enabledToggle");
    els.statusDot = $("statusDot");
    els.countLabel = $("countLabel");
    els.staleCountLabel = $("staleCountLabel");
    els.projectRootLabel = $("projectRootLabel");
    els.memoryDirLabel = $("memoryDirLabel");
    els.emptyState = $("emptyState");
    els.listView = $("listView");
    els.searchInput = $("searchInput");
    els.typeFilters = $("typeFilters");
    els.toastHost = $("toastHost");
    els.modalHost = $("modalHost");
    els.scopeSwitch = $("scopeSwitch");
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
    if (typeof qt === "undefined" || !qt.webChannelTransport) {
      showToast("error", "QWebChannel is not available.");
      return;
    }

    new QWebChannel(qt.webChannelTransport, async (channel) => {
      bridge = channel.objects.memoryBridge;
      bridge.data_changed.connect((payload) => receiveMemoryState(JSON.parse(payload)));
      bridge.toast_requested.connect(showToast);

      const payload = await bridge.loadInitialData();
      receiveMemoryState(JSON.parse(payload));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    cacheElements();
    bindStaticActions();
    initBridge();
  });

  window.receiveMemoryState = receiveMemoryState;
  window.showToast = showToast;
})();
