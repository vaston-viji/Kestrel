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

/* ── Wire up forms ─────────────────────────────────────── */
document.querySelectorAll('.subscribe-form').forEach(f =>
  f.addEventListener('submit', handleSubscribe)
);
const unsubForm = document.querySelector('.unsubscribe-form');
if (unsubForm) unsubForm.addEventListener('submit', handleUnsubscribe);
