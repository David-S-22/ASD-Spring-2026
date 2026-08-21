htmx.config.responseHandling = [
  { code: "204", swap: false },
  { code: "[23]..", swap: true },
  { code: "422", swap: true, error: false },
  { code: "[45]..", swap: true, error: false },
];

function showModal(onConfirm) {
  var root = document.getElementById("modal-root");
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
  window.setTimeout(function () {
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

document.addEventListener("htmx:confirm", function (evt) {
  var verb = (evt.detail.verb || "get").toLowerCase();
  if (verb === "get") {
    return;
  }
  evt.preventDefault();
  showModal(function () {
    evt.detail.issueRequest(true);
  });
});

document.body.addEventListener("toast", function (evt) {
  var detail = evt.detail || {};
  var text = typeof detail.value === "string" ? detail.value : detail;
  showToast(typeof text === "string" ? text : "Done.");
});

document.body.addEventListener("switchTab", function (evt) {
  var detail = evt.detail || {};
  var name = typeof detail.value === "string" ? detail.value : detail;
  if (typeof name === "string") {
    activateTab(name);
  }
});

document.body.addEventListener("click", function (evt) {
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
