// Copy buttons for install commands + version picker.
// No tracking, no dependencies. Unobtrusive: adds a Copy button to each .cmd block.

(() => {
  const cmdBlocks = document.querySelectorAll('figure.cmd');
  cmdBlocks.forEach((fig) => {
    const pre = fig.querySelector('pre');
    if (!pre) return;
    const code = pre.querySelector('code');
    if (!code) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Copy';
    btn.setAttribute('aria-label', 'Copy command');
    btn.style.marginBlockStart = '0.5rem';
    btn.style.padding = '0.35rem 0.9rem';
    btn.style.borderRadius = '8px';
    btn.style.border = '1px solid var(--border, #ddd)';
    btn.style.background = 'var(--surface, #fff)';
    btn.style.cursor = 'pointer';
    btn.style.font = 'inherit';
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.textContent.trim());
        btn.textContent = 'Copied';
        setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
      } catch {
        btn.textContent = 'Select & copy';
      }
    });
    fig.appendChild(btn);
  });

  // Version picker: jumps to CHANGELOG.html when present.
  const picker = document.getElementById('version-picker');
  if (picker) {
    picker.addEventListener('change', () => {
      if (picker.value) window.location.href = picker.value;
    });
  }
})();
