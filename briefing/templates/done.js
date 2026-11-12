/* "Mark complete" for meeting-prep briefs.
 *
 * Served by briefing.actions at /api/done.js. The brief's Action items table
 * carries data-actions, each row data-id / data-owner, and a hidden
 * data-done-bar under it. Progressive enhancement: if /api/done does not
 * answer (the published Artifact copy, a file:// copy) nothing is shown.
 *
 * Text is only ever set with textContent. No inline handlers, no eval: this
 * file stays valid under a script-src 'self' policy.
 */
(function () {
  "use strict";

  var API = "/api/done";
  var table = document.querySelector("table[data-actions]");
  var bar = document.querySelector("[data-done-bar]");
  if (!table || !bar) return;
  var button = bar.querySelector("button");
  var message = bar.querySelector("[data-done-msg]");
  if (!button || !message) return;

  function rows() {
    return Array.prototype.slice.call(table.querySelectorAll("tbody tr[data-id]"));
  }
  function itemText(row) {
    var cell = row.querySelector("td.item");
    return cell ? cell.textContent.replace(/\s+/g, " ").trim() : row.dataset.id;
  }
  function say(text, warn) {
    message.textContent = text;
    message.dataset.state = warn ? "warn" : "ok";
  }

  function call(method, url, body) {
    var headers = { Accept: "application/json" };
    var opts = { method: method, headers: headers, credentials: "same-origin" };
    if (method !== "GET") {
      headers["X-Briefing-Action"] = "1";
      headers["Content-Type"] = "application/json";
    }
    if (body) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || data.ok === false) {
          throw new Error(data.error || "request failed (" + res.status + ")");
        }
        return data;
      });
    });
  }

  function cardNote(k) {
    if (!k) return null;
    var card = "Card #" + k.card;
    switch (k.state) {
      case "moved": return { text: card + " moved to Done." };
      case "restored": return { text: card + " put back in " + k.status + "." };
      case "unconfigured": return { text: card + " not updated: kanban is not connected.", warn: true };
      case "not_found": return { text: card + " is not on the board.", warn: true };
      case "failed": return { text: card + " not updated: " + k.error, warn: true };
      case "restore_failed": return { text: card + " could not be put back: " + k.error, warn: true };
      default: return null; // already_done, or no card: nothing to add
    }
  }

  function pickCell(row) { return row.querySelector("td.pick"); }

  function selectedRows() {
    return rows().filter(function (row) {
      var box = row.querySelector("td.pick input[type=checkbox]");
      return box && box.checked;
    });
  }
  function refreshButton() {
    var n = selectedRows().length;
    button.disabled = n === 0;
    button.textContent = n ? "Mark complete (" + n + ")" : "Mark complete";
  }

  function makeCheckbox(row) {
    var box = document.createElement("input");
    box.type = "checkbox";
    box.setAttribute("aria-label", "Select: " + itemText(row));
    box.addEventListener("change", refreshButton);
    return box;
  }
  function setOpen(row) {
    row.classList.remove("is-done");
    var cell = pickCell(row);
    if (!cell) return;
    cell.textContent = "";
    cell.appendChild(makeCheckbox(row));
  }
  function setDone(row) {
    row.classList.add("is-done");
    var cell = pickCell(row);
    if (!cell) return;
    cell.textContent = "";
    var undo = document.createElement("button");
    undo.type = "button";
    undo.className = "undo";
    undo.textContent = "Undo";
    undo.setAttribute("aria-label", "Undo complete: " + itemText(row));
    undo.addEventListener("click", function () { undoRow(row, undo); });
    cell.appendChild(undo);
  }

  function undoRow(row, undo) {
    undo.disabled = true;
    call("DELETE", API + "/" + encodeURIComponent(row.dataset.id))
      .then(function (res) {
        setOpen(row);
        refreshButton();
        var note = cardNote(res.kanban);
        say(note ? note.text : "Back on the list.", note && note.warn);
      })
      .catch(function (err) {
        undo.disabled = false;
        say("Could not undo: " + err.message, true);
      });
  }

  function completeSelected() {
    var chosen = selectedRows();
    if (!chosen.length) return;
    button.disabled = true;
    say("Saving…", false);
    var saved = 0, notes = [], problems = [];
    chosen.reduce(function (chain, row) {
      return chain.then(function () {
        return call("POST", API, {
          id: row.dataset.id,
          text: itemText(row),
          owner: row.dataset.owner || "",
          brief: location.pathname
        }).then(function (res) {
          saved++;
          setDone(row);
          var note = cardNote(res.kanban);
          if (note) (note.warn ? problems : notes).push(note.text);
        }).catch(function (err) {
          problems.push("“" + itemText(row) + "” not saved: " + err.message);
        });
      });
    }, Promise.resolve()).then(function () {
      refreshButton();
      var head = saved ? "Marked " + saved + " complete." : "Nothing saved.";
      say([head].concat(notes, problems).join(" "), problems.length > 0);
    });
  }

  call("GET", API).then(function (data) {
    var done = data.items || {};
    table.classList.add("can-complete");
    bar.hidden = false;
    rows().forEach(function (row) {
      if (Object.prototype.hasOwnProperty.call(done, row.dataset.id)) setDone(row);
      else setOpen(row);
    });
    button.addEventListener("click", completeSelected);
    refreshButton();
  }).catch(function () { /* no service here: leave the page as a plain table */ });
})();
