// ====================================================
// ANIMATIONS.JS — À charger avant </body> dans base.html
// Reveal au scroll, loader, bouton retour en haut
// ====================================================

document.addEventListener('DOMContentLoaded', function () {

    // ---------- Reveal au scroll ----------
    const revealElements = document.querySelectorAll('.reveal');

    if ('IntersectionObserver' in window && revealElements.length) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });

        revealElements.forEach(el => observer.observe(el));
    } else {
        // Fallback : navigateurs anciens
        revealElements.forEach(el => el.classList.add('is-visible'));
    }

    // ---------- Loader de page ----------
    const loader = document.querySelector('.page-loader');
    if (loader) {
        window.addEventListener('load', () => {
            setTimeout(() => loader.classList.add('hidden'), 200);
        });
    }

    // ---------- Bouton retour en haut ----------
    const backToTop = document.querySelector('.back-to-top');
    if (backToTop) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 400) {
                backToTop.classList.add('visible');
            } else {
                backToTop.classList.remove('visible');
            }
        });

        backToTop.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // ---------- Menu hamburger mobile ----------
    const hamburger = document.querySelector('.hamburger-icon');
    const mobileMenu = document.querySelector('.mobile-menu');

    if (hamburger && mobileMenu) {
        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            mobileMenu.classList.toggle('open');
        });

        // Fermer le menu au clic sur un lien
        mobileMenu.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                hamburger.classList.remove('active');
                mobileMenu.classList.remove('open');
            });
        });
    }

    // ---------- Compteurs animés (statistiques accueil) ----------
    const counters = document.querySelectorAll('.stat-number[data-count]');
    if (counters.length && 'IntersectionObserver' in window) {
        const counterObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    animateCounter(entry.target);
                    counterObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.5 });

        counters.forEach(counter => counterObserver.observe(counter));
    }

    function animateCounter(el) {
        const target = parseInt(el.getAttribute('data-count'), 10);
        const duration = 1500;
        const start = performance.now();

        function step(now) {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.floor(eased * target);
            if (progress < 1) requestAnimationFrame(step);
            else el.textContent = target;
        }
        requestAnimationFrame(step);
    }

    // ---------- Lightbox (zoom image au clic) ----------
    let lightbox = document.querySelector('.lightbox-overlay');
    if (!lightbox) {
        lightbox = document.createElement('div');
        lightbox.className = 'lightbox-overlay';
        lightbox.innerHTML = '<button class="lightbox-close" aria-label="Fermer">&times;</button><img src="" alt="">';
        document.body.appendChild(lightbox);
    }
    const lightboxImg = lightbox.querySelector('img');
    const lightboxClose = lightbox.querySelector('.lightbox-close');

    function openLightbox(src, alt) {
        lightboxImg.src = src;
        lightboxImg.alt = alt || '';
        lightbox.classList.add('open');
        document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
        lightbox.classList.remove('open');
        document.body.style.overflow = '';
    }

    document.addEventListener('click', function (e) {
        const target = e.target.closest('.lightbox-img');
        if (target && target.tagName === 'IMG') {
            openLightbox(target.src, target.alt);
        }
    });

    lightboxClose.addEventListener('click', closeLightbox);
    lightbox.addEventListener('click', function (e) {
        if (e.target === lightbox) closeLightbox();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeLightbox();
    });

});
