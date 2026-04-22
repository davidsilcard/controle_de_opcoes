(function () {
  const controllers = new WeakMap();

  function parseSymbols(raw) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return [...new Set(parsed.map((item) => String(item || "").trim().toUpperCase()).filter(Boolean))];
      }
    } catch (_error) {
      // Fallback para CSV simples.
    }
    return [...new Set(String(raw).split(",").map((item) => item.trim().toUpperCase()).filter(Boolean))];
  }

  function formatLocalDatetimes(root) {
    const scope = root || document;
    const nodes = scope.querySelectorAll("[data-local-datetime]");
    const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    for (const node of nodes) {
      const raw = (node.getAttribute("data-local-datetime") || "").trim();
      if (!raw) continue;
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
        const [year, month, day] = raw.split("-");
        node.textContent = `${day}/${month}/${year}`;
        node.title = raw;
        continue;
      }
      const parsed = new Date(raw);
      if (Number.isNaN(parsed.getTime())) {
        node.textContent = raw;
        continue;
      }
      node.textContent = dateFormatter.format(parsed);
      node.title = raw;
    }
  }

  function findScopedSymbols(container) {
    const root = container.querySelector("[data-live-symbols]");
    if (!root) {
      return parseSymbols(container.getAttribute("data-live-symbols"));
    }
    return parseSymbols(root.getAttribute("data-live-symbols"));
  }

  function updateStatus(container, kind, text) {
    const node = container.querySelector("[data-live-connection-status]");
    if (!node) return;
    node.className = "badge";
    if (kind === "live") {
      node.classList.add("text-bg-success");
    } else if (kind === "connecting") {
      node.classList.add("text-bg-primary");
    } else if (kind === "reconnecting") {
      node.classList.add("text-bg-warning");
    } else {
      node.classList.add("text-bg-secondary");
    }
    node.textContent = text;
  }

  class LiveMarketController {
    constructor(container) {
      this.container = container;
      this.scope = container.getAttribute("data-live-scope") || "";
      this.bootstrapUrl = container.getAttribute("data-live-bootstrap-url") || "/live-market/bootstrap";
      this.refreshUrl = container.getAttribute("data-live-refresh-url") || container.getAttribute("hx-get") || "";
      this.fallbackSeconds = Math.max(parseInt(container.getAttribute("data-live-fallback-seconds") || "60", 10) || 60, 15);
      this.symbols = findScopedSymbols(container);
      this.socket = null;
      this.refreshTimer = null;
      this.fallbackTimer = null;
      this.previousQuotes = new Map();
      this.bootstrapInFlight = false;
    }

    start() {
      formatLocalDatetimes(this.container);
      if (!this.refreshUrl || this.symbols.length === 0) {
        updateStatus(this.container, "fallback", "Snapshot");
        return;
      }
      this.ensureFallback();
      this.connect();
    }

    connect() {
      if (this.bootstrapInFlight || this.symbols.length === 0) {
        return;
      }
      this.bootstrapInFlight = true;
      updateStatus(this.container, "connecting", "Conectando");
      const params = new URLSearchParams();
      params.set("scope", this.scope);
      params.set("symbols", this.symbols.join(","));
      params.set("fallback_seconds", String(this.fallbackSeconds));
      fetch(`${this.bootstrapUrl}?${params.toString()}`, {
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`bootstrap:${response.status}`);
          }
          return response.json();
        })
        .then((payload) => this.openSocket(payload))
        .catch(() => {
          updateStatus(this.container, "fallback", "Snapshot (fallback)");
          this.ensureFallback();
        })
        .finally(() => {
          this.bootstrapInFlight = false;
        });
    }

    openSocket(payload) {
      if (!payload || !payload.ws_url || !payload.token) {
        updateStatus(this.container, "fallback", "Snapshot (fallback)");
        this.ensureFallback();
        return;
      }
      const url = `${payload.ws_url}?token=${encodeURIComponent(payload.token)}`;
      this.closeSocket();
      this.socket = new WebSocket(url);
      this.socket.addEventListener("open", () => {
        updateStatus(this.container, "live", "Ao vivo");
        this.clearFallback();
        this.socket.send(JSON.stringify({ action: "subscribe", symbols: this.symbols }));
      });
      this.socket.addEventListener("message", (event) => this.handleMessage(event));
      this.socket.addEventListener("close", () => {
        updateStatus(this.container, "reconnecting", "Reconectando");
        this.socket = null;
        this.ensureFallback();
        window.setTimeout(() => this.connect(), 3000);
      });
      this.socket.addEventListener("error", () => {
        updateStatus(this.container, "fallback", "Snapshot (fallback)");
        this.ensureFallback();
      });
    }

    handleMessage(event) {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (_error) {
        return;
      }
      if (!payload || payload.type !== "snapshot" || !Array.isArray(payload.items)) {
        return;
      }
      let changed = false;
      for (const item of payload.items) {
        const symbol = String(item.requested_symbol || item.symbol || "").trim().toUpperCase();
        if (!symbol) continue;
        const nextSignature = JSON.stringify({
          bid: item.bid ?? null,
          ask: item.ask ?? null,
          last: item.last ?? null,
          time_utc: item.time_utc ?? null,
          source: item.source ?? null,
        });
        if (this.previousQuotes.get(symbol) !== nextSignature) {
          this.previousQuotes.set(symbol, nextSignature);
          changed = true;
        }
      }
      if (changed) {
        this.scheduleRefresh();
      }
    }

    scheduleRefresh() {
      if (this.refreshTimer) {
        window.clearTimeout(this.refreshTimer);
      }
      this.refreshTimer = window.setTimeout(() => {
        if (!window.htmx || !this.refreshUrl) {
          return;
        }
        window.htmx.ajax("GET", this.refreshUrl, {
          target: this.container,
          swap: "innerHTML",
        });
      }, 500);
    }

    refreshSymbols() {
      const nextSymbols = findScopedSymbols(this.container);
      const current = this.symbols.join(",");
      const next = nextSymbols.join(",");
      if (current === next) {
        formatLocalDatetimes(this.container);
        return;
      }
      this.symbols = nextSymbols;
      this.previousQuotes.clear();
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ action: "subscribe", symbols: this.symbols }));
      } else {
        this.connect();
      }
      formatLocalDatetimes(this.container);
    }

    ensureFallback() {
      if (this.fallbackTimer) {
        return;
      }
      this.fallbackTimer = window.setInterval(() => this.scheduleRefresh(), this.fallbackSeconds * 1000);
    }

    clearFallback() {
      if (!this.fallbackTimer) {
        return;
      }
      window.clearInterval(this.fallbackTimer);
      this.fallbackTimer = null;
    }

    closeSocket() {
      if (!this.socket) {
        return;
      }
      try {
        this.socket.close();
      } catch (_error) {
        // noop
      }
      this.socket = null;
    }
  }

  function initContainer(container) {
    if (!container || controllers.has(container)) {
      return;
    }
    const controller = new LiveMarketController(container);
    controllers.set(container, controller);
    controller.start();
  }

  function initAll(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-live-scope][data-live-refresh-url]").forEach(initContainer);
  }

  document.addEventListener("DOMContentLoaded", function () {
    formatLocalDatetimes(document);
    initAll(document);
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    formatLocalDatetimes(event.target);
    const direct = controllers.get(event.target);
    if (direct) {
      direct.refreshSymbols();
      return;
    }
    const parent = event.target.closest("[data-live-scope][data-live-refresh-url]");
    if (parent && controllers.has(parent)) {
      controllers.get(parent).refreshSymbols();
      return;
    }
    initAll(event.target);
  });

  window.OpcoesLiveMarket = {
    initAll,
    formatLocalDatetimes,
  };
})();
