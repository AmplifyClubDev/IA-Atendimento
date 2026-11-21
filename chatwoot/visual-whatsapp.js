/* Mostra a nota "🔗 Botão enviado pelo WhatsApp: *Rótulo* → link" como o lead vê:
   balão verde com o texto e um botão de link embaixo. Só aparência; não muda a mensagem. */
(function () {
  function ampCta() {
    document.querySelectorAll('[data-bubble-name] .prose').forEach(function (prose) {
      var bubble = prose.closest('[data-bubble-name]');
      if (!bubble || bubble.dataset.ampCta) return;
      var first = prose.querySelector('p');
      if (!first || first.textContent.indexOf('🔗 Botão enviado pelo WhatsApp:') !== 0) return;
      var link = first.querySelector('a');
      if (!link || !/^https:\/\//.test(link.href)) return;
      var label = (first.querySelector('em') || {}).textContent || 'Abrir';
      bubble.dataset.ampCta = '1';
      bubble.classList.add('amp-cta');
      first.classList.add('amp-cta-head');
      var button = document.createElement('a');
      button.className = 'amp-cta-btn';
      button.href = link.href;
      button.target = '_blank';
      button.rel = 'noopener noreferrer';
      button.textContent = '↗ ' + label;
      prose.after(button);
    });
  }
  var scheduled = false;
  new MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () { scheduled = false; ampCta(); });
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', ampCta);
})();
