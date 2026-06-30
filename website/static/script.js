/* Kestrel website — form handling + scroll effects */
'use strict';

/* ── Nav scroll effect ─────────────────────────────────── */
const nav = document.querySelector('.site-nav');
if (nav) {
  const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 8);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

/* ── Scroll reveal ─────────────────────────────────────── */
const revealObs = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('visible');
      revealObs.unobserve(e.target);
    }
  });
}, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.reveal').forEach(el => revealObs.observe(el));

/* ── Subscription form handler ─────────────────────────── */
async function handleSubscribe(e) {
  e.preventDefault();
  const form   = e.currentTarget;
  const status = form.querySelector('.form-status');
  const btn    = form.querySelector('.btn-primary');
  const name   = (form.querySelector('[name="name"]')?.value || '').trim();
  const email  = (form.querySelector('[name="email"]')?.value || '').trim();

  if (!email) return;

  btn.disabled    = true;
  btn.textContent = 'Subscribing…';
  if (status) { status.className = 'form-status'; status.textContent = ''; }

  try {
    const res  = await fetch('/api/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email }),
    });
    const data = await res.json();
    if (status) {
      status.textContent = data.message;
      status.className   = 'form-status ' + (res.ok ? 'success' : 'error');
    }
    if (res.ok) form.reset();
  } catch {
    if (status) {
      status.textContent = 'Connection error — please try again.';
      status.className   = 'form-status error';
    }
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Get the brief';
  }
}

/* ── Unsubscribe form handler ──────────────────────────── */
async function handleUnsubscribe(e) {
  e.preventDefault();
  const form   = e.currentTarget;
  const status = form.querySelector('.form-status');
  const btn    = form.querySelector('.btn-danger');
  const email  = (form.querySelector('[name="email"]')?.value || '').trim();

  if (!email) return;

  btn.disabled    = true;
  btn.textContent = 'Processing…';
  if (status) { status.className = 'form-status'; status.textContent = ''; }

  try {
    const res  = await fetch('/api/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();

    if (res.ok) {
      const card = document.querySelector('.unsub-card-body');
      const done = document.querySelector('.unsub-done');
      if (card) card.style.display = 'none';
      if (done) done.style.display = 'block';
    } else {
      if (status) {
        status.textContent = data.message || 'Email not found.';
        status.className   = 'form-status error';
      }
    }
  } catch {
    if (status) {
      status.textContent = 'Connection error — please try again.';
      status.className   = 'form-status error';
    }
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Confirm unsubscribe';
  }
}

/* ── Pre-fill email on unsubscribe page ────────────────── */
const params     = new URLSearchParams(window.location.search);
const emailParam = params.get('email');
if (emailParam) {
  const emailInput = document.querySelector('#unsub-email');
  if (emailInput) emailInput.value = decodeURIComponent(emailParam);
}

/* ── Dynamic brief date ────────────────────────────────── */
(function () {
  const el = document.getElementById('brief-doc-date');
  if (!el) return;
  const DAYS   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const now = new Date();
  el.textContent = `${DAYS[now.getDay()]} ${now.getDate()} ${MONTHS[now.getMonth()]} ${now.getFullYear()}`;
})();

/* ── Contact modal ─────────────────────────────────────── */
(function () {
  const overlay  = document.getElementById('contact-modal');
  // Support any number of trigger buttons via data attribute

  const closeBtn = document.getElementById('close-contact-modal');
  const doneClose = document.getElementById('contact-done-close');
  const form     = document.getElementById('contact-form');
  const doneEl   = document.getElementById('contact-done');
  const statusEl = document.getElementById('contact-status');

  if (!overlay) return;

  let _challengeAnswer = 0;
  let _lastFocus = null;

  function setupChallenge() {
    const a = Math.floor(Math.random() * 9) + 1;
    const b = Math.floor(Math.random() * 9) + 1;
    _challengeAnswer = a + b;
    document.getElementById('challenge-question').textContent = `What is ${a} + ${b}?`;
    const input = document.getElementById('cf-challenge');
    if (input) input.value = '';
  }

  function openModal() {
    _lastFocus = document.activeElement;
    setupChallenge();
    form.reset();
    form.style.display = '';
    if (doneEl) doneEl.hidden = true;
    if (statusEl) { statusEl.className = 'form-status'; statusEl.textContent = ''; }
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    // Focus first field after transition
    setTimeout(() => {
      const first = overlay.querySelector('input:not([tabindex="-1"]):not(.contact-honeypot)');
      if (first) first.focus();
    }, 60);
  }

  function closeModal() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    if (_lastFocus) _lastFocus.focus();
  }

  // Trap focus within modal
  overlay.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeModal(); return; }
    if (e.key !== 'Tab') return;
    const focusable = Array.from(overlay.querySelectorAll(
      'button:not([disabled]), input:not([tabindex="-1"]):not(.contact-honeypot), textarea, select, [tabindex]:not([tabindex="-1"])'
    )).filter(el => !el.closest('[hidden]'));
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey ? document.activeElement === first : document.activeElement === last) {
      e.preventDefault();
      (e.shiftKey ? last : first).focus();
    }
  });

  // Close on overlay background click (not on card)
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeModal();
  });

  document.querySelectorAll('[data-open-contact-modal]').forEach(btn =>
    btn.addEventListener('click', openModal)
  );
  if (closeBtn)  closeBtn.addEventListener('click', closeModal);
  if (doneClose) doneClose.addEventListener('click', closeModal);

  /* ── Contact form submission ─────────────────────────── */
  if (form) form.addEventListener('submit', async function (e) {
    e.preventDefault();

    const btn    = form.querySelector('.contact-submit');
    const name   = form.querySelector('[name="name"]').value.trim();
    const company = form.querySelector('[name="company"]').value.trim();
    const email  = form.querySelector('[name="email"]').value.trim();
    const message = form.querySelector('[name="message"]').value.trim();
    const gotcha  = form.querySelector('[name="_gotcha"]').value;
    const challenge = parseInt(form.querySelector('[name="challenge"]').value, 10);

    // Honeypot — bail silently if filled (bot)
    if (gotcha) { closeModal(); return; }

    // Math challenge client-side check
    if (isNaN(challenge) || challenge !== _challengeAnswer) {
      statusEl.textContent = 'Incorrect answer to the maths question — please try again.';
      statusEl.className = 'form-status error';
      document.getElementById('cf-challenge').focus();
      return;
    }

    if (!name || !email || !message) {
      statusEl.textContent = 'Please fill in all required fields.';
      statusEl.className = 'form-status error';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending…';
    if (statusEl) { statusEl.className = 'form-status'; statusEl.textContent = ''; }

    try {
      const res  = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, company, email, message }),
      });
      const data = await res.json();
      if (res.ok) {
        form.style.display = 'none';
        if (doneEl) doneEl.hidden = false;
        if (doneClose) setTimeout(() => doneClose.focus(), 50);
      } else {
        statusEl.textContent = data.detail || 'Something went wrong — please try again.';
        statusEl.className = 'form-status error';
      }
    } catch {
      statusEl.textContent = 'Connection error — please try again.';
      statusEl.className = 'form-status error';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Send message';
    }
  });
})();

/* ── Wire up forms ─────────────────────────────────────── */
document.querySelectorAll('.subscribe-form').forEach(f =>
  f.addEventListener('submit', handleSubscribe)
);
const unsubForm = document.querySelector('.unsubscribe-form');
if (unsubForm) unsubForm.addEventListener('submit', handleUnsubscribe);
