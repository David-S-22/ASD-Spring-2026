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

function activateTab(name) {
  document.querySelectorAll(".tabs button").forEach(function (btn) {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === name);
  });
  document.querySelectorAll(".tab-page").forEach(function (page) {
    page.classList.toggle("active", page.getAttribute("data-tab-page") === name);
  });
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
  if (location.hash.indexOf("#chat?") === 0) {
    var chat = document.querySelector(".ask-tally");
    if (chat) {
      chat.scrollIntoView({ block: "start" });
    }
  }
})();
