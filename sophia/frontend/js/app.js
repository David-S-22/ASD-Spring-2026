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

document.addEventListener("htmx:afterRequest", function (evt) {
  var config = evt.detail.requestConfig || {};
  var verb = (config.verb || "get").toLowerCase();
  if (verb === "get" || !evt.detail.successful) {
    return;
  }
  showToast(verb === "delete" ? "Done — removed." : "Done — change saved.");
});

document.body.addEventListener("click", function (evt) {
  var tab = evt.target.closest(".tabs button");
  if (tab) {
    document.querySelectorAll(".tabs button").forEach(function (btn) {
      btn.classList.remove("active");
    });
    tab.classList.add("active");
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
