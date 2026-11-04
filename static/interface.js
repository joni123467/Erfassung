/* Progressive Web UI helpers. Forms and overview links work without JavaScript. */
(function () {
    'use strict';

    const navigationToggles = Array.from(document.querySelectorAll('[data-navigation-toggle]'));
    let lastNavigationToggle = navigationToggles[0] || null;

    function setNavigation(open, restoreFocus) {
        document.body.classList.toggle('navigation-open', open);
        navigationToggles.forEach(function (button) {
            button.setAttribute('aria-expanded', String(open));
        });
        if (!open && restoreFocus && lastNavigationToggle) lastNavigationToggle.focus();
    }

    function disclosureTarget(button) {
        const id = button.getAttribute('data-disclose');
        return id ? document.getElementById(id) : null;
    }

    function updateDisclosureButtons() {
        document.querySelectorAll('[data-disclose]').forEach(function (button) {
            const target = disclosureTarget(button);
            if (target instanceof HTMLDetailsElement) {
                button.setAttribute('aria-expanded', String(target.open));
            }
        });
    }

    function reveal(target, focus) {
        if (!target) return;
        let parent = target instanceof HTMLDetailsElement ? target : target.closest('details');
        while (parent) {
            parent.open = true;
            parent = parent.parentElement ? parent.parentElement.closest('details') : null;
        }
        updateDisclosureButtons();
        if (focus) {
            const field = target.querySelector('input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), summary');
            if (field) field.focus({ preventScroll: true });
        }
    }

    function revealHash() {
        if (!location.hash) return;
        let id;
        try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
        const target = document.getElementById(id);
        if (!target) return;
        reveal(target, false);
        requestAnimationFrame(function () { target.scrollIntoView({ block: 'start' }); });
    }

    document.addEventListener('click', function (event) {
        if (!(event.target instanceof Element)) return;
        const toggle = event.target.closest('[data-navigation-toggle]');
        if (toggle) {
            lastNavigationToggle = toggle;
            setNavigation(!document.body.classList.contains('navigation-open'), false);
            return;
        }
        if (document.body.classList.contains('navigation-open')) {
            const header = lastNavigationToggle ? lastNavigationToggle.closest('header') : null;
            const navigationId = lastNavigationToggle ? lastNavigationToggle.getAttribute('aria-controls') : null;
            const navigation = navigationId ? document.getElementById(navigationId) : null;
            if (!header || !header.contains(event.target) || (navigation && navigation.contains(event.target) && event.target.closest('a[href]'))) {
                setNavigation(false, false);
            }
        }
        const disclose = event.target.closest('[data-disclose]');
        if (disclose) {
            const target = disclosureTarget(disclose);
            if (!target) return;
            reveal(target, true);
            // Native anchor navigation preserves the URL and browser history.
            if (disclose.tagName !== 'A') target.scrollIntoView({ block: 'start' });
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && document.body.classList.contains('navigation-open')) {
            setNavigation(false, true);
        }
    });
    document.addEventListener('toggle', updateDisclosureButtons, true);
    document.addEventListener('invalid', function (event) {
        if (event.target instanceof Element) reveal(event.target, false);
    }, true);
    window.addEventListener('hashchange', revealHash);
    const desktop = window.matchMedia('(min-width: 1024px)');
    const onDesktopChange = function () { if (desktop.matches) setNavigation(false, false); };
    if (desktop.addEventListener) desktop.addEventListener('change', onDesktopChange);
    else if (desktop.addListener) desktop.addListener(onDesktopChange);

    updateDisclosureButtons();
    revealHash();
})();
