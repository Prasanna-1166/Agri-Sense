/* ==========================================================================
   AgriSense AI — chat.js
   AgriSense Assistant: a simple floating chat widget. No RAG, no vector
   DB, no server-side memory — conversation history lives only in this
   browser tab's memory for the current session, and is resent with
   each request so the backend can stay stateless.
   ========================================================================== */

const CropWiseChat = {
  history: [], // [{role: "user"|"assistant", content: "..."}], session-only
  open: false,

  init() {
    const fab = document.getElementById("chatFab");
    const panel = document.getElementById("chatPanel");
    const closeBtn = document.getElementById("chatCloseBtn");
    const clearBtn = document.getElementById("chatClearBtn");
    const form = document.getElementById("chatForm");
    const input = document.getElementById("chatInput");

    fab.addEventListener("click", () => this.toggle());
    closeBtn.addEventListener("click", () => this.toggle(false));
    clearBtn.addEventListener("click", () => this.clear());

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      this.send(text);
    });

    document.querySelectorAll(".chat-chip").forEach(chip => {
      chip.addEventListener("click", () => this.send(chip.dataset.q));
    });
  },

  toggle(force) {
    const panel = document.getElementById("chatPanel");
    this.open = force !== undefined ? force : !this.open;
    panel.classList.toggle("hidden", !this.open);
    if (this.open) document.getElementById("chatInput").focus();
  },

  clear() {
    this.history = [];
    document.getElementById("chatMessages").innerHTML = `
      <div class="chat-bubble chat-bubble--assistant">
        Conversation cleared. Ask me anything about your current crop, cost, seed, fertilizer, or yield.
      </div>
    `;
    document.getElementById("chatError").classList.add("hidden");
  },

  /** Build the structured context from whatever AgriSense data this
   *  browser session already has, WITHOUT re-deriving or guessing any
   *  value itself — everything here was already fetched from a real
   *  AgriSense API by prediction.js / crop_plan.js. */
  buildContext() {
    const context = {};
    const pred = CropWise.state.lastPrediction;

    if (pred) {
      if (pred.farm) context.farm = { area_ha: pred.farm.area_ha };
      if (pred.top_crop) {
        const top = pred.top_crop;
        context.top_crop = {
          crop: top.crop,
          predicted_yield_t_per_ha: top.predicted_yield_t_per_ha,
          predicted_total_production_t: top.predicted_total_production_t,
          yield_range_t_per_ha: top.yield_range_t_per_ha,
          explanation: top.explanation ? { limiting_factor: top.explanation.limiting_factor } : undefined,
        };
      }
      const profile = pred.environment_profile || {};
      const envPick = (key) => (profile[key] && profile[key].value !== undefined ? profile[key].value : undefined);
      context.environment = {
        soil_ph: envPick("ph"),
        rainfall_mm: envPick("rainfall"),
        temperature_c: envPick("temperature"),
        humidity_pct: envPick("humidity"),
      };
    }

    if (window.CropWiseCropPlan && window.CropWiseCropPlan.lastPlan) {
      context.crop_plan = window.CropWiseCropPlan.lastPlan;
    }
    if (window.CropWiseRevenue && window.CropWiseRevenue.lastRevenue) {
      context.revenue = window.CropWiseRevenue.lastRevenue;
    }
    if (window.CropWiseCalendar && window.CropWiseCalendar.lastCalendar) {
      context.calendar = window.CropWiseCalendar.lastCalendar;
    }
    if (window.CropWiseDashboard && window.CropWiseDashboard.lastFarmSummary) {
      context.farm_summary = window.CropWiseDashboard.lastFarmSummary;
    }

    return context;
  },

  appendBubble(role, text) {
    const container = document.getElementById("chatMessages");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble--${role}`;
    bubble.textContent = text;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
    return bubble;
  },

  async send(text) {
    document.getElementById("chatError").classList.add("hidden");
    this.appendBubble("user", text);
    this.history.push({ role: "user", content: text });

    const loadingBubble = this.appendBubble("loading", "Thinking…");

    const sendBtn = document.getElementById("chatSendBtn");
    sendBtn.disabled = true;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          context: this.buildContext(),
          history: this.history.slice(0, -1), // everything before this new message
        }),
      });
      const data = await res.json();
      loadingBubble.remove();

      if (!res.ok) {
        this.showError(data.error || "The AgriSense Assistant is temporarily unavailable. Please try again later.");
        return;
      }

      this.appendBubble("assistant", data.reply);
      this.history.push({ role: "assistant", content: data.reply });
    } catch (e) {
      loadingBubble.remove();
      this.showError("Could not reach the server. Please check your connection and try again.");
    } finally {
      sendBtn.disabled = false;
    }
  },

  showError(message) {
    const errEl = document.getElementById("chatError");
    errEl.textContent = message;
    errEl.classList.remove("hidden");
  },
};

document.addEventListener("DOMContentLoaded", () => CropWiseChat.init());
window.CropWiseChat = CropWiseChat;
