/* Fundamentus owns its presentation state. Financial calculations stay on the server. */
(() => {
  "use strict";
  const cleanText = (text) => String(text ?? "").replace(/\s+/g, " ").trim();
  const filterNumber = (text) => {
    let value = text.replace(/\s|%/g, "");
    if (value.includes(",")) value = value.replace(/\./g, "").replace(",", ".");
    return value === "" ? NaN : Number(value);
  };
  const safeSpreadsheetText = (text) => /^[=+@-]/.test(text) ? "'" + text : text;

  function initGrid(grid) {
    const table = grid.querySelector(".js-sort-filter-table");
    if (!table || table.dataset.gridReady) return;
    table.dataset.gridReady = "true";
    const body = table.tBodies[0];
    const columns = Array.from(table.querySelectorAll("thead tr:first-child th[data-key]")).map((th) => ({
      key: th.dataset.key,
      label: cleanText(th.querySelector(".sort-btn").textContent),
      type: th.dataset.type,
      precision: Number(th.dataset.precision || 2),
      essential: th.dataset.essential === "true",
      th,
    }));
    const cells = new Map(Array.from(body.rows).map((row) => [row, new Map(
      Array.from(row.querySelectorAll("td[data-key]")).map((cell) => [cell.dataset.key, cell])
    )]));
    const allRows = () => Array.from(body.rows);
    const visibleRows = () => allRows().filter((row) => !row.hidden);
    const selectedRows = () => allRows().filter((row) => row.querySelector(".grid-row-select").checked);
    const filters = Array.from(table.querySelectorAll(".column-filter"));
    const selectAll = table.querySelector(".grid-select-all");
    const profile = grid.querySelector(".grid-profile");
    const scope = grid.querySelector(".grid-scope");
    const exportColumns = grid.querySelector(".grid-export-columns");
    const feedback = grid.querySelector(".grid-feedback");
    const dialog = grid.querySelector(".grid-copy-dialog");
    const output = grid.querySelector(".grid-copy-output");
    const hiddenColumns = new Set();
    const storageKey = `fundamentus.columns.v1.${grid.dataset.gridName}`;
    let activeSort = {key: null, direction: 1};
    const value = (row, column) => {
      const cell = cells.get(row).get(column.key);
      if (column.type === "text") return cleanText(cell.textContent);
      return cell.dataset.value === "" ? NaN : Number(cell.dataset.value);
    };
    const numberText = (number, column) => Number.isFinite(number) ? number.toLocaleString("pt-BR", {
      useGrouping: false, minimumFractionDigits: column.precision, maximumFractionDigits: column.precision,
    }) + (column.type === "percent" ? "%" : "") : "";
    const cellText = (row, column, spreadsheet = false) => {
      if (column.type !== "text") return numberText(value(row, column), column);
      const text = value(row, column);
      const normalized = text === "-" ? "" : text;
      return spreadsheet ? safeSpreadsheetText(normalized) : normalized;
    };
    const choice = () => {
      const filtered = visibleRows();
      const selected = selectedRows();
      const useSelection = scope.value === "auto" && selected.length > 0;
      return {
        rows: useSelection ? filtered.filter((row) => row.querySelector(".grid-row-select").checked) : filtered,
        columns: columns.filter((column) => exportColumns.value === "all" || !hiddenColumns.has(column.key)),
        useSelection,
      };
    };
    const updateHeaderHeight = () => {
      const height = table.tHead.rows[0].getBoundingClientRect().height;
      if (height) table.style.setProperty("--grid-header-height", `${height}px`);
    };
    const update = () => {
      const filtered = visibleRows();
      const selected = selectedRows();
      const filteredSelected = filtered.filter((row) => row.querySelector(".grid-row-select").checked);
      const picked = choice();
      selectAll.checked = filtered.length > 0 && filteredSelected.length === filtered.length;
      selectAll.indeterminate = filteredSelected.length > 0 && filteredSelected.length < filtered.length;
      selectAll.disabled = !filtered.length;
      allRows().forEach((row) => row.classList.toggle("grid-selected", row.querySelector(".grid-row-select").checked));
      grid.querySelector(".grid-count").textContent = `${filtered.length} de ${allRows().length} linhas carregadas`;
      grid.querySelector(".grid-selection-note").textContent = selected.length ?
        `${selected.length} selecionadas${selected.length - filteredSelected.length ? ` · ${selected.length - filteredSelected.length} fora do filtro` : ""}` : "";
      grid.querySelector(".grid-scope-label").textContent = `Copiar: ${picked.rows.length} linhas ${picked.useSelection ? "selecionadas dentro do filtro" : "filtradas"} · ${picked.columns.length} colunas · Google Planilhas: Brasil (vírgula decimal).`;
      grid.querySelectorAll(".grid-export").forEach((button) => { button.disabled = picked.rows.length === 0; });
      grid.querySelector(".grid-clear-selection").disabled = selected.length === 0;
      grid.querySelector(".grid-empty").hidden = filtered.length > 0;
      const hints = grid.querySelector(".grid-active-filters");
      hints.replaceChildren();
      filters.filter((input) => input.value.trim()).forEach((input) => {
        const column = columns.find((item) => item.key === input.dataset.key);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-outline-secondary btn-sm";
        button.textContent = `${column.label}${hiddenColumns.has(column.key) ? " (coluna oculta)" : ""}: ${input.value} ×`;
        button.setAttribute("aria-label", `Remover filtro de ${column.label}`);
        button.addEventListener("click", () => { input.value = ""; applyFilters(); });
        hints.append(button);
      });
      grid.querySelector(".grid-clear-filters").disabled = hints.childElementCount === 0;
      const wrap = grid.querySelector(".fundamentus-table-wrap");
      const overflowing = wrap.scrollWidth > wrap.clientWidth + 1;
      grid.querySelector(".grid-scroll-hint").hidden = !overflowing;
      wrap.tabIndex = overflowing ? 0 : -1;
      updateHeaderHeight();
    };
    const applyFilters = () => {
      allRows().forEach((row) => {
        row.hidden = !filters.every((input) => {
          const raw = input.value.trim().toLowerCase();
          if (!raw) return true;
          const column = columns.find((item) => item.key === input.dataset.key);
          const operator = raw.match(/^(>=|<=|>|<|=)\s*(-?[\d.,]+)\s*%?$/);
          if (operator && column.type !== "text") {
            const current = value(row, column);
            const target = filterNumber(operator[2]);
            if (!Number.isFinite(current) || !Number.isFinite(target)) return false;
            return {">=": current >= target, "<=": current <= target, ">": current > target,
              "<": current < target, "=": current === target}[operator[1]];
          }
          return cleanText(cells.get(row).get(column.key).textContent).toLowerCase()
            .includes(column.type === "text" ? raw : raw.replace(",", "."));
        });
      });
      feedback.textContent = "";
      update();
    };
    const sort = (column, direction = null) => {
      activeSort = {key: column.key, direction: direction ?? (activeSort.key === column.key ? -activeSort.direction : 1)};
      const rows = allRows();
      rows.sort((left, right) => {
        const a = value(left, column), b = value(right, column);
        if (column.type !== "text") {
          if (!Number.isFinite(a)) return Number.isFinite(b) ? 1 : 0;
          if (!Number.isFinite(b)) return -1;
          return (a - b) * activeSort.direction;
        }
        return a.toLowerCase().localeCompare(b.toLowerCase(), "pt-BR") * activeSort.direction;
      });
      rows.forEach((row) => body.append(row));
      columns.forEach((item) => {
        item.th.removeAttribute("aria-sort");
        item.th.querySelector(".sort-indicator").textContent = "";
        if (item.key === activeSort.key) {
          item.th.setAttribute("aria-sort", activeSort.direction === 1 ? "ascending" : "descending");
          item.th.querySelector(".sort-indicator").textContent = activeSort.direction === 1 ? " ▲" : " ▼";
        }
      });
      feedback.textContent = "";
      update();
    };
    const saveColumns = () => {
      try { localStorage.setItem(storageKey, JSON.stringify([...hiddenColumns])); } catch (_) { /* Optional preference only. */ }
    };
    const applyColumns = () => {
      table.querySelectorAll("[data-key]").forEach((element) => {
        if (element.matches("th, td")) element.hidden = hiddenColumns.has(element.dataset.key);
      });
      grid.querySelectorAll(".grid-column-toggle").forEach((input) => { input.checked = !hiddenColumns.has(input.dataset.key); });
      const essentialHidden = columns.filter((column) => !column.essential).map((column) => column.key);
      profile.value = hiddenColumns.size === 0 ? "all" :
        essentialHidden.length === hiddenColumns.size && essentialHidden.every((key) => hiddenColumns.has(key)) ? "essential" : "custom";
      feedback.textContent = "";
      update();
    };
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      if (Array.isArray(saved)) saved.forEach((key) => {
        if (key !== "papel" && columns.some((column) => column.key === key)) hiddenColumns.add(key);
      });
    } catch (_) { /* Storage can be blocked; the table must still work. */ }
    const options = grid.querySelector(".grid-column-options");
    columns.forEach((column) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.className = "form-check-input grid-column-toggle";
      input.dataset.key = column.key;
      input.disabled = column.key === "papel";
      input.addEventListener("change", () => {
        if (input.checked) hiddenColumns.delete(column.key); else hiddenColumns.add(column.key);
        applyColumns(); saveColumns();
      });
      label.append(input, document.createTextNode(column.label));
      options.append(label);
      const filter = filters.find((item) => item.dataset.key === column.key);
      filter.setAttribute("aria-label", `Filtrar ${column.label}`);
      column.th.querySelector(".sort-indicator").setAttribute("aria-hidden", "true");
      column.th.querySelector(".sort-btn").addEventListener("click", () => sort(column));
    });
    profile.addEventListener("change", () => {
      if (profile.value === "custom") { grid.querySelector(".grid-column-picker").open = true; return; }
      hiddenColumns.clear();
      if (profile.value === "essential") columns.filter((column) => !column.essential).forEach((column) => hiddenColumns.add(column.key));
      applyColumns(); saveColumns();
    });
    filters.forEach((input) => input.addEventListener("input", applyFilters));
    allRows().forEach((row) => row.querySelector(".grid-row-select").addEventListener("change", update));
    selectAll.addEventListener("change", () => {
      visibleRows().forEach((row) => { row.querySelector(".grid-row-select").checked = selectAll.checked; });
      update();
    });
    grid.querySelector(".grid-clear-selection").addEventListener("click", () => {
      allRows().forEach((row) => { row.querySelector(".grid-row-select").checked = false; }); update();
    });
    grid.querySelector(".grid-clear-filters").addEventListener("click", () => {
      filters.forEach((input) => { input.value = ""; }); applyFilters();
    });
    [scope, exportColumns].forEach((input) => input.addEventListener("change", () => { feedback.textContent = ""; update(); }));
    const serialize = (format, picked) => {
      if (format === "text") {
        const context = [`${grid.dataset.tableLabel} · Fundamentus: ${grid.dataset.snapshot || "indisponível"}`];
        if (grid.dataset.optionsSnapshot) context.push(`Cotações de opções: ${grid.dataset.optionsSnapshot}`);
        if (grid.dataset.expiry) context.push(`Vencimento: ${grid.dataset.expiry}`);
        // Sharing PUTs must retain execution context even in the essential profile.
        const textColumns = columns.filter((column) => picked.columns.includes(column) ||
          grid.dataset.gridName === "puts" && ["premium_source", "execution_note"].includes(column.key));
        return context.join("\n") + "\n\n" + picked.rows.map((row) => textColumns.map((column) =>
          `${column.label}: ${cellText(row, column) || "indisponível"}`
        ).join("\n")).join("\n\n");
      }
      const data = [picked.columns.map((column) => column.label), ...picked.rows.map((row) => picked.columns.map((column) => cellText(row, column, true)))];
      if (format === "tsv") return data.map((row) => row.join("\t")).join("\n");
      const escapeCsv = (text) => /[;"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
      return "\ufeff" + data.map((row) => row.map(escapeCsv).join(";")).join("\r\n");
    };
    grid.querySelectorAll(".grid-export").forEach((button) => button.addEventListener("click", async () => {
      const picked = choice();
      if (!picked.rows.length) return;
      const format = button.dataset.format;
      const text = serialize(format, picked);
      if (format === "csv") {
        const url = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
        const link = document.createElement("a");
        link.href = url;
        link.download = `fundamentus_${grid.dataset.gridName}_${grid.dataset.snapshot || "sem-data"}.csv`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        feedback.textContent = `CSV gerado: ${picked.rows.length} linhas.`;
        return;
      }
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(text);
        feedback.textContent = `${picked.rows.length} linhas copiadas${format === "tsv" ? " para Google Planilhas (Brasil)" : " como texto"}.`;
      } catch (_) {
        feedback.textContent = "Cópia automática indisponível. Use o texto selecionado para copiar manualmente.";
        output.value = text;
        if (!dialog.open) dialog.showModal();
        output.focus(); output.select();
      }
    }));
    grid.querySelector(".grid-close-dialog").addEventListener("click", () => dialog.close());
    const defaultColumn = columns.find((column) => column.key === table.dataset.defaultSortKey);
    applyColumns();
    if (defaultColumn) sort(defaultColumn, table.dataset.defaultSortDirection === "desc" ? -1 : 1);
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => {
        if (!table.isConnected) { observer.disconnect(); return; }
        update();
      });
      observer.observe(grid.querySelector(".fundamentus-table-wrap"));
      observer.observe(table.tHead.rows[0]);
    }
  }

  function initSectorChart(root) {
    const canvas = root.querySelector("#sector-chart");
    if (!canvas || canvas.dataset.chartReady) return;
    canvas.dataset.chartReady = "true";
    let data;
    try { data = JSON.parse(canvas.dataset.sectorBreakdown || "[]"); } catch (_) { return; }
    if (!Array.isArray(data)) return;
    const total = data.reduce((sum, item) => sum + (item.count || 0), 0);
    const ctx = canvas.getContext("2d");
    if (!total || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let start = -Math.PI / 2;
    data.forEach((item) => {
      const slice = item.count / total * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(canvas.width / 2, canvas.height / 2);
      ctx.arc(canvas.width / 2, canvas.height / 2, Math.min(canvas.width, canvas.height) * .45, start, start + slice);
      ctx.closePath(); ctx.fillStyle = item.color || "#888"; ctx.fill(); start += slice;
    });
  }
  function init(root = document) {
    if (root.matches?.(".fundamentus-grid")) initGrid(root);
    root.querySelectorAll(".fundamentus-grid").forEach(initGrid);
    initSectorChart(root);
  }
  // Existing hook remains available for progressive rendering and browser tests.
  window.initFundamentusInteractive = init;
  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:afterSwap", (event) => init(event.target));
  if (document.readyState !== "loading") init(document);
})();
