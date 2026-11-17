/* ==========================================================================
   AgriSense AI — revenue.js
   Revenue & Return Estimate: production × reference market price, minus
   the existing crop-plan cost figure = Estimated Gross Margin (never
   called "profit" — see services/revenue_service.py). Lives inside the
   Crop Plan & Economics page.
   ========================================================================== */

const CropWiseRevenue = {
  lastRevenue: null,

  async loadForTopCrop(data) {
    const top = data && data.top_crop;
    if (!top) return;
    const areaHa = (data.farm && data.farm.area_ha) || 1.0;
    const loc = data.location || {};

    let url = `/api/revenue/${encodeURIComponent(top.crop)}?area_ha=${encodeURIComponent(areaHa)}`;
    if (top.predicted_total_production_t !== undefined && top.predicted_total_production_t !== null) {
      url += `&production_t=${encodeURIComponent(top.predicted_total_production_t)}`;
    }
    if (loc.lat !== undefined && loc.lon !== undefined) {
      url += `&lat=${encodeURIComponent(loc.lat)}&lon=${encodeURIComponent(loc.lon)}`;
    }

    try {
      const res = await fetch(url);
      const revenue = await res.json();
      if (!res.ok) return;
      this.lastRevenue = revenue;
      this.render(revenue);
      this.patchHistory(revenue);
    } catch (e) {
      this.render(null);
    }
  },

  render(revenue) {
    const el = document.getElementById("cropPlanRevenue");
    if (!revenue) {
      el.innerHTML = `<p class="small-muted">Revenue estimate unavailable.</p>`;
      return;
    }

    const market = revenue.market_price || {};
    let html = "";

    if (market.status === "AVAILABLE") {
      html += `
        <div class="grid grid-4 dashboard-stats">
          <div class="stat-card">
            <span class="stat-label">Reference market price</span>
            <span class="stat-value">₹${CropWise.formatNumber(market.modal_price_per_quintal / 100, 2)}/kg</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Market</span>
            <span class="stat-value" style="font-size:1rem;">${market.market || "—"}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Price date</span>
            <span class="stat-value" style="font-size:1rem;">${market.price_date || "—"}</span>
          </div>
          <div class="stat-card stat-card--accent">
            <span class="stat-label">Expected gross revenue</span>
            <span class="stat-value">${revenue.gross_revenue_inr !== null ? "₹" + CropWise.formatNumber(revenue.gross_revenue_inr, 0) : "—"}</span>
          </div>
        </div>
        <p class="small-muted" style="margin-top:8px;">
          Observed range: ₹${CropWise.formatNumber((market.min_price_per_quintal || 0) / 100, 2)} – ₹${CropWise.formatNumber((market.max_price_per_quintal || 0) / 100, 2)}/kg ·
          Price type: ${market.price_type || "Modal"} · Match: ${market.match_scope || "—"} ·
          Source: AGMARKNET via data.gov.in (Open Government Data Platform)
        </p>
      `;

      if (revenue.gross_margin_inr !== null && revenue.gross_margin_inr !== undefined) {
        html += `
          <div class="profile-param" style="margin-top:10px;">
            <div><div class="profile-param-name">Estimated input cost</div></div>
            <div class="profile-param-value">₹${CropWise.formatNumber(revenue.cost_for_farm_inr, 0)}</div>
          </div>
          <div class="profile-param">
            <div><div class="profile-param-name">${revenue.gross_margin_label}</div></div>
            <div class="profile-param-value"><strong>₹${CropWise.formatNumber(revenue.gross_margin_inr, 0)}</strong></div>
          </div>
        `;
      }
      html += `<p class="small-muted" style="margin-top:8px;">${revenue.note || ""}</p>`;
    } else {
      html += `<p class="small-muted">Market price: currently unavailable (${market.note || "no verified source found"}).</p>`;
      html += `<p class="small-muted">Revenue estimate cannot be calculated until a verified market price is available. The rest of your crop plan is unaffected.</p>`;
    }

    html += `<div class="notice-box" style="margin-top:10px;">${revenue.disclaimer || ""}</div>`;
    el.innerHTML = html;
  },

  /** Best-effort: attach revenue/cost figures to the history entry this
   *  prediction already created (see prediction.js saveToHistory). */
  patchHistory(revenue) {
    const historyId = CropWise.state.lastHistoryId;
    if (!historyId) return;
    const fields = {};
    if (revenue.cost_for_farm_inr !== null && revenue.cost_for_farm_inr !== undefined) {
      fields.estimated_cost = revenue.cost_for_farm_inr;
    }
    if (revenue.market_price && revenue.market_price.status === "AVAILABLE") {
      fields.market_price_modal_per_quintal = revenue.market_price.modal_price_per_quintal;
      fields.market_name = revenue.market_price.market;
    }
    if (revenue.gross_revenue_inr !== null && revenue.gross_revenue_inr !== undefined) {
      fields.estimated_revenue = revenue.gross_revenue_inr;
    }
    if (revenue.gross_margin_inr !== null && revenue.gross_margin_inr !== undefined) {
      fields.estimated_gross_margin = revenue.gross_margin_inr;
    }
    if (Object.keys(fields).length === 0) return;

    fetch(`/api/history/${historyId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }).catch(() => { /* best-effort */ });
  },
};

window.CropWiseRevenue = CropWiseRevenue;
