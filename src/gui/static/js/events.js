/*
 * src/gui/static/js/events.js
 *
 * Desktop behavior-events panel.
 *
 * R6 / Week 3:
 * - Reads recent events from /api/events/recent
 * - Displays newest events first
 * - Refreshes every 10 seconds while TOOLS is visible
 * - Stops refreshing when TOOLS is hidden
 * - Shows an empty state when no events exist
 */

"use strict";

let _eventsRefreshTimer = null;

async function loadRecentEvents() {
  const status = document.getElementById("events-status");
  const table = document.getElementById("events-table");
  const tbody = document.getElementById("events-tbody");

  if (!status || !table || !tbody) return;

  try {
    const response = await fetch("/api/events/recent", {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const events = Array.isArray(data.events) ? data.events : [];

    tbody.innerHTML = "";

    if (events.length === 0) {
      table.style.display = "none";
      status.style.display = "block";
      status.textContent =
        "No behavior events yet. Draw zones first, then run a compress.";
      return;
    }

    status.style.display = "none";
    table.style.display = "table";

    events.forEach((event) => {
      const row = document.createElement("tr");

      const kind = document.createElement("td");
      kind.textContent = event.kind || "—";

      const camera = document.createElement("td");
      camera.textContent = event.camera_id || "—";

      const headline = document.createElement("td");
      headline.textContent =
        event.headline ||
        event.message ||
        event.kind ||
        "Behavior event";

      const wallTime = document.createElement("td");
      wallTime.textContent = event.wall_time || "—";

      row.appendChild(kind);
      row.appendChild(camera);
      row.appendChild(headline);
      row.appendChild(wallTime);

      tbody.appendChild(row);
    });
  } catch (error) {
    table.style.display = "none";
    status.style.display = "block";
    status.textContent = "Unable to load behavior events.";
    console.error("Failed to load recent events:", error);
  }
}

function startEventsRefresh() {
  stopEventsRefresh();

  loadRecentEvents();

  _eventsRefreshTimer = window.setInterval(() => {
    loadRecentEvents();
  }, 10000);
}

function stopEventsRefresh() {
  if (_eventsRefreshTimer !== null) {
    window.clearInterval(_eventsRefreshTimer);
    _eventsRefreshTimer = null;
  }
}
