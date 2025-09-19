const adminState = {
  services: {},
  feedback: {},
};

const SERVICE_LABELS = {
  github: 'GitHub',
  openai: 'OpenAI',
};

function formatServiceName(service) {
  if (!service) {
    return '';
  }
  if (SERVICE_LABELS[service]) {
    return SERVICE_LABELS[service];
  }
  return service.charAt(0).toUpperCase() + service.slice(1);
}

function formatTimestamp(value) {
  if (!value) {
    return 'Sin configuración guardada';
  }
  try {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return `Última actualización: ${date.toLocaleString('es-ES')}`;
    }
  } catch (err) {
    // ignore formatting errors and fallback to raw value
  }
  return `Última actualización: ${value}`;
}

function setGlobalMessage(message, type = 'error') {
  const container = document.getElementById('adminGlobalMessage');
  if (!container) {
    return;
  }
  if (!message) {
    container.classList.add('is-hidden');
    container.textContent = '';
    return;
  }
  container.textContent = message;
  container.classList.remove('is-hidden');
  container.classList.remove('admin-callout', 'admin-warning');
  if (type === 'success') {
    container.classList.add('admin-callout');
  } else {
    container.classList.add('admin-warning');
  }
}

function ensureAdminSession() {
  const slug = getStoredSlug();
  const token = getStoredToken();
  return Boolean(slug && token);
}

function renderEmptyState() {
  const container = document.getElementById('serviceForms');
  if (!container) {
    return;
  }
  container.innerHTML = '<p class="admin-empty">No hay servicios configurables disponibles.</p>';
}

function applyFeedbackToDom(service) {
  const feedback = adminState.feedback[service];
  const messageElement = document.querySelector(
    `[data-service-block="${service}"] .admin-config__message`
  );
  if (!messageElement) {
    return;
  }
  messageElement.classList.remove(
    'admin-config__message--success',
    'admin-config__message--error'
  );
  if (!feedback || !feedback.message) {
    messageElement.textContent = '';
    return;
  }
  messageElement.textContent = feedback.message;
  if (feedback.type === 'success') {
    messageElement.classList.add('admin-config__message--success');
  } else if (feedback.type === 'error') {
    messageElement.classList.add('admin-config__message--error');
  }
}

function setFormFeedback(service, message, type = 'info') {
  if (!message) {
    delete adminState.feedback[service];
  } else {
    adminState.feedback[service] = { message, type };
  }
  applyFeedbackToDom(service);
}

function setFormSubmitting(form, isSubmitting) {
  if (!form) {
    return;
  }
  const submitBtn = form.querySelector('.admin-config__submit');
  if (!submitBtn) {
    return;
  }
  const defaultLabel = submitBtn.dataset.defaultLabel || submitBtn.textContent;
  submitBtn.dataset.defaultLabel = defaultLabel;
  submitBtn.disabled = Boolean(isSubmitting);
  submitBtn.textContent = isSubmitting ? 'Validando…' : defaultLabel;
}

function createFieldElement(service, key, field) {
  const fieldWrapper = document.createElement('div');
  fieldWrapper.className = 'admin-config__field';

  const label = document.createElement('label');
  label.setAttribute('for', `${service}-${key}`);
  label.textContent = field.label || key;
  fieldWrapper.appendChild(label);

  const input = document.createElement('input');
  input.id = `${service}-${key}`;
  input.dataset.fieldKey = key;
  input.type = field.sensitive ? 'password' : 'text';
  input.autocomplete = field.sensitive ? 'off' : 'on';
  input.placeholder = field.metadata && field.metadata.placeholder ? field.metadata.placeholder : '';
  if (!field.sensitive && typeof field.value === 'string') {
    input.value = field.value;
  }
  if (field.sensitive && field.has_value) {
    input.placeholder = 'Se mantiene el valor actual al dejarlo vacío';
  }
  fieldWrapper.appendChild(input);

  if (field.description) {
    const description = document.createElement('p');
    description.className = 'admin-config__description';
    description.textContent = field.description;
    fieldWrapper.appendChild(description);
  }

  if (field.metadata && field.metadata.example) {
    const meta = document.createElement('p');
    meta.className = 'admin-config__metadata';
    meta.textContent = `Ejemplo: ${field.metadata.example}`;
    fieldWrapper.appendChild(meta);
  }

  return fieldWrapper;
}

function renderForms() {
  const container = document.getElementById('serviceForms');
  if (!container) {
    return;
  }
  container.innerHTML = '';
  const services = adminState.services || {};
  const entries = Object.entries(services);
  if (entries.length === 0) {
    renderEmptyState();
    return;
  }
  entries.sort(([a], [b]) => a.localeCompare(b));
  entries.forEach(([serviceKey, serviceData]) => {
    const section = document.createElement('section');
    section.className = 'admin-config';
    section.dataset.serviceBlock = serviceKey;

    const header = document.createElement('div');
    header.className = 'admin-config__header';

    const title = document.createElement('h2');
    title.className = 'admin-config__title';
    title.textContent = formatServiceName(serviceKey);
    header.appendChild(title);

    const updated = document.createElement('span');
    updated.className = 'admin-config__updated';
    updated.textContent = formatTimestamp(serviceData.updated_at);
    header.appendChild(updated);
    section.appendChild(header);

    const form = document.createElement('form');
    form.dataset.service = serviceKey;
    const fieldsWrapper = document.createElement('div');
    fieldsWrapper.className = 'admin-config__fields';

    const fieldEntries = Object.entries(serviceData.fields || {});
    fieldEntries.forEach(([fieldKey, fieldData]) => {
      fieldsWrapper.appendChild(
        createFieldElement(serviceKey, fieldKey, fieldData)
      );
    });
    form.appendChild(fieldsWrapper);

    const actions = document.createElement('div');
    actions.className = 'admin-config__actions';

    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'admin-config__submit';
    submit.textContent = 'Probar y guardar';
    actions.appendChild(submit);

    const message = document.createElement('div');
    message.className = 'admin-config__message';
    actions.appendChild(message);

    form.appendChild(actions);
    form.addEventListener('submit', (event) => handleSubmit(event, serviceKey));
    section.appendChild(form);

    container.appendChild(section);
    applyFeedbackToDom(serviceKey);
  });
}

function buildPayloadFromForm(service, form) {
  const payload = {
    slug: getStoredSlug(),
    service,
    values: {},
  };
  const fields = adminState.services[service]?.fields || {};
  const missing = [];
  const inputs = form.querySelectorAll('input[data-field-key]');
  inputs.forEach((input) => {
    const key = input.dataset.fieldKey;
    const definition = fields[key] || {};
    const raw = input.value || '';
    const value = raw.trim();
    const hasStoredValue = Boolean(definition.has_value);
    if (!value && definition.sensitive && hasStoredValue) {
      return;
    }
    if (!value && definition.required && !hasStoredValue) {
      missing.push(definition.label || key);
      return;
    }
    if (value || !definition.sensitive) {
      payload.values[key] = value;
    }
  });
  return { payload, missing };
}

async function handleSubmit(event, service) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!ensureAdminSession()) {
    setGlobalMessage('Tu sesión expiró. Vuelve al portal para iniciar sesión.', 'error');
    renderEmptyState();
    return;
  }

  setFormFeedback(service, 'Probando credenciales…', 'info');
  const { payload, missing } = buildPayloadFromForm(service, form);
  if (missing.length > 0) {
    setFormFeedback(
      service,
      `Completa los campos obligatorios: ${missing.join(', ')}`,
      'error'
    );
    return;
  }

  const token = getStoredToken();
  const hasExisting = Object.values(adminState.services[service]?.fields || {}).some(
    (field) => field.has_value
  );
  const method = hasExisting ? 'PUT' : 'POST';

  setFormSubmitting(form, true);
  try {
    const response = await fetch('/api/admin/service-configs', {
      method,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      setGlobalMessage('Tu sesión de administrador venció. Inicia sesión nuevamente.', 'error');
      clearSession();
      updateAdminLinkVisibility(false);
      renderEmptyState();
      return;
    }
    if (!response.ok) {
      const errorMessage = data.error || 'No se pudo guardar la configuración.';
      const testMessage = data.test_result && data.test_result.message;
      setFormFeedback(service, testMessage || errorMessage, 'error');
      return;
    }
    if (data && data.config) {
      adminState.services[service] = data.config;
    }
    const successMessage =
      (data.test_result && data.test_result.message) ||
      'Credenciales validadas y guardadas correctamente.';
    adminState.feedback[service] = { message: successMessage, type: 'success' };
    renderForms();
  } catch (err) {
    setFormFeedback(
      service,
      'No pudimos comunicarnos con el backend. Intenta nuevamente.',
      'error'
    );
  } finally {
    setFormSubmitting(form, false);
  }
}

async function loadServiceConfigs() {
  if (!ensureAdminSession()) {
    setGlobalMessage('Debes iniciar sesión en el portal antes de administrar las integraciones.', 'error');
    renderEmptyState();
    return;
  }
  const slug = getStoredSlug();
  const token = getStoredToken();
  setGlobalMessage('');
  try {
    const response = await fetch(
      `/api/admin/service-configs?slug=${encodeURIComponent(slug)}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    );
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      setGlobalMessage('Tu sesión de administrador venció. Inicia sesión nuevamente.', 'error');
      clearSession();
      updateAdminLinkVisibility(false);
      renderEmptyState();
      return;
    }
    if (!response.ok) {
      const errorMessage = data.error || 'No se pudieron cargar las configuraciones.';
      setGlobalMessage(errorMessage, 'error');
      renderEmptyState();
      return;
    }
    adminState.services = data.services || {};
    adminState.feedback = {};
    renderForms();
  } catch (err) {
    setGlobalMessage('Error de red al obtener las configuraciones.', 'error');
    renderEmptyState();
  }
}

function initializeAdminPage() {
  updateAdminLinkVisibility();
  if (!ensureAdminSession()) {
    setGlobalMessage('Debes iniciar sesión en el portal antes de administrar las integraciones.', 'error');
    renderEmptyState();
    return;
  }
  loadServiceConfigs();
}

document.addEventListener('DOMContentLoaded', () => {
  initializeAdminPage();
});
