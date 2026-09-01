// Everything below binds to Bills' own root rather than to document or
// document.body, and that is load-bearing rather than tidiness.
//
// The shared shell (:3000) swaps this whole document into its #content, and
// htmx re-executes scripts in swapped content -- so this file runs there,
// against the shell's htmx instance, which every other feature's tab shares.
// Anything set globally here would silently change behaviour for Transactions,
// Anomalies and Savings, and nothing ever sets it back. Scoping to #bills-root
// also means a second visit to the Bills tab rebinds a fresh subtree instead of
// stacking a duplicate listener on a document that is never replaced.
var billsRoot = document.getElementById("bills-root");
if (!billsRoot) {
  throw new Error("#bills-root is missing -- Bills' handlers cannot bind.");
}

// Bills' write routes answer invalid input with a 422 and an HTML error
// fragment, so error responses have to swap into the target instead of being
// discarded. htmx's default drops 4xx/5xx bodies and raises htmx:responseError.
//
// This used to be done with htmx.config.responseHandling, which is global: in
// the shell that one assignment would make every feature swap error bodies and
// stop firing htmx:responseError. The same result is achieved per-event here,
// on Bills' subtree only. 204 and 2xx/3xx are left to htmx's defaults, which
// already match what the old config asked for -- 4xx/5xx was the only
// difference, so behaviour standalone is unchanged.
billsRoot.addEventListener("htmx:beforeSwap", function (evt) {
  var xhr = evt.detail && evt.detail.xhr;
  if (xhr && xhr.status >= 400) {
    evt.detail.shouldSwap = true;
    evt.detail.isError = false;
  }
});

function showModal(onConfirm) {
  // The confirm dialog must NOT live in #modal-root: the add/edit/cancel/
  // payment/dispute forms render there, and replacing them detaches the
  // form so htmx drops the request it is asking to confirm.
  var root = document.getElementById("confirm-root");
  if (!root) {
    root = document.createElement("div");
    root.id = "confirm-root";
    // Into Bills' root, not document.body: in the shell, body is outside the
    // #content the shell replaces on a tab switch, so a dialog appended there
    // would outlive Bills and sit over whichever feature came next.
    billsRoot.appendChild(root);
  }
  root.innerHTML =
    '<div class="modal-backdrop"><div class="modal">' +
    "<p>Confirm this change</p>" +
    '<button type="button" class="confirm">Confirm</button> ' +
    '<button type="button" class="cancel">Cancel</button>' +
    "</div></div>";
  root.querySelector(".confirm").addEventListener("click", function () {
    root.innerHTML = "";
    onConfirm();
  });
  root.querySelector(".cancel").addEventListener("click", function () {
    root.innerHTML = "";
  });
}

function showToast(text) {
  var root = document.getElementById("toast-root");
  root.innerHTML = '<div class="toast">' + text + "</div>";
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(function () {
    if (root.firstChild) {
      root.innerHTML = "";
    }
  }, 2500);
}

// The four inner tabs, in markup order. Also the whitelist for the fragment:
// only these names are ever written to or restored from location.hash.
var TAB_NAMES = ["bills", "calendar", "timeline", "disputes"];

// Tab memory is namespaced -- "#bills:disputes", not "#disputes". In the shell
// this fragment lives on the shell's own URL, which is shared ground: if the
// shell later records its active feature there, a bare "#bills" would be
// ambiguous between "the shell's Bills tab" and "Bills' own bills tab". The
// prefix also keeps these values clear of the published deep links, which are
// "#bills?confirm=<id>" and "#chat?..." and are contract, not tab state.
var TAB_HASH_PREFIX = "#bills:";

function activateTab(name) {
  document.querySelectorAll(".tabs button").forEach(function (btn) {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === name);
  });
  document.querySelectorAll(".tab-page").forEach(function (page) {
    page.classList.toggle("active", page.getAttribute("data-tab-page") === name);
  });
  rememberTab(name);
}

// Record the open tab in the fragment so a reload comes back to it.
//
// replaceState rather than assigning location.hash: assigning pushes a history
// entry per tab click, so Back would walk the tabs instead of leaving the page.
// replaceState also fires no hashchange, so this cannot re-enter the restore
// branch in the initialiser below.
//
// Inside the shell this writes to the shell's own URL (:3000/#calendar), which
// is the only place a reload can survive -- the shell swaps features into
// #content without touching the URL, so Bills has nowhere else to put it. The
// shell has no hashchange listener and no other feature reads the fragment, so
// the value is inert until Bills is opened again. A reload at :3000 still lands
// on the shell's own Home tab, because Bills is not mounted at that point;
// clicking Bills then restores the remembered tab. Making the reload itself
// return to Bills needs the shell to record its active tab, which is Aiden's.
function rememberTab(name) {
  if (TAB_NAMES.indexOf(name) === -1) {
    return;
  }
  // Leave a deep link alone while its own tab is the one being activated:
  // "#bills?confirm=12" already says bills, and overwriting it would drop the
  // target row on a reload.
  if (location.hash.indexOf("#" + name + "?") === 0) {
    return;
  }
  var next = TAB_HASH_PREFIX + name;
  if (location.hash === next) {
    return;
  }
  history.replaceState(null, "", next);
}

billsRoot.addEventListener("htmx:confirm", function (evt) {
  var verb = (evt.detail.verb || "get").toLowerCase();
  if (verb === "get") {
    return;
  }
  evt.preventDefault();
  showModal(function () {
    evt.detail.issueRequest(true);
  });
});

billsRoot.addEventListener("htmx:afterRequest", function (evt) {
  // A modal form used to be wiped as a side effect of the confirm dialog
  // replacing it; now the dialog lives elsewhere, close the form once its
  // request succeeds.
  var modal = document.getElementById("modal-root");
  if (evt.detail.successful && modal && evt.detail.elt && modal.contains(evt.detail.elt)) {
    modal.innerHTML = "";
  }
});

billsRoot.addEventListener("toast", function (evt) {
  var detail = evt.detail || {};
  var text = typeof detail.value === "string" ? detail.value : detail;
  showToast(typeof text === "string" ? text : "Done.");
});

billsRoot.addEventListener("switchTab", function (evt) {
  var detail = evt.detail || {};
  var name = typeof detail.value === "string" ? detail.value : detail;
  if (typeof name === "string") {
    activateTab(name);
  }
});

// Client-side search over the rendered rows. No route, no ?q=, no request --
// the whole table is already in the DOM, and filtering it is the honest shape
// for twelve rows. Server-side search is the R1 shape, for when it is not.
//
// Matched against Name, Every, Paid by and Status. Deliberately not the actions
// cell, whose every row reads "Edit Cancel Dispute Record payment" and would
// therefore match any query that is a substring of those words.
var SEARCHABLE_CELLS = [0, 2, 4, 5];

function rowMatches(row, needle) {
  for (var i = 0; i < SEARCHABLE_CELLS.length; i++) {
    var cell = row.cells[SEARCHABLE_CELLS[i]];
    if (cell && cell.textContent.toLowerCase().indexOf(needle) !== -1) {
      return true;
    }
  }
  return false;
}

function applyBillsFilter() {
  var input = document.getElementById("bills-search");
  var table = billsRoot.querySelector(".bills-table");
  if (!input || !table) {
    return;
  }
  var needle = input.value.trim().toLowerCase();
  var rows = table.querySelectorAll("tbody tr[data-bill-id]");
  var shown = 0;
  for (var i = 0; i < rows.length; i++) {
    var hit = !needle || rowMatches(rows[i], needle);
    rows[i].hidden = !hit;
    if (hit) {
      shown++;
    }
  }
  var empty = table.querySelector("tbody tr.no-match");
  if (empty) {
    empty.hidden = !(needle && shown === 0);
  }
}

// Bound on billsRoot rather than the input: the input survives table swaps, but
// binding through the root keeps every listener in this file on one subtree, so
// a second visit to the Bills tab rebinds a fresh subtree instead of stacking a
// duplicate on a document that is never replaced.
billsRoot.addEventListener("input", function (evt) {
  if (evt.target && evt.target.id === "bills-search") {
    applyBillsFilter();
  }
});

// Every write replaces #bills-table wholesale, which brings back rows the filter
// had hidden. Re-apply once the swap has settled.
billsRoot.addEventListener("htmx:afterSwap", function () {
  applyBillsFilter();
});

billsRoot.addEventListener("click", function (evt) {
  var tab = evt.target.closest(".tabs button");
  if (tab) {
    activateTab(tab.getAttribute("data-tab"));
    return;
  }

  var chip = evt.target.closest("[data-chip]");
  if (chip) {
    var input = document.querySelector('.chat-panel input[name="message"]');
    if (input) {
      input.value = chip.getAttribute("data-chip");
      if (input.form && input.form.requestSubmit) {
        input.form.requestSubmit();
      }
    }
    return;
  }

  var rewrite = evt.target.closest('[data-action="rewrite"]');
  if (rewrite) {
    var panel = rewrite.closest(".dispute-panel");
    var feedback = panel && panel.querySelector(".rewrite-feedback");
    if (feedback) {
      feedback.hidden = !feedback.hidden;
    }
    return;
  }

  var copyNote = evt.target.closest('[data-action="copy-note"]');
  if (copyNote) {
    var panelForCopy = copyNote.closest(".dispute-panel");
    var letter = panelForCopy && panelForCopy.querySelector(".letter");
    if (letter && navigator.clipboard) {
      navigator.clipboard.writeText(letter.value).then(function () {
        showToast(copyNote.getAttribute("data-toast") || "Copied");
      });
    }
    return;
  }

  var setAside = evt.target.closest('[data-action="set-aside"]');
  if (setAside) {
    showToast(setAside.getAttribute("data-toast") || "Done — change saved.");
    return;
  }

  var dismissPreview = evt.target.closest('[data-action="dismiss-preview"]');
  if (dismissPreview) {
    var card = dismissPreview.closest(".preview-card");
    if (card) {
      card.remove();
    }
    return;
  }

  var dismissModal = evt.target.closest('[data-action="dismiss-modal"]');
  if (dismissModal) {
    document.getElementById("modal-root").innerHTML = "";
  }
});

(function () {
  if (location.pathname.indexOf("/handoff/") === 0) {
    htmx.ajax("GET", "/bills-backend/ui" + location.pathname + location.search, { target: "#modal-root", swap: "innerHTML" });
    history.replaceState(null, "", "/");
    return;
  }
  if (location.hash.indexOf("#bills?confirm=") === 0) {
    var billId = parseInt(location.hash.split("confirm=")[1], 10);
    activateTab("bills");
    if (isNaN(billId)) {
      return;
    }
    var scrollToBill = function () {
      var row = document.querySelector('#bills-table tr[data-bill-id="' + billId + '"]');
      if (row) {
        window.clearTimeout(stopLooking);
        billsRoot.removeEventListener("htmx:afterSettle", scrollToBill);
        row.scrollIntoView({ block: "center" });
      }
    };
    var stopLooking = window.setTimeout(function () {
      billsRoot.removeEventListener("htmx:afterSettle", scrollToBill);
    }, 10000);
    billsRoot.addEventListener("htmx:afterSettle", scrollToBill);
    return;
  }
  // "#bills:<tab>" is the tab remembered from a previous visit. Checked after
  // the deep links above, which carry a query and are the more specific match.
  if (location.hash.indexOf(TAB_HASH_PREFIX) === 0) {
    var remembered = location.hash.slice(TAB_HASH_PREFIX.length);
    if (TAB_NAMES.indexOf(remembered) !== -1) {
      activateTab(remembered);
      return;
    }
  }
  if (location.hash.indexOf("#chat?") === 0) {
    var chat = document.querySelector(".ask-tally");
    if (chat) {
      chat.scrollIntoView({ block: "start" });
    }
  }
})();
