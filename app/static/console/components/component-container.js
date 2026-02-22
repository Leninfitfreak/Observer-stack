export class ComponentContainer {
  constructor({ title, id, controls = [], onFullscreenToggle, onReset, loadingText = 'Loading...' }) {
    this.id = id;
    this.root = document.createElement('section');
    this.root.className = 'component-container';
    this.root.dataset.componentId = id;

    const header = document.createElement('header');
    header.className = 'component-header';

    const titleEl = document.createElement('h3');
    titleEl.textContent = title;
    header.appendChild(titleEl);

    const controlsWrap = document.createElement('div');
    controlsWrap.className = 'component-controls';

    controls.forEach((control) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'control-btn';
      btn.textContent = control.label;
      btn.addEventListener('click', control.onClick);
      controlsWrap.appendChild(btn);
    });

    const fullBtn = document.createElement('button');
    fullBtn.type = 'button';
    fullBtn.className = 'control-btn';
    fullBtn.textContent = 'Fullscreen';
    fullBtn.addEventListener('click', () => onFullscreenToggle?.(id));
    controlsWrap.appendChild(fullBtn);

    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'control-btn';
    resetBtn.textContent = 'Reset';
    resetBtn.addEventListener('click', () => onReset?.(id));
    controlsWrap.appendChild(resetBtn);

    header.appendChild(controlsWrap);
    this.root.appendChild(header);

    this.body = document.createElement('div');
    this.body.className = 'component-body';
    this.root.appendChild(this.body);

    this.status = document.createElement('div');
    this.status.className = 'component-status hidden';
    this.status.textContent = loadingText;
    this.root.appendChild(this.status);
  }

  setLoading(isLoading, message = 'Loading...') {
    this.status.textContent = message;
    this.status.classList.toggle('hidden', !isLoading);
    this.root.classList.toggle('is-loading', isLoading);
  }

  setError(message) {
    this.status.textContent = message;
    this.status.classList.remove('hidden');
    this.root.classList.add('is-error');
  }

  clearError() {
    this.root.classList.remove('is-error');
  }
}
