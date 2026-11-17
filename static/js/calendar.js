/* ==========================================================================
   AgriSense AI — calendar.js
   Crop Calendar: harvest window (sowing date + verified duration) and
   any day-anchored agronomy events/stage notes already sourced in the
   Crop Plan data. Lives inside the Crop Plan & Economics page.
   ========================================================================== */

const CropWiseCalendar = {
  lastCalendar: null,

  init() {
    const input = document.getElementById("calendarSowingDate");
    if (input) {
      input.addEventListener("change", () => {
        const crop = CropWise.state.lastPrediction && CropWise.state.lastPrediction.top_crop
          ? CropWise.state.lastPrediction.top_crop.crop : null;
        if (crop) this.load(crop, input.value || null);
      });
    }
  },

  async loadForTopCrop(data) {
    const top = data && data.top_crop;
    if (!top) return;
    const input = document.getElementById("calendarSowingDate");
    await this.load(top.crop, input ? input.value || null : null);
  },

  async load(cropId, sowingDate) {
    try {
      const url = `/api/crop-calendar/${encodeURIComponent(cropId)}` + (sowingDate ? `?sowing_date=${encodeURIComponent(sowingDate)}` : "");
      const res = await fetch(url);
      const calendar = await res.json();
      if (!res.ok) return;
      this.lastCalendar = calendar;
      this.render(calendar);
    } catch (e) { /* calendar is a nice-to-have; fail silently */ }
  },

  render(cal) {
    const el = document.getElementById("cropPlanCalendar");
    let html = "";

    const dur = cal.duration || {};
    if (dur.status === "VERIFIED_SOURCE") {
      html += `<p><strong>Duration:</strong> ${dur.min_days}–${dur.max_days} days</p>`;
    } else {
      html += `<p class="small-muted">Duration: unavailable (no verified source) — harvest window cannot be estimated.</p>`;
    }

    if (cal.harvest_window) {
      html += `<p><strong>Estimated harvest window:</strong> ${cal.harvest_window.start} – ${cal.harvest_window.end}</p>`;
    } else if (dur.status === "VERIFIED_SOURCE") {
      html += `<p class="small-muted">Enter a sowing date above to see an estimated harvest window.</p>`;
    }

    if (Array.isArray(cal.day_anchored_events) && cal.day_anchored_events.length > 0) {
      html += `<p style="margin-top:10px;"><strong>Key sourced timing:</strong></p>`;
      html += cal.day_anchored_events.map(e => `
        <div class="profile-param">
          <div>
            <div class="profile-param-name">${e.label}</div>
            <div class="profile-param-source">${e.day_offset_min}-${e.day_offset_max} days after sowing${e.notes ? " — " + e.notes : ""}</div>
          </div>
          <div class="profile-param-value">${e.date_min ? `${e.date_min} – ${e.date_max}` : ""}</div>
        </div>
      `).join("");
    }

    if (Array.isArray(cal.stage_notes) && cal.stage_notes.length > 0) {
      html += `<p style="margin-top:10px;"><strong>Other verified stage notes (no specific day count in source):</strong></p>`;
      html += cal.stage_notes.map(s => `
        <p class="small-muted">• ${s.label}: ${s.stage_description}</p>
      `).join("");
    }

    el.innerHTML = html || `<p class="small-muted">No calendar information available for this crop.</p>`;
  },
};

document.addEventListener("DOMContentLoaded", () => CropWiseCalendar.init());
window.CropWiseCalendar = CropWiseCalendar;
