function showToast(message) {
    const toastBody = document.getElementById('toastBody');
    toastBody.innerText = message;
    const toast = new bootstrap.Toast(document.getElementById('liveToast'));
    toast.show();
}

// Automatically inject CSRF token into all fetch requests
(function() {
    const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
    if (!csrfTokenMeta) return;
    const csrfToken = csrfTokenMeta.getAttribute('content');
    
    const originalFetch = window.fetch;
    window.fetch = function(resource, config) {
        config = config || {};
        const method = (config.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            config.headers = config.headers || {};
            if (config.headers instanceof Headers) {
                config.headers.set('X-CSRFToken', csrfToken);
            } else {
                config.headers['X-CSRFToken'] = csrfToken;
            }
        }
        return originalFetch(resource, config);
    };
})();
