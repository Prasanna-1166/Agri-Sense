/* ==========================================================================
   CropWise V2 — history.js
   Prediction history list, view, and delete/clear actions.
   ========================================================================== */

const CropWiseHistory = {
  charts: {},

  init() {
    document.getElementById("refreshHistoryBtn").addEventListener("click", () => this.load());
    document.getElementById("clearHistoryBtn").addEventListener("click", () => this.clearAll());

    document.querySelector('.nav-item[data-section="history"]').addEventListener("click", () => this.load());
  },

  async load() {
    const emptyEl = document.getElementById("historyEmpty");
    const listEl = document.getElementById("historyList");
    const chartsEl = document.getElementById("historyCharts");

    try {
      const res = await fetch("/api/history?limit=30");
      const data = await res.json();
      const predictions = data.predictions || [];

      if (predictions.length === 0) {
        emptyEl.classList.remove("hidden");
        chartsEl.classList.add("hidden");
        listEl.innerHTML = "";
        return;
      }

      emptyEl.classList.add("hidden");
      chartsEl.classList.remove("hidden");
      listEl.innerHTML = predictions.map(p => this.renderItem(p)).join("");

      listEl.querySelectorAll(".history-delete-btn").forEach(btn => {
        btn.addEventListener("click", () => this.deleteItem(btn.dataset.id));
      });

      this.renderCharts(predictions);

    } catch (e) {
      listEl.innerHTML = `<p class="small-muted">Could not load history.</p>`;
    }
  },

  renderItem(p) {
    const date = p.timestamp ? new Date(p.timestamp).toLocaleString() : "Unknown time";
    const locationName = p.location && p.location.lat !== undefined
      ? `${p.location.lat.toFixed(3)}, ${p.location.lon.toFixed(3)}`
      : "Unknown location";

    const cost = (typeof p.estimated_cost === "number") ? `₹${CropWise.formatNumber(p.estimated_cost, 0)}` : "—";
    const marketPrice = (typeof p.market_price_modal_per_quintal === "number")
      ? `₹${CropWise.formatNumber(p.market_price_modal_per_quintal / 100, 2)}/kg${p.market_name ? " (" + p.market_name + ")" : ""}`
      : "—";
    const revenue = (typeof p.estimated_revenue === "number") ? `₹${CropWise.formatNumber(p.estimated_revenue, 0)}` : "—";
    const margin = (typeof p.estimated_gross_margin === "number") ? `₹${CropWise.formatNumber(p.estimated_gross_margin, 0)}` : "—";

    return `
      <div class="history-item">
        <div class="history-item-main">
          <span class="history-item-crop">${p.recommended_crop ? this.capitalize(p.recommended_crop) : "—"}</span>
          <span class="history-item-meta">${date} · ${locationName} · ${p.mode || ""} mode</span>
        </div>
        <div class="history-item-stats">
          <span title="Suitability">${p.suitability_pct !== undefined && p.suitability_pct !== null ? p.suitability_pct + "%" : "—"}</span>
          <span title="Predicted yield">${p.estimated_yield !== undefined && p.estimated_yield !== null ? p.estimated_yield.toFixed(1) + " t/ha" : "—"}</span>
          <span title="Estimated cost">${cost}</span>
          <span title="Market price">${marketPrice}</span>
          <span title="Estimated revenue">${revenue}</span>
          <span title="Estimated gross margin">${margin}</span>
        </div>
        <button class="history-delete-btn" data-id="${p.id}" title="Delete">✕</button>
      </div>
    `;
  },

  renderCharts(predictions) {
    if (typeof Chart === "undefined") return; // Chart.js failed to load - list still works without charts
    const chrono = [...predictions].reverse(); // API returns newest first; charts read left-to-right

    const labels = chrono.map(p => p.timestamp ? new Date(p.timestamp).toLocaleDateString() : "—");

    this._renderLineChart("chartYieldHistory", labels,
      chrono.map(p => (typeof p.estimated_yield === "number" ? p.estimated_yield : null)),
      "Predicted yield (t/ha)", "#4C7A3D");

    const costPoints = chrono.filter(p => typeof p.estimated_cost === "number");
    document.getElementById("chartCostHistoryNote").textContent =
      costPoints.length === 0 ? "No cost data recorded yet for these predictions." : "";
    this._renderLineChart("chartCostHistory",
      costPoints.map(p => p.timestamp ? new Date(p.timestamp).toLocaleDateString() : "—"),
      costPoints.map(p => p.estimated_cost),
      "Estimated cost (₹)", "#B5651D");

    const cropCounts = {};
    predictions.forEach(p => {
      if (p.recommended_crop) cropCounts[p.recommended_crop] = (cropCounts[p.recommended_crop] || 0) + 1;
    });
    this._renderBarChart("chartCropCounts", Object.keys(cropCounts).map(c => this.capitalize(c)),
      Object.values(cropCounts), "Predictions", "#3E6B8A");

    const revenuePoints = chrono.filter(p => typeof p.estimated_revenue === "number" || typeof p.estimated_gross_margin === "number");
    document.getElementById("chartRevenueHistoryNote").textContent =
      revenuePoints.length === 0 ? "No revenue/margin data available yet - this needs a verified market price (see Crop Plan > Revenue & Return)." : "";
    if (revenuePoints.length > 0) {
      this._renderMultiLineChart("chartRevenueHistory",
        revenuePoints.map(p => p.timestamp ? new Date(p.timestamp).toLocaleDateString() : "—"),
        [
          { label: "Revenue (₹)", data: revenuePoints.map(p => (p.estimated_revenue !== undefined ? p.estimated_revenue : null)), color: "#4C7A3D" },
          { label: "Gross margin (₹)", data: revenuePoints.map(p => (p.estimated_gross_margin !== undefined ? p.estimated_gross_margin : null)), color: "#B5651D" },
        ]);
    } else {
      this._destroyIfExists("chartRevenueHistory");
    }
  },

  _destroyIfExists(id) {
    if (this.charts[id]) { this.charts[id].destroy(); delete this.charts[id]; }
  },

  _renderLineChart(canvasId, labels, data, label, color) {
    this._destroyIfExists(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    this.charts[canvasId] = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ label, data, borderColor: color, backgroundColor: color + "33", tension: 0.25, spanGaps: true }] },
      options: { responsive: true, plugins: { legend: { display: false } } },
    });
  },

  _renderMultiLineChart(canvasId, labels, series) {
    this._destroyIfExists(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    this.charts[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: series.map(s => ({ label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color + "33", tension: 0.25, spanGaps: true })),
      },
      options: { responsive: true, plugins: { legend: { display: true } } },
    });
  },

  _renderBarChart(canvasId, labels, data, label, color) {
    this._destroyIfExists(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    this.charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label, data, backgroundColor: color }] },
      options: { responsive: true, plugins: { legend: { display: false } } },
    });
  },

  async deleteItem(id) {
    if (!id) return;
    try {
      await fetch(`/api/history/${id}`, { method: "DELETE" });
      this.load();
    } catch (e) {
      CropWise.toast("Could not delete this entry.", "error");
    }
  },

  async clearAll() {
    if (!confirm("Clear all prediction history? This cannot be undone.")) return;
    try {
      await fetch("/api/history", { method: "DELETE" });
      this.load();
      CropWise.toast("History cleared.");
    } catch (e) {
      CropWise.toast("Could not clear history.", "error");
    }
  },

  capitalize(s) {
    if (!s) return "";
    return s.charAt(0).toUpperCase() + s.slice(1);
  },
};

window.CropWiseHistory = CropWiseHistory;
document.addEventListener("DOMContentLoaded", () => CropWiseHistory.init());
