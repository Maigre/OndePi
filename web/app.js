async function fetchStatus() {
  const response = await fetch('/api/status');
  if (!response.ok) {
    return null;
  }
  return response.json();
}

async function fetchConfig() {
  const response = await fetch('/api/config');
  if (!response.ok) {
    return null;
  }
  return response.json();
}

async function fetchDevices() {
  const response = await fetch('/api/devices');
  if (!response.ok) {
    return [];
  }
  const payload = await response.json();
  return payload;
}

async function updateConfig(method, payload) {
  const response = await fetch('/api/config', {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message = detail.detail || 'Config update failed';
    throw new Error(message);
  }
  return response.json();
}

async function startStream() {
  await fetch('/api/stream/start', { method: 'POST' });
}

async function stopStream() {
  await fetch('/api/stream/stop', { method: 'POST' });
}

async function setGain(gainDb) {
  await fetch('/api/gain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gain_db: gainDb }),
  });
}

async function testInput() {
  const response = await fetch('/api/test-input', { method: 'POST' });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || 'Test input failed');
  }
  return response.json();
}

function updateMeter(element, value) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  element.style.width = `${percent}%`;
}

function renderConfigForm(config) {
  const container = document.getElementById('config-form');
  container.innerHTML = '';

  Object.entries(config).forEach(([sectionName, sectionValue]) => {
    const section = document.createElement('div');
    section.className = 'config-section';

    const title = document.createElement('h3');
    title.textContent = sectionName;
    section.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'config-grid';

    Object.entries(sectionValue).forEach(([key, value]) => {
      const field = document.createElement('div');
      field.className = 'config-field';

      const label = document.createElement('label');
      label.textContent = key;
      const tooltip = getFieldTooltip(sectionName, key);
      if (tooltip) {
        label.title = tooltip;
      }
      field.appendChild(label);

  const input = document.createElement('input');
      input.dataset.path = `${sectionName}.${key}`;

      if (typeof value === 'number') {
        input.type = 'number';
        input.value = value;
      } else if (typeof value === 'boolean') {
        input.type = 'checkbox';
        input.checked = value;
      } else {
        input.type = 'text';
        input.value = value ?? '';
      }

      field.appendChild(input);
      grid.appendChild(field);
    });

    section.appendChild(grid);
    container.appendChild(section);
  });
}

function getFieldTooltip(section, key) {
  if (section === 'input' && key === 'limiter_enabled') {
    return 'Enable soft limiter to avoid saturation.';
  }
  if (section === 'input' && key === 'limiter_drive') {
    return 'Limiter drive strength. Higher = more compression.';
  }
  return '';
}

function collectConfigFromForm() {
  const inputs = Array.from(document.querySelectorAll('#config-form input'));
  const result = {};

  inputs.forEach((input) => {
    const path = input.dataset.path.split('.');
    let current = result;
    for (let i = 0; i < path.length - 1; i += 1) {
      const key = path[i];
      current[key] = current[key] || {};
      current = current[key];
    }
    const key = path[path.length - 1];
    if (input.type === 'checkbox') {
      current[key] = input.checked;
    } else if (input.type === 'number') {
      const parsed = input.value === '' ? 0 : Number(input.value);
      current[key] = Number.isNaN(parsed) ? 0 : parsed;
    } else {
      current[key] = input.value;
    }
  });

  return result;
}

async function poll() {
  const status = await fetchStatus();
  if (!status) {
    return;
  }
  const state = status.state;
  const configValidation = document.getElementById('config-validation');
  const setupPanel = document.getElementById('setup-panel');
  const setupIssues = document.getElementById('setup-issues');
  document.getElementById('streaming').textContent = state.streaming ? 'Yes' : 'No';
  document.getElementById('started').textContent = state.started_at || '—';
  document.getElementById('retry-count').textContent = state.retry_count ?? 0;
  document.getElementById('last-retry').textContent = state.last_retry_at || '—';
  document.getElementById('error').textContent = state.last_error || '—';
  document.getElementById('gain-value').textContent = `${state.gain_db.toFixed(1)} dB`;
  updateMeter(document.getElementById('rms'), state.levels.rms);
  updateMeter(document.getElementById('peak'), state.levels.peak);
  const device = status.device;
  if (device) {
    document.getElementById('device-status').textContent = device.status || '—';
    document.getElementById('device-error').textContent = device.last_error || '—';
    document.getElementById('device-name').textContent = device.device || '—';
    const limiter = device.limiter_enabled ? `On (${device.limiter_drive})` : 'Off';
    document.getElementById('device-limiter').textContent = limiter;
  }
  updateMeter(document.getElementById('device-rms'), state.levels.rms);
  updateMeter(document.getElementById('device-peak'), state.levels.peak);
  if (status.config && !status.config.valid) {
    configValidation.textContent = status.config.errors.join('\n');
    setupPanel.classList.remove('hidden');
    setupIssues.innerHTML = '';
    const issues = status.config.issues || [];
    issues.forEach((issue) => {
      const item = document.createElement('li');
      item.textContent = `${issue.field} ${issue.message}`;
      setupIssues.appendChild(item);
    });
    highlightFields(issues);
  } else {
    configValidation.textContent = '';
    setupPanel.classList.add('hidden');
    setupIssues.innerHTML = '';
    highlightFields([]);
  }
}

function highlightFields(issues) {
  const fields = document.querySelectorAll('.config-field');
  fields.forEach((field) => field.classList.remove('field-error'));
  issues.forEach((issue) => {
    const input = document.querySelector(`input[data-path="${issue.field}"]`);
    if (input && input.parentElement) {
      input.parentElement.classList.add('field-error');
    }
  });
}

async function init() {
  const config = await fetchConfig();
  if (config) {
    renderConfigForm(config);
  }

  document.getElementById('start').addEventListener('click', startStream);
  document.getElementById('stop').addEventListener('click', stopStream);

  const gainInput = document.getElementById('gain');
  gainInput.addEventListener('input', (event) => {
    const value = parseFloat(event.target.value);
    document.getElementById('gain-value').textContent = `${value.toFixed(1)} dB`;
  });
  gainInput.addEventListener('change', (event) => {
    const value = parseFloat(event.target.value);
    setGain(value);
  });

  const configError = document.getElementById('config-error');

  const deviceSelect = document.getElementById('device-select');
  const deviceRefresh = document.getElementById('device-refresh');

  async function loadDevices() {
    const payload = await fetchDevices();
    const devices = payload.devices || [];
    const current = payload.current;
    deviceSelect.innerHTML = '';
    devices.forEach((device) => {
      const option = document.createElement('option');
      option.value = device.alsa;
      option.textContent = `${device.name} (${device.channels} ch)`;
      if (current && current === device.alsa) {
        option.selected = true;
      }
      deviceSelect.appendChild(option);
    });
  }

  deviceSelect.addEventListener('change', () => {
    const selected = deviceSelect.value;
    const input = document.querySelector('input[data-path="input.alsa_device"]');
    if (input) {
      input.value = selected;
    }
    updateConfig('PATCH', { input: { alsa_device: selected } }).catch((error) => {
      const configError = document.getElementById('config-error');
      configError.textContent = error.message;
    });
  });

  deviceRefresh.addEventListener('click', loadDevices);
  await loadDevices();

  async function reloadConfig() {
    configError.textContent = '';
    const fresh = await fetchConfig();
    if (fresh) {
      renderConfigForm(fresh);
    }
  }

  document.getElementById('config-put').addEventListener('click', async () => {
    configError.textContent = '';
    try {
      const payload = collectConfigFromForm();
      await updateConfig('PUT', payload);
    } catch (error) {
      configError.textContent = error.message;
    }
  });

  document.getElementById('config-patch').addEventListener('click', async () => {
    configError.textContent = '';
    try {
      const payload = collectConfigFromForm();
      await updateConfig('PATCH', payload);
    } catch (error) {
      configError.textContent = error.message;
    }
  });

  document.getElementById('config-reload').addEventListener('click', reloadConfig);

  const testButton = document.getElementById('test-input');
  const testError = document.getElementById('test-error');
  testButton.addEventListener('click', async () => {
    testError.textContent = '';
    try {
      const levels = await testInput();
      updateMeter(document.getElementById('test-rms'), levels.rms || 0);
      updateMeter(document.getElementById('test-peak'), levels.peak || 0);
    } catch (error) {
      testError.textContent = error.message;
    }
  });

  setInterval(poll, 1500);
  poll();
}

init();
