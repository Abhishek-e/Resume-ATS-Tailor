/*
 * Company prep dashboard - shared by the landing page section and the
 * standalone Preparation page. Both render the same markup ids, so one script
 * drives either; the two URLs it needs come off data attributes on the modal
 * rather than being templated in, which is what lets it live in a static file.
 *
 * Loaded with defer, so the DOM is parsed by the time this runs. It has no
 * dependency on the vendored Tabler bundle - the modal is a plain overlay,
 * because window.bootstrap does not exist yet at inline-script time.
 */
(function () {
    var grid = document.getElementById('prep-grid');
    if (!grid) { return; }   // page without the dashboard

    // --- Company filtering --------------------------------------------------
    var search = document.getElementById('prep-search');
    var empty = document.getElementById('prep-empty');
    var chips = document.querySelectorAll('.prep-chip');
    var cards = Array.prototype.slice.call(grid.querySelectorAll('.prep-card-col'));
    var sector = '';

    function applyFilters() {
        var term = (search.value || '').trim().toLowerCase();
        var shown = 0;
        cards.forEach(function (card) {
            var matchesSector = !sector || card.dataset.sector === sector;
            var matchesTerm = !term || card.dataset.search.indexOf(term) !== -1;
            var visible = matchesSector && matchesTerm;
            card.classList.toggle('d-none', !visible);
            if (visible) { shown++; }
        });
        empty.classList.toggle('d-none', shown !== 0);
    }

    if (search) { search.addEventListener('input', applyFilters); }
    chips.forEach(function (chip) {
        chip.addEventListener('click', function () {
            chips.forEach(function (c) { c.classList.remove('active'); });
            chip.classList.add('active');
            sector = chip.dataset.sector;
            applyFilters();
        });
    });

    // --- Scroll gate --------------------------------------------------------
    // Blur engages once the locked block is scrolled to, so the prompt lands
    // when the visitor reaches for the content.
    //
    // Measured off scroll rather than an IntersectionObserver: observer
    // callbacks go undelivered in a backgrounded or unpainted tab, and the
    // failure mode there is the block sitting open with no prompt on it. A
    // geometry check cannot fail that way - if the visitor can see the block,
    // the event that revealed it has already run this.
    var gate = document.getElementById('prep-gate');
    if (gate) {
        var lockGate = function () {
            if (gate.getBoundingClientRect().top >= window.innerHeight * 0.85) {
                return;
            }
            gate.classList.add('is-locked');
            window.removeEventListener('scroll', lockGate);
            window.removeEventListener('resize', lockGate);
        };
        window.addEventListener('scroll', lockGate, { passive: true });
        window.addEventListener('resize', lockGate);
        lockGate();   // already in view on load (short viewport, or a #prep link)
    }

    // --- Practice set modal -------------------------------------------------
    var modalEl = document.getElementById('prep-modal');
    if (!modalEl) { return; }

    var modalTitle = document.getElementById('prep-modal-title');
    var modalSub = document.getElementById('prep-modal-sub');
    var modalBody = document.getElementById('prep-modal-body');
    var registerUrl = modalEl.dataset.registerUrl || '/register';
    var setUrlBase = modalEl.dataset.setUrlBase || '/prep/';

    function openModal() { modalEl.style.display = 'flex'; }
    function closeModal() { modalEl.style.display = 'none'; }

    document.getElementById('prep-modal-close').addEventListener('click', closeModal);
    modalEl.addEventListener('click', function (e) { if (e.target === modalEl) closeModal(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && modalEl.style.display === 'flex') { closeModal(); }
    });

    function escapeHtml(value) {
        var div = document.createElement('div');
        div.textContent = value == null ? '' : value;
        return div.innerHTML;
    }

    function questionMarkup(question) {
        return '<div class="prep-q">' +
            '<span class="badge bg-primary-lt mb-2">' + escapeHtml(question.type) + '</span>' +
            '<p class="prep-q-prompt">' + escapeHtml(question.prompt) + '</p>' +
            '<details class="prep-q-answer"><summary>Show approach</summary>' +
            '<p class="mb-0 mt-2">' + escapeHtml(question.answer) + '</p></details>' +
            '</div>';
    }

    function lockedMarkup(data) {
        var rows = '';
        for (var i = 0; i < data.locked_count; i++) {
            rows += '<div class="prep-skeleton"><span class="prep-skeleton-tag"></span>' +
                '<span class="prep-skeleton-line"></span>' +
                '<span class="prep-skeleton-line short"></span></div>';
        }
        return '<div class="prep-gate is-locked mt-3">' +
            '<div class="prep-gate-content" aria-hidden="true">' + rows + '</div>' +
            '<div class="prep-gate-overlay"><div class="prep-gate-card">' +
            '<h3 class="mb-1">' + data.locked_count + ' more question' +
            (data.locked_count === 1 ? '' : 's') + ' in this set</h3>' +
            '<p class="text-secondary mb-3">Log in to read them with worked answers.</p>' +
            '<div class="btn-list justify-content-center">' +
            '<a href="' + escapeHtml(data.login_url) + '" class="btn btn-primary">Log in</a>' +
            '<a href="' + escapeHtml(registerUrl) + '" class="btn btn-ghost-secondary">Create account</a>' +
            '</div></div></div></div>';
    }

    function render(data) {
        modalSub.textContent = data.sector + ' · ' + data.question_count + ' questions';
        var html = '<div class="prep-modal-meta mb-3">' +
            '<span class="badge prep-diff prep-diff-' + escapeHtml(data.difficulty.toLowerCase()) +
            '">' + escapeHtml(data.difficulty) + '</span>' +
            '</div>' +
            '<p class="text-secondary">' + escapeHtml(data.blurb) + '</p>' +
            '<h4 class="mt-3">Interview rounds</h4><ol class="prep-rounds">' +
            data.rounds.map(function (r) { return '<li>' + escapeHtml(r) + '</li>'; }).join('') +
            '</ol><h4 class="mt-3">Practice questions</h4>' +
            data.questions.map(questionMarkup).join('');

        if (!data.unlocked && data.locked_count > 0) { html += lockedMarkup(data); }
        modalBody.innerHTML = html;
    }

    document.querySelectorAll('.prep-open').forEach(function (button) {
        button.addEventListener('click', function () {
            modalTitle.textContent = button.dataset.name;
            modalSub.textContent = '';
            modalBody.innerHTML = '<div class="text-center py-4"><div class="spinner"></div></div>';
            openModal();
            fetch(setUrlBase + encodeURIComponent(button.dataset.slug) + '/set')
                .then(function (r) { return r.json(); })
                .then(render)
                .catch(function () {
                    modalBody.innerHTML =
                        '<p class="text-danger mb-0">Could not load this practice set. Try again.</p>';
                });
        });
    });
})();
