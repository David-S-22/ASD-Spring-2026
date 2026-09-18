// Anomaly-alert toast handling for the Tally shell.
//
// This lives on the main page (not inside a swapped-in tab), so anomaly toasts
// keep working even after the user switches tabs. A tab (e.g. the transactions
// page) starts a check by calling window.watchTransactionForAnomaly(id).

// Poll the anomalies backend for the review result of a specific transaction
// (its id is the key). htmx swaps the returned toast fragment into #alert on a
// 200; a 204 (no anomaly, or still being reviewed) leaves #alert untouched.
window.watchTransactionForAnomaly = function (key) {
    if (key == null || typeof htmx === 'undefined') return;
    htmx.ajax(
        'GET',
        '/anomalies-backend/anomaly-alert?key=' + encodeURIComponent(key),
        { target: '#alert', swap: 'innerHTML' }
    );
};

window.dismissToast = function (toast) {
    if (!toast || toast.classList.contains('toast--hide')) return;
    toast.classList.add('toast--hide');
    toast.addEventListener('transitionend', function () {
        toast.remove();
    }, { once: true });
};

if (!window.__sharedToastInit) {
    window.__sharedToastInit = true;

    // When a transaction is created (the transactions backend fires an
    // `HX-Trigger: transaction-created` response header with the new id), start
    // polling the anomalies backend so any resulting alert surfaces as a toast.
    document.body.addEventListener('transaction-created', function (evt) {
        const key = evt.detail && (evt.detail.value != null ? evt.detail.value : evt.detail);
        window.watchTransactionForAnomaly(key);
    });

    // Auto-dismiss a toast 30s after it is swapped into #alert.
    document.body.addEventListener('htmx:afterSwap', function (evt) {
        const target = evt.detail && evt.detail.target;
        if (!target || target.id !== 'alert') return;

        const toast = target.querySelector('.toast');
        if (!toast) return;

        setTimeout(function () {
            window.dismissToast(toast);
        }, 30000);
    });

    // Dismiss a toast when its close button is clicked.
    document.body.addEventListener('click', function (evt) {
        const closeBtn = evt.target.closest('.toast-close');
        if (!closeBtn) return;
        window.dismissToast(closeBtn.closest('.toast'));
    });
}
