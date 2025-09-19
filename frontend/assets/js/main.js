// main.js - lógica del portal de misiones

const API_BASE = '';

let landingContentHTML = '';

function cacheLandingContent() {
  if (landingContentHTML || typeof document === 'undefined') {
    return;
  }
  const landingContainer = document.getElementById('content');
  if (landingContainer) {
    landingContentHTML = landingContainer.innerHTML;
  }
}

cacheLandingContent();

function getApiBase() {
  if (typeof API_BASE !== 'undefined' && API_BASE) {
    return API_BASE;
  }
  if (typeof window !== 'undefined' && window.API_BASE) {
    return window.API_BASE;
  }
  return '';
}

function joinBase(base, path) {
  const basePart = typeof base === 'string' ? base.trim() : '';
  const pathPart = typeof path === 'string' ? path.trim() : '';
  if (!pathPart) {
    return basePart || '';
  }
  const needsLeadingSlash =
    !pathPart.startsWith('/') &&
    !pathPart.startsWith('http://') &&
    !pathPart.startsWith('https://') &&
    !pathPart.startsWith('//') &&
    !pathPart.startsWith('data:') &&
    !pathPart.startsWith('blob:') &&
    !pathPart.startsWith('mailto:') &&
    !pathPart.startsWith('?');
  const normalizedPath = needsLeadingSlash ? `/${pathPart}` : pathPart;
  if (!basePart) {
    if (normalizedPath.startsWith('//')) {
      return normalizedPath.replace(/^\/+/g, '/');
    }
    if (normalizedPath.startsWith('/') || normalizedPath.startsWith('?')) {
      return normalizedPath;
    }
    return `/${normalizedPath}`;
  }
  try {
    return new URL(normalizedPath, basePart).toString();
  } catch (err) {
    const cleanedBase = basePart.replace(/\/+$/g, '');
    if (normalizedPath.startsWith('?')) {
      return `${cleanedBase}${normalizedPath}`;
    }
    const cleanedPath = normalizedPath.replace(/^\/+/g, '');
    return `${cleanedBase}/${cleanedPath}`;
  }
}

function apiFetch(path, options) {
  return fetch(joinBase(getApiBase(), path), options);
}
const STORAGE_KEYS = {
  slug: 'student_slug',
  token: 'session_token',
  mission: 'current_mission',
  admin: 'session_is_admin',
};

function _normalizeBooleanFlag(value) {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return value !== 0;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    return (
      normalized === '1' ||
      normalized === 'true' ||
      normalized === 'yes' ||
      normalized === 'y' ||
      normalized === 'on' ||
      normalized === 'si' ||
      normalized === 'sí'
    );
  }
  return false;
}

function updateMissionAdminLink(isAdmin) {
  if (typeof document === 'undefined') {
    return;
  }
  const navigation = document.querySelector('.portal-header__nav');
  if (!navigation) {
    return;
  }
  const existingLink = navigation.querySelector('[data-action="mission-admin"]');
  const shouldDisplay = _normalizeBooleanFlag(isAdmin);
  if (!shouldDisplay) {
    if (existingLink && existingLink.parentElement) {
      existingLink.parentElement.removeChild(existingLink);
    }
    return;
  }
  if (existingLink) {
    existingLink.textContent = 'Panel administrativo';
    existingLink.onclick = (event) => {
      const target = event && event.currentTarget ? event.currentTarget : existingLink;
      const requestedSection = target && target.dataset ? target.dataset.defaultSection : undefined;
      renderAdminModule(resolvePreferredAdminSection(requestedSection));
    };
    return;
  }
  const adminButton = document.createElement('button');
  adminButton.type = 'button';
  adminButton.className = 'portal-header__link portal-header__link--admin';
  adminButton.dataset.action = 'mission-admin';
  adminButton.textContent = 'Panel administrativo';
  adminButton.onclick = (event) => {
    const target = event && event.currentTarget ? event.currentTarget : adminButton;
    const requestedSection = target && target.dataset ? target.dataset.defaultSection : undefined;
    renderAdminModule(resolvePreferredAdminSection(requestedSection));
  };
  const loginLink = navigation.querySelector('[data-action="login"]');
  if (loginLink) {
    loginLink.insertAdjacentElement('afterend', adminButton);
    return;
  }
  navigation.appendChild(adminButton);
}

function storeSession(slug, token, isAdmin) {
  if (slug) {
    localStorage.setItem(STORAGE_KEYS.slug, slug);
  }
  if (token) {
    localStorage.setItem(STORAGE_KEYS.token, token);
  } else {
    localStorage.removeItem(STORAGE_KEYS.token);
  }
  if (typeof isAdmin !== 'undefined') {
    if (isAdmin === null) {
      localStorage.removeItem(STORAGE_KEYS.admin);
    } else {
      const flag = _normalizeBooleanFlag(isAdmin);
      localStorage.setItem(STORAGE_KEYS.admin, flag ? '1' : '0');
    }
  }
}

function clearSession() {
  localStorage.removeItem(STORAGE_KEYS.slug);
  localStorage.removeItem(STORAGE_KEYS.token);
  localStorage.removeItem(STORAGE_KEYS.admin);
  updateMissionAdminLink(false);
}

const ADMIN_AVAILABLE_ROLES = ['Ventas', 'Operaciones'];
const ADMIN_SECTION_KEYS = ['missions', 'users', 'roles', 'integrations'];

function normalizeAdminSection(sectionName) {
  if (!sectionName) {
    return '';
  }
  const normalized = String(sectionName).trim().toLowerCase();
  return ADMIN_SECTION_KEYS.includes(normalized) ? normalized : '';
}

function resolvePreferredAdminSection(requestedSection) {
  const normalizedRequested = normalizeAdminSection(requestedSection);
  if (normalizedRequested) {
    return normalizedRequested;
  }
  if (typeof window !== 'undefined') {
    const globalSection =
      normalizeAdminSection(window.defaultAdminSection) ||
      normalizeAdminSection(window.preferredAdminSection);
    if (globalSection) {
      return globalSection;
    }
    try {
      const search = window.location && typeof window.location.search === 'string' ? window.location.search : '';
      if (search) {
        const params = new URLSearchParams(search);
        const querySection =
          normalizeAdminSection(params.get('admin')) || normalizeAdminSection(params.get('adminSection'));
        if (querySection) {
          return querySection;
        }
      }
    } catch (err) {
      /* no-op */
    }
    if (window.location && typeof window.location.hash === 'string') {
      const hash = window.location.hash.trim();
      const hashMatch = hash.match(/admin(?:[:=])([a-z]+)/i);
      if (hashMatch) {
        const hashSection = normalizeAdminSection(hashMatch[1]);
        if (hashSection) {
          return hashSection;
        }
      }
      const normalizedHash = normalizeAdminSection(hash.replace(/^#/, ''));
      if (normalizedHash) {
        return normalizedHash;
      }
    }
  }
  return 'missions';
}

const ADMIN_VERIFICATION_TYPE_OPTIONS = [
  { value: 'evidence', label: 'Evidencia (archivos)' },
  { value: 'script_output', label: 'Salida de script' },
  { value: 'llm_evaluation', label: 'Evaluación con LLM' },
];

function buildAdminVerificationTypeOptions(selectedValue = '') {
  const normalizedSelected = typeof selectedValue === 'string' ? selectedValue : '';
  const baseOption = '<option value="">Selecciona un tipo de verificación</option>';
  const otherOptions = ADMIN_VERIFICATION_TYPE_OPTIONS.map((option) => {
    const isSelected = option.value === normalizedSelected ? ' selected' : '';
    return `<option value="${escapeHtml(option.value)}"${isSelected}>${escapeHtml(option.label)}</option>`;
  }).join('');
  return `${baseOption}${otherOptions}`;
}

function splitMissionContent(content) {
  const rawContent =
    content && typeof content === 'object' && !Array.isArray(content) ? { ...content } : {};
  const verificationType =
    typeof rawContent.verification_type === 'string' ? rawContent.verification_type : '';
  const sourceData =
    rawContent.source && typeof rawContent.source === 'object' && !Array.isArray(rawContent.source)
      ? rawContent.source
      : {};
  const source = {
    repository: typeof sourceData.repository === 'string' ? sourceData.repository : '',
    default_branch:
      typeof sourceData.default_branch === 'string' ? sourceData.default_branch : '',
    base_path: typeof sourceData.base_path === 'string' ? sourceData.base_path : '',
  };
  const deliverables = Array.isArray(rawContent.deliverables)
    ? rawContent.deliverables
        .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
        .map((item) => ({
          type: item.type != null ? String(item.type) : '',
          path: item.path != null ? String(item.path) : '',
          content: item.content != null ? String(item.content) : '',
          feedback_fail: item.feedback_fail != null ? String(item.feedback_fail) : '',
        }))
    : [];
  delete rawContent.verification_type;
  delete rawContent.source;
  delete rawContent.deliverables;
  return { verificationType, source, deliverables, extras: rawContent };
}

function cloneMissionContentExtras(extras) {
  if (!extras || typeof extras !== 'object' || Array.isArray(extras)) {
    return {};
  }
  try {
    return JSON.parse(JSON.stringify(extras));
  } catch (err) {
    return { ...extras };
  }
}

function combineMissionContentParts({ verificationType, source, deliverables, extras }) {
  const result = cloneMissionContentExtras(extras);
  const normalizedVerification =
    typeof verificationType === 'string' ? verificationType.trim() : '';
  if (normalizedVerification) {
    result.verification_type = normalizedVerification;
  }
  const sourceRepository = source && typeof source.repository === 'string' ? source.repository.trim() : '';
  const sourceBranch =
    source && typeof source.default_branch === 'string' ? source.default_branch.trim() : '';
  const sourceBasePath =
    source && typeof source.base_path === 'string' ? source.base_path.trim() : '';
  if (sourceRepository || sourceBranch || sourceBasePath) {
    result.source = {
      ...(result.source && typeof result.source === 'object' && !Array.isArray(result.source)
        ? result.source
        : {}),
      repository: sourceRepository,
      default_branch: sourceBranch,
      base_path: sourceBasePath,
    };
  } else {
    delete result.source;
  }
  const normalizedDeliverables = Array.isArray(deliverables)
    ? deliverables
        .filter((item) => item && typeof item === 'object' && !Array.isArray(item))
        .map((item) => {
          const normalized = {};
          if (typeof item.type === 'string' && item.type.trim()) {
            normalized.type = item.type.trim();
          }
          if (typeof item.path === 'string' && item.path.trim()) {
            normalized.path = item.path.trim();
          }
          if (typeof item.content === 'string' && item.content.trim()) {
            normalized.content = item.content;
          }
          if (typeof item.feedback_fail === 'string' && item.feedback_fail.trim()) {
            normalized.feedback_fail = item.feedback_fail.trim();
          }
          return normalized;
        })
        .filter((item) => Object.keys(item).length > 0)
    : [];
  if (normalizedDeliverables.length > 0) {
    result.deliverables = normalizedDeliverables;
  } else {
    delete result.deliverables;
  }
  return result;
}

function updateDeliverablesEmptyState(listContainer) {
  if (!listContainer) {
    return;
  }
  const hasItems = listContainer.querySelector('[data-deliverable-item]');
  let placeholder = listContainer.querySelector('[data-deliverables-empty]');
  if (!hasItems) {
    if (!placeholder) {
      placeholder = document.createElement('p');
      placeholder.dataset.deliverablesEmpty = '1';
      placeholder.className = 'admin-field__hint';
      placeholder.textContent = 'No hay entregables configurados.';
      listContainer.appendChild(placeholder);
    }
  } else if (placeholder) {
    placeholder.remove();
  }
}

function createDeliverableEditorRow(initialData = {}, handlers = {}) {
  const { onChange, onRemove, listContainer } = handlers;
  const data = initialData && typeof initialData === 'object' ? initialData : {};
  const row = document.createElement('div');
  row.className = 'admin-deliverable';
  row.dataset.deliverableItem = '1';
  const initialType = data.type && typeof data.type === 'string' ? data.type : 'file_exists';
  const initialPath = data.path && typeof data.path === 'string' ? data.path : '';
  const initialContent = data.content && typeof data.content === 'string' ? data.content : '';
  const initialFeedback =
    data.feedback_fail && typeof data.feedback_fail === 'string' ? data.feedback_fail : '';
  row.innerHTML = `
    <div class="admin-deliverable__body">
      <div class="admin-field">
        <label class="admin-field__label">Tipo</label>
        <input type="text" class="admin-field__control" data-field="type" list="missionDeliverableTypeOptions" placeholder="file_exists" value="${escapeHtml(initialType)}">
      </div>
      <div class="admin-field">
        <label class="admin-field__label">Ruta</label>
        <input type="text" class="admin-field__control" data-field="path" placeholder="docs/entrega.txt" value="${escapeHtml(initialPath)}">
      </div>
      <div class="admin-field">
        <label class="admin-field__label">Contenido esperado</label>
        <textarea class="admin-field__control admin-field__control--textarea" data-field="content" rows="3" placeholder="Texto requerido en el archivo">${escapeHtml(initialContent)}</textarea>
      </div>
      <div class="admin-field">
        <label class="admin-field__label">Mensaje al fallar</label>
        <input type="text" class="admin-field__control" data-field="feedback_fail" placeholder="Mensaje personalizado" value="${escapeHtml(initialFeedback)}">
      </div>
    </div>
    <div class="admin-deliverable__actions">
      <button type="button" class="admin-button admin-button--danger admin-button--small" data-action="remove-deliverable">Eliminar</button>
    </div>
  `;
  const typeInput = row.querySelector('[data-field="type"]');
  const pathInput = row.querySelector('[data-field="path"]');
  const contentInput = row.querySelector('[data-field="content"]');
  const feedbackInput = row.querySelector('[data-field="feedback_fail"]');
  const removeButton = row.querySelector('[data-action="remove-deliverable"]');
  const triggerChange = () => {
    if (typeof onChange === 'function') {
      onChange();
    }
  };
  const updateContentRequirement = () => {
    if (!typeInput || !contentInput) {
      return;
    }
    const requiresContent = (typeInput.value || '').trim() === 'file_contains';
    if (requiresContent) {
      contentInput.setAttribute('required', 'required');
    } else {
      contentInput.removeAttribute('required');
    }
  };
  [typeInput, pathInput, contentInput, feedbackInput].forEach((field) => {
    if (!field) {
      return;
    }
    field.addEventListener('input', triggerChange);
    field.addEventListener('change', triggerChange);
  });
  if (typeInput) {
    typeInput.addEventListener('change', updateContentRequirement);
    updateContentRequirement();
  }
  if (removeButton) {
    removeButton.onclick = () => {
      row.remove();
      if (listContainer) {
        updateDeliverablesEmptyState(listContainer);
      }
      if (typeof onRemove === 'function') {
        onRemove();
      }
    };
  }
  return row;
}

function renderDeliverablesEditor(listContainer, deliverables, handlers = {}) {
  if (!listContainer) {
    return;
  }
  listContainer.innerHTML = '';
  const items = Array.isArray(deliverables) ? deliverables : [];
  items.forEach((item) => {
    const rowHandlers = { ...handlers, listContainer };
    if (!rowHandlers.onRemove && typeof handlers.onChange === 'function') {
      rowHandlers.onRemove = handlers.onChange;
    }
    const row = createDeliverableEditorRow(item, rowHandlers);
    listContainer.appendChild(row);
  });
  updateDeliverablesEmptyState(listContainer);
}

function collectDeliverablesFromEditor(listContainer) {
  const deliverables = [];
  const errors = [];
  if (!listContainer) {
    return { deliverables, errors };
  }
  const rows = Array.from(listContainer.querySelectorAll('[data-deliverable-item]'));
  rows.forEach((row, index) => {
    const typeField = row.querySelector('[data-field="type"]');
    const pathField = row.querySelector('[data-field="path"]');
    const contentField = row.querySelector('[data-field="content"]');
    const feedbackField = row.querySelector('[data-field="feedback_fail"]');
    const typeValue = typeField && typeof typeField.value === 'string' ? typeField.value.trim() : '';
    const pathValue = pathField && typeof pathField.value === 'string' ? pathField.value.trim() : '';
    const contentValue = contentField && typeof contentField.value === 'string' ? contentField.value : '';
    const feedbackValue =
      feedbackField && typeof feedbackField.value === 'string' ? feedbackField.value.trim() : '';
    const hasAnyValue = Boolean(typeValue || pathValue || contentValue.trim() || feedbackValue);
    if (!typeValue && hasAnyValue) {
      errors.push(`El deliverable #${index + 1} necesita un tipo.`);
    }
    if (!pathValue && hasAnyValue) {
      errors.push(`El deliverable #${index + 1} necesita una ruta.`);
    }
    if (typeValue === 'file_contains' && !contentValue.trim()) {
      errors.push(`El deliverable #${index + 1} requiere un contenido esperado.`);
    }
    if (typeValue && pathValue) {
      const item = { type: typeValue, path: pathValue };
      if (contentValue && contentValue.trim()) {
        item.content = contentValue;
      }
      if (feedbackValue) {
        item.feedback_fail = feedbackValue;
      }
      deliverables.push(item);
    }
  });
  return { deliverables, errors };
}

function renderAdminDeliverablesSummary(summaryContainer, deliverables, errors = []) {
  if (!summaryContainer) {
    return;
  }
  summaryContainer.innerHTML = '';
  const hasDeliverables = Array.isArray(deliverables) && deliverables.length > 0;
  let summaryRendered = false;
  if (hasDeliverables) {
    const list = document.createElement('ul');
    list.className = 'admin-deliverables-summary__list';
    deliverables.forEach((item) => {
      if (!item || typeof item !== 'object') {
        return;
      }
      const parts = [];
      if (typeof item.type === 'string' && item.type.trim()) {
        parts.push(item.type.trim());
      }
      if (typeof item.path === 'string' && item.path.trim()) {
        parts.push(item.path.trim());
      }
      if (parts.length === 0) {
        return;
      }
      const entry = document.createElement('li');
      entry.textContent = parts.join(' — ');
      list.appendChild(entry);
    });
    if (list.children.length > 0) {
      summaryContainer.appendChild(list);
      summaryRendered = true;
    }
  }
  const hasErrors = Array.isArray(errors) && errors.length > 0;
  if (hasErrors) {
    const helper = document.createElement('p');
    helper.className = 'admin-field__hint';
    helper.textContent = errors[0];
    summaryContainer.appendChild(helper);
    return;
  }
  if (!summaryRendered) {
    const helper = document.createElement('p');
    helper.className = 'admin-field__hint';
    helper.textContent = 'Agrega deliverables para generar un resumen automático.';
    summaryContainer.appendChild(helper);
  }
}

async function fetchMissionsForRole(role, token) {
  const params = new URLSearchParams();
  if (role) {
    params.set('role', role);
  }
  const headers = token
    ? {
        Authorization: `Bearer ${token}`,
      }
    : {};
  const url = `/api/missions${params.toString() ? `?${params.toString()}` : ''}`;
  try {
    const res = await apiFetch(url, {
      credentials: 'include',
      headers,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (!res.ok) {
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      throw new Error(backendMessage || 'No fue posible obtener las misiones.');
    }
    const missions = Array.isArray(data.missions) ? data.missions : [];
    return missions.map((mission) => {
      if (!mission || typeof mission !== 'object') {
        return mission;
      }
      const normalized = { ...mission };
      if (Object.prototype.hasOwnProperty.call(normalized, 'mission_id')) {
        normalized.mission_id = normalized.mission_id != null ? String(normalized.mission_id) : normalized.mission_id;
      }
      return normalized;
    });
  } catch (err) {
    console.error('No se pudieron obtener las misiones disponibles.', err);
    return [];
  }
}

async function fetchMissionById(missionId, token) {
  const missionKey = typeof missionId === 'string' ? missionId.trim() : '';
  if (!missionKey) {
    return null;
  }
  const headers = token
    ? {
        Authorization: `Bearer ${token}`,
      }
    : {};
  const url = `/api/missions/${encodeURIComponent(missionKey)}`;
  try {
    const res = await apiFetch(url, {
      credentials: 'include',
      headers,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (!res.ok) {
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      throw new Error(backendMessage || 'No pudimos obtener la información de la misión.');
    }
    const mission = data.mission;
    if (!mission || typeof mission !== 'object') {
      return null;
    }
    if (Object.prototype.hasOwnProperty.call(mission, 'mission_id')) {
      const value = mission.mission_id;
      mission.mission_id = value != null ? String(value) : value;
    }
    return mission;
  } catch (err) {
    console.error(`No se pudo obtener la misión ${missionKey}.`, err);
    return null;
  }
}

function calculateUnlockedMissions(missionsForRole, completed) {
  const unlocked = {};
  if (!Array.isArray(missionsForRole) || missionsForRole.length === 0) {
    return unlocked;
  }
  const completedSet = new Set(
    (Array.isArray(completed) ? completed : []).map((missionId) => (missionId != null ? String(missionId) : missionId))
  );
  const firstMissionId =
    missionsForRole[0] && missionsForRole[0].mission_id != null
      ? String(missionsForRole[0].mission_id)
      : '';
  if (firstMissionId) {
    unlocked[firstMissionId] = true;
  }
  missionsForRole.forEach((mission, index) => {
    if (!mission || mission.mission_id == null) {
      return;
    }
    const missionId = String(mission.mission_id);
    if (completedSet.has(missionId)) {
      unlocked[missionId] = true;
      const nextMission = missionsForRole[index + 1];
      if (nextMission && nextMission.mission_id != null) {
        unlocked[String(nextMission.mission_id)] = true;
      }
    }
  });
  return unlocked;
}

function setCurrentMission(missionId) {
  if (missionId) {
    localStorage.setItem(STORAGE_KEYS.mission, missionId);
    return;
  }
  localStorage.removeItem(STORAGE_KEYS.mission);
}

function getCurrentMission() {
  return localStorage.getItem(STORAGE_KEYS.mission);
}

function clearCurrentMission() {
  localStorage.removeItem(STORAGE_KEYS.mission);
}

function getStoredSlug() {
  return localStorage.getItem(STORAGE_KEYS.slug);
}

function getStoredToken() {
  return localStorage.getItem(STORAGE_KEYS.token);
}

function getStoredIsAdmin() {
  const value = localStorage.getItem(STORAGE_KEYS.admin);
  if (value === null || typeof value === 'undefined') {
    return null;
  }
  return _normalizeBooleanFlag(value);
}

function $(selector) {
  return document.querySelector(selector);
}

function escapeHtml(value) {
  if (value === null || typeof value === 'undefined') {
    return '';
  }
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Obtiene o crea el contenedor donde se dibuja el contenido principal.
 * Permite usar el flujo de matrícula en cualquier archivo HTML.
 */
function getContentContainer() {
  let content = $('#content');
  if (content) {
    return content;
  }
  const main = document.querySelector('main');
  if (main) {
    main.id = 'content';
    return main;
  }
  content = document.createElement('div');
  content.id = 'content';
  document.body.appendChild(content);
  return content;
}

function renderLandingContent() {
  cacheLandingContent();
  if (!landingContentHTML) {
    if (typeof window !== 'undefined' && window.location) {
      const target = 'index.html';
      if (typeof window.location.assign === 'function') {
        window.location.assign(target);
      } else {
        window.location.href = target;
      }
    }
    return;
  }
  const content = getContentContainer();
  content.innerHTML = landingContentHTML;
  updateMissionAdminLink(false);
}

/**
 * Renderiza el formulario de matrícula.
 */
function renderEnrollForm() {
  const content = getContentContainer();
  const missionId = getCurrentMission();
  let missionNotice = '';
  if (missionId) {
    const safeMissionId = missionId.replace(/[^a-z0-9_-]/gi, '').toUpperCase();
    if (safeMissionId) {
      missionNotice = `<p class="enroll__current-mission">Estás iniciando tu matrícula desde la misión <strong>${safeMissionId}</strong>.</p>`;
    }
  }
  clearCurrentMission();
  content.innerHTML = `
    <section class="enroll">
      <h2>Matrícula</h2>
      ${missionNotice}
      <p>Ingresa tus datos para comenzar.</p>
      <form id="enrollForm">
        <label>Nombre:<br /><input type="text" id="name" required /></label><br />
        <label>Correo electrónico:<br /><input type="email" id="email" required /></label><br />
        <label>Contraseña:<br /><input type="password" id="password" required /></label><br />
        <label>Slug (sin espacios, ej: juan-perez):<br /><input type="text" id="slug" required /></label><br />
        <label>Rol:<br />
          <select id="role" required>
            <option value="Ventas">Ventas</option>
            <option value="Operaciones">Operaciones</option>
          </select>
        </label><br />
        <label>Ruta de tu carpeta de trabajo (workdir):<br /><input type="text" id="workdir" required /></label><br />
        <button type="submit">Matricularme</button>
      </form>
      <div id="enrollMsg" class="msg"></div>
    </section>
  `;
  $('#enrollForm').onsubmit = async (e) => {
    e.preventDefault();
    const name = $('#name').value.trim();
    const email = $('#email').value.trim();
    const password = $('#password').value;
    const slug = $('#slug').value.trim();
    const role = $('#role').value;
    const workdir = $('#workdir').value.trim();
    if (!name || !email || !password || !slug || !role || !workdir) {
      $('#enrollMsg').textContent = 'Todos los campos son obligatorios.';
      return;
    }
    try {
      const res = await apiFetch('/api/enroll', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, email, password, slug, role, workdir }),
      });
      const data = await res.json();
      if (res.ok) {
        let sessionToken = '';
        let loginStudent = null;
        try {
          const loginRes = await apiFetch('/api/login', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ slug, password }),
          });
          if (loginRes.ok) {
            const loginData = await loginRes.json();
            if (loginData && loginData.authenticated && loginData.token) {
              sessionToken = loginData.token;
              loginStudent = loginData.student || null;
            }
          }
        } catch (loginErr) {
          console.warn('No se pudo iniciar sesión automáticamente tras la matrícula.', loginErr);
        }
        if (sessionToken) {
          const canonicalSlug =
            loginStudent && loginStudent.slug ? loginStudent.slug : slug;
          const isAdminFlag = loginStudent ? loginStudent.is_admin : false;
          storeSession(canonicalSlug, sessionToken, isAdminFlag);
          $('#enrollMsg').textContent = '¡Matrícula exitosa! Redirigiendo...';
          setTimeout(() => {
            loadDashboard();
          }, 1000);
        } else {
          clearSession();
          $('#enrollMsg').textContent = '¡Matrícula exitosa! Ahora ingresa con tu contraseña.';
          setTimeout(() => {
            renderLoginForm();
          }, 1200);
        }
      } else {
        $('#enrollMsg').textContent = data.error || 'Error en la matrícula.';
      }
    } catch (err) {
      $('#enrollMsg').textContent = 'Error de conexión.';
    }
  };
}

/**
 * Renderiza el formulario para ingresar con un slug existente.
 */
function renderLoginForm() {
  const content = getContentContainer();
  content.innerHTML = `
    <section class="login">
      <h2>Ingresar</h2>
      <p>Ingresa tu slug y contraseña para acceder al portal.</p>
      <form id="loginForm">
        <label>Selecciona tu usuario:<br />
          <select id="studentSelect">
            <option value="">Cargando estudiantes...</option>
          </select>
        </label><br />
        <label>Slug:<br /><input type="text" id="loginSlug" required /></label><br />
        <label>Contraseña:<br /><input type="password" id="loginPassword" required /></label><br />
        <button type="submit">Ingresar</button>
        <button type="button" id="registerBtn">Registrarse</button>
      </form>
      <div id="loginMsg" class="msg"></div>
    </section>
  `;
  updateMissionAdminLink(false);
  const loginForm = $('#loginForm');
  if (!loginForm) {
    return;
  }
  const slugInput = $('#loginSlug');
  const passwordInput = $('#loginPassword');
  const msg = $('#loginMsg');
  const studentSelect = $('#studentSelect');
  const registerBtn = $('#registerBtn');

  const attemptLogin = async () => {
    if (!slugInput || !msg) {
      return;
    }
    const slug = (slugInput.value || '').trim();
    const password = passwordInput ? passwordInput.value : '';
    if (!slug) {
      msg.textContent = 'Debes ingresar tu slug.';
      return;
    }
    if (!password) {
      msg.textContent = 'Debes ingresar tu contraseña.';
      return;
    }
    slugInput.value = slug;
    msg.textContent = 'Verificando tus datos...';
    try {
      const res = await apiFetch('/api/login', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ slug, password }),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (parseErr) {
        data = {};
      }
      const authenticated = Boolean(data && data.authenticated);
      if (res.ok && authenticated) {
        const confirmedSlug =
          data && data.student && data.student.slug
            ? data.student.slug
            : slug;
        const sessionToken = data && data.token ? data.token : '';
        const isAdminFlag = data && data.student ? data.student.is_admin : false;
        storeSession(confirmedSlug, sessionToken, isAdminFlag);
        msg.textContent = 'Ingreso exitoso. Cargando tu portal...';
        loadDashboard();
        return;
      }
      clearSession();
      if (passwordInput) {
        passwordInput.value = '';
      }
      const backendError = data && typeof data.error === 'string' ? data.error.trim() : '';
      msg.textContent = backendError || 'Credenciales incorrectas. Verifica tus datos.';
    } catch (err) {
      msg.textContent = 'Error de conexión. Intenta nuevamente.';
    }
  };

  loginForm.onsubmit = async (e) => {
    e.preventDefault();
    await attemptLogin();
  };

  if (registerBtn) {
    registerBtn.onclick = (event) => {
      event.preventDefault();
      clearSession();
      renderEnrollForm();
    };
  }

  if (studentSelect) {
    studentSelect.disabled = true;
    studentSelect.onchange = () => {
      const selectedSlug = studentSelect.value;
      if (!selectedSlug) {
        if (slugInput) {
          slugInput.value = '';
        }
        return;
      }
      if (slugInput) {
        slugInput.value = selectedSlug;
      }
      if (passwordInput) {
        passwordInput.focus();
      }
    };
    (async () => {
      try {
        const res = await apiFetch('/api/students', {
          credentials: 'include',
        });
        if (!res.ok) {
          throw new Error('Failed to load students');
        }
        const data = await res.json();
        const students = Array.isArray(data.students) ? data.students : [];
        if (students.length === 0) {
          studentSelect.innerHTML = '<option value="">No hay estudiantes registrados.</option>';
          studentSelect.disabled = true;
          return;
        }
        studentSelect.innerHTML = '<option value="">Selecciona tu usuario</option>';
        students.forEach((student) => {
          if (!student || !student.slug || !student.name) {
            return;
          }
          const option = document.createElement('option');
          option.value = student.slug;
          option.textContent = student.name;
          studentSelect.appendChild(option);
        });
        studentSelect.disabled = false;
      } catch (err) {
        studentSelect.innerHTML = '<option value="">No pudimos cargar los estudiantes.</option>';
        studentSelect.disabled = true;
      }
    })();
  }
}

/**
 * Carga el tablero de misiones según el estudiante.
 */
async function loadDashboard() {
  const slug = getStoredSlug();
  const token = getStoredToken();
  const initialSlug = slug;
  if (!slug || !token) {
    clearSession();
    renderLoginForm();
    return;
  }
  const content = $('#content');
  content.innerHTML = '<p>Cargando tu información...</p>';
  try {
    const headers = token
      ? {
          Authorization: `Bearer ${token}`,
        }
      : {};
    const statusUrl = `/api/status?${new URLSearchParams({ slug })}`;
    const res = await apiFetch(statusUrl, {
      credentials: 'include',
      headers,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    const backendMessage = typeof data.error === 'string' ? data.error : '';
    const studentNotFound =
      res.status === 404 && backendMessage.toLowerCase().includes('student not found');
    if (!res.ok) {
      if (res.status === 401) {
        clearSession();
        content.innerHTML = `
          <section class="status-error">
            <p>Tu sesión expiró o no es válida. Vuelve a iniciar sesión para continuar.</p>
            <button id="loginAgainBtn">Iniciar sesión</button>
          </section>
        `;
        const loginAgainBtn = $('#loginAgainBtn');
        if (loginAgainBtn) {
          loginAgainBtn.onclick = () => {
            renderLoginForm();
          };
        }
        return;
      }
      if (studentNotFound) {
        clearSession();
        content.innerHTML = `
          <section class="status-error">
            <p>No encontramos tu matrícula. Vuelve a matricularte para continuar.</p>
            <button id="retryEnrollBtn">Matricularme de nuevo</button>
          </section>
        `;
        const retryEnrollBtn = $('#retryEnrollBtn');
        if (retryEnrollBtn) {
          retryEnrollBtn.onclick = () => {
            renderEnrollForm();
          };
        }
        return;
      }
      const errorMessage = backendMessage || 'No pudimos obtener tu información en este momento.';
      content.innerHTML = `
        <section class="status-error">
          <p>${errorMessage}</p>
          <button id="retryStatusBtn">Reintentar</button>
        </section>
      `;
      const retryBtn = $('#retryStatusBtn');
      if (retryBtn) {
        retryBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    const student = data.student;
    const completed = data.completed || [];
    const missions = await fetchMissionsForRole(student ? student.role : '', token);
    const currentSlug = getStoredSlug();
    if (!currentSlug || currentSlug !== initialSlug) {
      return;
    }
    const canonicalSlug = student && student.slug ? student.slug : slug;
    const isAdminFlag =
      student && Object.prototype.hasOwnProperty.call(student, 'is_admin')
        ? student.is_admin
        : undefined;
    if (canonicalSlug && canonicalSlug !== currentSlug) {
      storeSession(canonicalSlug, token, isAdminFlag);
    } else if (typeof isAdminFlag !== 'undefined') {
      storeSession(currentSlug, token, isAdminFlag);
    }
    renderDashboard(student, missions, completed);
  } catch (err) {
    content.innerHTML = `
      <section class="status-error">
        <p>No pudimos comunicarnos con el servidor. Por favor verifica tu conexión e intenta nuevamente.</p>
        <button id="retryStatusBtn">Reintentar</button>
      </section>
    `;
    const retryBtn = $('#retryStatusBtn');
    if (retryBtn) {
      retryBtn.onclick = () => {
        loadDashboard();
      };
    }
  }
}

/**
 * Renderiza el dashboard con las misiones disponibles.
 * @param {Object} student
 * @param {Object[]} missions
 * @param {string[]} completed
 */
function renderDashboard(student, missions, completed) {
  const content = $('#content');
  const studentRole = student && typeof student.role === 'string' ? student.role : '';
  const normalizeRoleValue = (value) => {
    if (value == null) {
      return '';
    }
    if (typeof value === 'string') {
      return value.trim().toLowerCase();
    }
    return String(value).trim().toLowerCase();
  };
  const normalizedStudentRole = normalizeRoleValue(studentRole);
  const universalTokens = new Set(['*', 'all', 'todos', 'todas']);
  const missionsArray = Array.isArray(missions) ? missions : [];
  const missionsForRole = missionsArray.filter((mission) => {
    if (!mission || mission.mission_id == null) {
      return false;
    }
    const missionRolesRaw = Array.isArray(mission.roles) ? mission.roles : [];
    const missionRoles = missionRolesRaw
      .map((role) => normalizeRoleValue(role))
      .filter((role) => role);
    if (missionRoles.length === 0) {
      return true;
    }
    if (missionRoles.some((role) => universalTokens.has(role))) {
      return true;
    }
    if (!normalizedStudentRole) {
      return false;
    }
    return missionRoles.includes(normalizedStudentRole);
  });
  const unlocked = calculateUnlockedMissions(missionsForRole, completed);
  const completedSet = new Set(
    (Array.isArray(completed) ? completed : []).map((missionId) => (missionId != null ? String(missionId) : missionId))
  );
  const isAdmin = _normalizeBooleanFlag(
    student && Object.prototype.hasOwnProperty.call(student, 'is_admin')
      ? student.is_admin
      : getStoredIsAdmin()
  );
  let html = `<section class="dashboard">
    <h2>Bienvenido, ${student.name}</h2>
    <p>Rol: ${student.role}</p>
    <p>Selecciona una misión para continuar:</p>
    <ul class="missions-grid">`;
  if (missionsForRole.length === 0) {
    html += '<li class="mission-card empty">No hay misiones disponibles para tu rol en este momento.</li>';
  }
  missionsForRole.forEach((mission) => {
    if (!mission || mission.mission_id == null) {
      return;
    }
    const missionId = String(mission.mission_id);
    const missionTitle = mission.title || missionId;
    const missionSummary =
      mission && mission.content && typeof mission.content === 'object' && mission.content.summary
        ? mission.content.summary
        : '';
    const summaryHtml = missionSummary
      ? `<p class="mission-summary">${missionSummary}</p>`
      : '';
    const isCompleted = completedSet.has(missionId);
    const isUnlocked = unlocked[missionId] || false;
    let statusClass = '';
    let statusText = '';
    if (isCompleted) {
      statusClass = 'completed';
      statusText = 'Completada';
    } else if (isUnlocked) {
      statusClass = 'unlocked';
      statusText = 'Disponible';
    } else {
      statusClass = 'locked';
      statusText = 'Bloqueada';
    }
    if (isUnlocked) {
      html += `<li class="mission-card ${statusClass}"><a href="${missionId}.html">${missionTitle}</a>${summaryHtml}<span class="status">${statusText}</span></li>`;
    } else {
      html += `<li class="mission-card ${statusClass}">${missionTitle}${summaryHtml}<span class="status">${statusText}</span></li>`;
    }
  });
  html += '</ul>';
  html += '<div class="dashboard-actions">';
  html += '<button id="logoutBtn">Salir</button>';
  html += '</div>';
  html += '</section>';
  content.innerHTML = html;
  updateMissionAdminLink(isAdmin);
  $('#logoutBtn').onclick = () => {
    clearSession();
    renderLandingContent();
  };
}

function _getAdminSessionContext() {
  const slug = getStoredSlug();
  const token = getStoredToken();
  const isAdmin = getStoredIsAdmin();
  if (!slug || !token || !_normalizeBooleanFlag(isAdmin)) {
    return null;
  }
  return { slug, token };
}

function renderAdminModule(defaultSection = 'missions') {
  const session = _getAdminSessionContext();
  if (!session) {
    clearSession();
    renderLoginForm();
    return;
  }
  const content = getContentContainer();
  content.innerHTML = `
    <section class="admin-module">
      <div class="admin-module__header">
        <h2 class="admin-module__title">Panel administrativo</h2>
        <div class="admin-module__actions">
          <button type="button" class="admin-button admin-button--ghost" data-action="admin-back-dashboard">
            Volver al dashboard
          </button>
        </div>
      </div>
      <div class="admin-module__layout">
        <nav class="admin-module__nav" aria-label="Secciones administrativas">
          <button type="button" class="admin-module__nav-btn" data-section="missions">Misiones</button>
          <button type="button" class="admin-module__nav-btn" data-section="users">Usuarios</button>
          <button type="button" class="admin-module__nav-btn" data-section="roles">Roles</button>
          <button type="button" class="admin-module__nav-btn" data-section="integrations">Integraciones</button>
        </nav>
        <div class="admin-module__content">
          <div class="admin-module__section" data-active-section=""></div>
        </div>
      </div>
    </section>
  `;
  const backButton = content.querySelector('[data-action="admin-back-dashboard"]');
  if (backButton) {
    backButton.onclick = () => {
      const storedSlug = getStoredSlug();
      const storedToken = getStoredToken();
      const storedAdmin = getStoredIsAdmin();
      if (storedSlug) {
        storeSession(storedSlug, storedToken, storedAdmin);
      }
      loadDashboard();
    };
  }
  const navButtons = Array.from(content.querySelectorAll('.admin-module__nav-btn'));
  const sectionContainer = content.querySelector('.admin-module__section');
  let currentSection = '';
  let rolesCache = null;
  let integrationsFeedback = null;
  const moduleState = {
    session,
    async loadRoles(force = false) {
      if (!force && Array.isArray(rolesCache)) {
        return rolesCache;
      }
      const response = await apiFetch('/api/admin/roles', {
        credentials: 'include',
        headers: {
          Authorization: `Bearer ${session.token}`,
        },
      });
      let data = {};
      try {
        data = await response.json();
      } catch (parseError) {
        data = {};
      }
      if (!response.ok) {
        const backendMessage = typeof data.error === 'string' ? data.error : '';
        const error = new Error(backendMessage || 'No fue posible obtener el catálogo de roles.');
        error.status = response.status;
        error.payload = data;
        throw error;
      }
      const roles = Array.isArray(data.roles) ? data.roles : [];
      rolesCache = roles;
      return roles;
    },
    invalidateRoles() {
      rolesCache = null;
    },
    refreshCurrentSection() {
      if (currentSection) {
        showSection(currentSection, { force: true });
      }
    },
    setIntegrationsFeedback(feedback) {
      integrationsFeedback = feedback || null;
    },
    consumeIntegrationsFeedback() {
      const feedback = integrationsFeedback;
      integrationsFeedback = null;
      return feedback;
    },
  };
  async function showSection(sectionName, { force = false } = {}) {
    if (!sectionContainer) {
      return;
    }
    if (!force && currentSection === sectionName) {
      return;
    }
    currentSection = sectionName;
    sectionContainer.dataset.activeSection = sectionName;
    navButtons.forEach((btn) => {
      const isActive = btn.dataset.section === sectionName;
      btn.classList.toggle('is-active', isActive);
      if (isActive) {
        btn.setAttribute('aria-current', 'page');
      } else {
        btn.removeAttribute('aria-current');
      }
    });
    sectionContainer.innerHTML =
      '<div class="admin-module__status admin-module__status--loading"><p>Cargando sección...</p></div>';
    try {
      if (sectionName === 'missions') {
        await renderAdminMissionsSection(sectionContainer, moduleState);
      } else if (sectionName === 'users') {
        await renderAdminUsersSection(sectionContainer, moduleState);
      } else if (sectionName === 'roles') {
        await renderAdminRolesSection(sectionContainer, moduleState);
      } else if (sectionName === 'integrations') {
        await renderAdminIntegrationsSection(sectionContainer, moduleState);
      } else if (sectionContainer.dataset.activeSection === sectionName) {
        sectionContainer.innerHTML =
          '<div class="status-error"><p>Sección desconocida.</p></div>';
      }
    } catch (err) {
      if (sectionContainer.dataset.activeSection !== sectionName) {
        return;
      }
      const message = err && err.message ? err.message : 'No fue posible cargar la sección seleccionada.';
      sectionContainer.innerHTML = `<div class="status-error"><p>${escapeHtml(message)}</p></div>`;
    }
  }
  navButtons.forEach((btn) => {
    btn.onclick = () => {
      const target = btn.dataset.section || 'missions';
      showSection(target);
    };
  });
  const initialSection = resolvePreferredAdminSection(defaultSection);
  showSection(initialSection);
}

async function renderAdminMissionsSection(sectionContainer, moduleState) {
  if (!sectionContainer) {
    return;
  }
  const sectionKey = 'missions';
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  sectionContainer.innerHTML =
    '<div class="admin-module__status admin-module__status--loading"><p>Cargando misiones disponibles...</p></div>';
  const { token } = moduleState.session;
  let missions = [];
  try {
    const res = await apiFetch('/api/admin/missions', {
      credentials: 'include',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    if (res.status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    if (res.status === 403) {
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>No tienes permisos para configurar misiones.</p>
          <button type="button" class="admin-button" data-action="admin-back">Volver</button>
        </div>
      `;
      const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
      if (backBtn) {
        backBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    if (!res.ok) {
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      throw new Error(backendMessage || 'No fue posible obtener la lista de misiones.');
    }
    missions = Array.isArray(data.missions) ? data.missions : [];
  } catch (err) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const message = err && err.message ? err.message : 'Ocurrió un error al cargar las misiones.';
    sectionContainer.innerHTML = `
      <div class="status-error">
        <p>${escapeHtml(message)}</p>
        <button type="button" class="admin-button admin-button--ghost" data-action="retry-missions">Reintentar</button>
      </div>
    `;
    const retryBtn = sectionContainer.querySelector('[data-action="retry-missions"]');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderAdminMissionsSection(sectionContainer, moduleState);
      };
    }
    return;
  }
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  let rolesLoadWarning = '';
  let useFallbackRoles = false;
  let roleOptions = [];
  try {
    const catalogRoles = await moduleState.loadRoles();
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    roleOptions = catalogRoles
      .map((role) => {
        const slug = role && role.slug ? String(role.slug) : '';
        if (!slug) {
          return null;
        }
        const name = role && role.name ? String(role.name) : slug;
        return { slug, name };
      })
      .filter(Boolean)
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch (rolesError) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const status = rolesError && rolesError.status;
    if (status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    useFallbackRoles = true;
    if (status === 403) {
      rolesLoadWarning =
        'No tienes permisos para consultar el catálogo de roles. Se mostrarán los roles detectados en las misiones disponibles.';
    } else {
      const backendMessage = rolesError && rolesError.message ? rolesError.message : '';
      rolesLoadWarning =
        (backendMessage || 'No fue posible obtener el catálogo de roles.') +
        ' Se mostrarán los roles detectados en las misiones disponibles.';
    }
  }
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  if (useFallbackRoles) {
    const roleOptionsSet = new Set(ADMIN_AVAILABLE_ROLES);
    missions.forEach((mission) => {
      const missionRoles = Array.isArray(mission && mission.roles) ? mission.roles : [];
      missionRoles.forEach((role) => {
        if (role && typeof role === 'string') {
          roleOptionsSet.add(role);
        }
      });
    });
    roleOptions = Array.from(roleOptionsSet)
      .filter((role) => typeof role === 'string' && role)
      .sort((a, b) => a.localeCompare(b))
      .map((role) => ({ slug: role, name: role }));
    if (!rolesLoadWarning) {
      rolesLoadWarning =
        'No fue posible obtener el catálogo de roles. Se mostrarán los roles detectados en las misiones disponibles.';
    }
  }
  const missionOptions = missions
    .map((mission) => {
      const missionId = mission && mission.mission_id != null ? String(mission.mission_id) : '';
      if (!missionId) {
        return '';
      }
      return `<option value="${escapeHtml(missionId)}">${escapeHtml(missionId)}</option>`;
    })
    .join('');
  const rolesCheckboxes = roleOptions
    .map(
      (role) =>
        `<label class="admin-checkbox"><input type="checkbox" class="mission-role-option" value="${escapeHtml(
          role.slug
        )}"> <span>${escapeHtml(role.name)}</span></label>`
    )
    .join('');
  sectionContainer.innerHTML = `
    <div class="admin-section admin-section--missions">
      <div class="admin-section__header">
        <div>
          <h3 class="admin-section__title">Misiones</h3>
          <p class="admin-section__description">Selecciona una misión para editar su título, roles y contenido.</p>
        </div>
        <div class="admin-section__actions">
          <button type="button" class="admin-button admin-button--ghost" data-action="refresh-missions">Actualizar lista</button>
          <button type="button" class="admin-button" data-action="new-mission">Nueva misión</button>
        </div>
      </div>
      ${rolesLoadWarning ? `<div class="status-warning"><p>${escapeHtml(rolesLoadWarning)}</p></div>` : ''}
      <div class="admin-section__grid admin-section__grid--two-columns">
        <div class="admin-card admin-card--selector">
          <label class="admin-field" for="missionAdminSelect">
            <span class="admin-field__label">Misiones disponibles</span>
            <select id="missionAdminSelect" class="admin-field__control">
              <option value="">Selecciona una misión</option>
              ${missionOptions}
            </select>
          </label>
        </div>
        <form id="missionAdminForm" class="admin-card admin-card--form">
          <div class="admin-field" id="missionIdField" hidden>
            <label class="admin-field__label" for="missionIdInput">Identificador</label>
            <input type="text" id="missionIdInput" class="admin-field__control" name="mission_id">
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="missionTitleInput">Título</label>
            <input type="text" id="missionTitleInput" class="admin-field__control" name="title">
          </div>
          <fieldset class="admin-field admin-field--fieldset">
            <legend>Roles disponibles</legend>
            <div class="admin-checkbox-grid">
              ${rolesCheckboxes}
            </div>
          </fieldset>
          <div class="admin-field">
            <label class="admin-field__label" for="missionVerificationType">Tipo de verificación</label>
            <select id="missionVerificationType" class="admin-field__control" name="verification_type">
              ${buildAdminVerificationTypeOptions()}
            </select>
          </div>
          <fieldset class="admin-field admin-field--fieldset">
            <legend>Repositorio de origen</legend>
            <div class="admin-field">
              <label class="admin-field__label" for="missionSourceRepositoryInput">Repositorio</label>
              <input type="text" id="missionSourceRepositoryInput" class="admin-field__control" placeholder="default" name="source_repository">
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionSourceBranchInput">Rama predeterminada</label>
              <input type="text" id="missionSourceBranchInput" class="admin-field__control" placeholder="main" name="source_branch">
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionSourceBasePathInput">Base path</label>
              <input type="text" id="missionSourceBasePathInput" class="admin-field__control" placeholder="students/{slug}" name="source_base_path">
            </div>
          </fieldset>
          <fieldset class="admin-field admin-field--fieldset">
            <legend>Campos extra</legend>
            <p class="admin-field__hint">
              Completa cada bloque numerado para seguir el estándar de documentación de misiones.
            </p>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraPurpose">1. Nombre y narrativa</label>
              <textarea
                id="missionExtraPurpose"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="purpose"
                placeholder="Presenta la misión y el escenario principal."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraOutcome">2. Objetivos de la misión</label>
              <textarea
                id="missionExtraOutcome"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="outcome"
                placeholder="Enumera los objetivos medibles que la persona deberá lograr."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraHistory">3. Historia / contexto breve</label>
              <textarea
                id="missionExtraHistory"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="history"
                placeholder="Describe el contexto narrativo que introduce la misión."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraResources">4. Recursos de aprendizaje sugeridos</label>
              <textarea
                id="missionExtraResources"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="resources"
                placeholder="Incluye enlaces y materiales recomendados para prepararse."
              ></textarea>
            </div>
            <fieldset class="admin-field admin-field--fieldset">
              <legend>5. Práctica — Contrato</legend>
              <div class="admin-field">
                <label class="admin-field__label" for="missionExtraPracticeEntry">Entrada</label>
                <textarea
                  id="missionExtraPracticeEntry"
                  class="admin-field__control admin-field__control--textarea"
                  rows="3"
                  data-mission-extra="practice_contract_entry"
                  placeholder="Describe cómo se presenta la práctica y qué información recibe la persona."
                ></textarea>
              </div>
              <div class="admin-field">
                <label class="admin-field__label" for="missionExtraPracticeSteps">Pasos a realizar</label>
                <textarea
                  id="missionExtraPracticeSteps"
                  class="admin-field__control admin-field__control--textarea"
                  rows="3"
                  data-mission-extra="practice_contract_steps"
                  placeholder="Detalla las acciones concretas que deberá ejecutar la persona."
                ></textarea>
              </div>
              <div class="admin-field">
                <label class="admin-field__label" for="missionExtraPracticeExpected">Logro esperado</label>
                <textarea
                  id="missionExtraPracticeExpected"
                  class="admin-field__control admin-field__control--textarea"
                  rows="3"
                  data-mission-extra="practice_contract_expected"
                  placeholder="Describe el resultado o criterio de éxito al finalizar la práctica."
                ></textarea>
              </div>
              <div class="admin-field">
                <label class="admin-field__label" for="missionExtraPracticeOutputs">Archivos de salida</label>
                <textarea
                  id="missionExtraPracticeOutputs"
                  class="admin-field__control admin-field__control--textarea"
                  rows="3"
                  data-mission-extra="practice_contract_outputs"
                  placeholder="Enumera los archivos o artefactos que se deberán entregar."
                ></textarea>
              </div>
            </fieldset>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraResearch">6. Investigación previa (fichas)</label>
              <textarea
                id="missionExtraResearch"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="research"
                placeholder="Resume la investigación previa que respalda la misión."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraMicroQuiz">7. Micro-quiz</label>
              <textarea
                id="missionExtraMicroQuiz"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="micro_quiz"
                placeholder="Redacta preguntas y respuestas. Entrega en reports/m#_quiz.txt."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraPrChecklist">8. Checklist para el Pull Request</label>
              <textarea
                id="missionExtraPrChecklist"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="pr_checklist"
                placeholder="Define la lista de verificación. Entrega en reports/m#_pr_checklist.md."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraDeliverables">9. Entregables obligatorios</label>
              <textarea
                id="missionExtraDeliverables"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="deliverables"
                placeholder="Describe los entregables que debe entregar la persona."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraEvaluationRubric">10. Rúbrica de evaluación (10 puntos)</label>
              <textarea
                id="missionExtraEvaluationRubric"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="evaluation_rubric"
                placeholder="Explica los criterios de evaluación y asigna puntos (reports/m#_rubric.md)."
              ></textarea>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="missionExtraReview">11. Revisión final</label>
              <textarea
                id="missionExtraReview"
                class="admin-field__control admin-field__control--textarea"
                rows="3"
                data-mission-extra="review"
                placeholder="Detalla el proceso de revisión y los siguientes pasos."
              ></textarea>
            </div>
            <div class="admin-field admin-field--details">
              <details id="missionExtrasAdvancedDetails">
                <summary>Editor avanzado</summary>
                <p class="admin-field__hint">
                  Edita el JSON que se fusionará con el contenido de la misión. Usa esta sección para conservar claves avanzadas como
                  rutas de scripts o validaciones.
                </p>
                <div class="admin-field">
                  <label class="admin-field__label" for="missionExtrasEditor">Contenido adicional (JSON)</label>
                  <textarea
                    id="missionExtrasEditor"
                    class="admin-field__control admin-field__control--textarea"
                    rows="8"
                    spellcheck="false"
                    placeholder="{}"
                  ></textarea>
                </div>
                <div class="admin-feedback admin-feedback--field" id="missionExtrasFeedback"></div>
              </details>
            </div>
          </fieldset>
          <fieldset class="admin-field admin-field--fieldset">
            <legend>Deliverables</legend>
            <p class="admin-field__hint">Administra la lista de entregables requeridos.</p>
            <div id="missionDeliverablesList" class="admin-deliverables-list"></div>
            <button type="button" class="admin-button admin-button--ghost" data-action="add-deliverable">Agregar deliverable</button>
            <datalist id="missionDeliverableTypeOptions">
              <option value="file_exists">
              <option value="file_contains">
            </datalist>
            <div id="missionDeliverablesSummary" class="admin-deliverables-summary"></div>
          </fieldset>
          <div id="missionAdminFeedback" class="admin-feedback"></div>
          <div class="admin-form__actions">
            <button type="submit" class="admin-button" id="missionAdminSaveBtn">Guardar cambios</button>
          </div>
        </form>
      </div>
    </div>
  `;
  const refreshBtn = sectionContainer.querySelector('[data-action="refresh-missions"]');
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      renderAdminMissionsSection(sectionContainer, moduleState);
    };
  }
  const missionSelect = sectionContainer.querySelector('#missionAdminSelect');
  const missionIdField = sectionContainer.querySelector('#missionIdField');
  const missionIdInput = sectionContainer.querySelector('#missionIdInput');
  const missionTitleInput = sectionContainer.querySelector('#missionTitleInput');
  const missionVerificationSelect = sectionContainer.querySelector('#missionVerificationType');
  const missionSourceRepositoryInput = sectionContainer.querySelector('#missionSourceRepositoryInput');
  const missionSourceBranchInput = sectionContainer.querySelector('#missionSourceBranchInput');
  const missionSourceBasePathInput = sectionContainer.querySelector('#missionSourceBasePathInput');
  const missionExtrasEditor = sectionContainer.querySelector('#missionExtrasEditor');
  const missionExtrasFeedback = sectionContainer.querySelector('#missionExtrasFeedback');
  const missionExtrasAdvancedDetails = sectionContainer.querySelector('#missionExtrasAdvancedDetails');
  const missionExtraSectionDefinitions = [
    { key: 'purpose', heading: '1. Nombre y narrativa', legacyHeadings: ['💡 ¿Para qué sirve?'] },
    { key: 'outcome', heading: '2. Objetivos de la misión', legacyHeadings: ['🏆 Al final podrás…'] },
    { key: 'history', heading: '3. Historia / contexto breve' },
    {
      key: 'resources',
      heading: '4. Recursos de aprendizaje sugeridos',
      legacyHeadings: ['📚 Material de aprendizaje sugerido…'],
    },
    {
      key: 'practice_contract',
      heading: '5. Práctica — Contrato',
      type: 'group',
      subheadingTag: 'h4',
      subfields: [
        {
          key: 'practice_contract_entry',
          heading: 'Entrada',
          legacyHeadings: ['6. Guía previa a la práctica', '🧭 Guía detallada antes de la práctica'],
        },
        {
          key: 'practice_contract_steps',
          heading: 'Pasos a realizar',
          legacyHeadings: ['7. Setup del repositorio y entorno', '📦 Clonar el repositorio…'],
        },
        {
          key: 'practice_contract_expected',
          heading: 'Logro esperado',
          legacyHeadings: ['9. Práctica principal', '🚀 Práctica…'],
        },
        {
          key: 'practice_contract_outputs',
          heading: 'Archivos de salida',
        },
      ],
    },
    {
      key: 'research',
      heading: '6. Investigación previa (fichas)',
      legacyHeadings: ['📝 Investigación (Fichas)'],
    },
    { key: 'micro_quiz', heading: '7. Micro-quiz' },
    { key: 'pr_checklist', heading: '8. Checklist para el Pull Request' },
    {
      key: 'deliverables',
      heading: '9. Entregables obligatorios',
      legacyHeadings: ['📋 Entregables obligatorios'],
    },
    { key: 'evaluation_rubric', heading: '10. Rúbrica de evaluación (10 puntos)' },
    { key: 'review', heading: '11. Revisión final', legacyHeadings: ['👁 Revisión'] },
  ];
  const missionExtraFieldDefinitions = missionExtraSectionDefinitions.flatMap((definition) => {
    if (definition.type === 'group' && Array.isArray(definition.subfields)) {
      return definition.subfields.map((subfield) => ({
        ...subfield,
        parentKey: definition.key,
        parentHeading: definition.heading,
        headingTag: (subfield.headingTag || definition.subheadingTag || 'h4').toLowerCase(),
        fullHeading:
          subfield.fullHeading ||
          (definition.heading && subfield.heading
            ? `${definition.heading} — ${subfield.heading}`
            : subfield.heading || definition.heading),
      }));
    }
    return [
      {
        ...definition,
        parentKey: null,
        parentHeading: null,
        headingTag: (definition.headingTag || 'h3').toLowerCase(),
        fullHeading: definition.heading,
      },
    ];
  });
  const missionExtrasFieldNodes = {};
  let missionDisplaySectionValues = {};
  missionExtraFieldDefinitions.forEach((definition) => {
    const field = sectionContainer.querySelector(`[data-mission-extra="${definition.key}"]`);
    if (field) {
      missionExtrasFieldNodes[definition.key] = field;
      field.addEventListener('input', () => {
        missionDisplaySectionValues[definition.key] = field.value;
        if (field.value.trim()) {
          field.removeAttribute('aria-invalid');
        }
      });
    }
  });
  missionDisplaySectionValues = createEmptyMissionDisplaySections();
  resetMissionSectionFieldValues();
  const deliverablesList = sectionContainer.querySelector('#missionDeliverablesList');
  const deliverablesSummary = sectionContainer.querySelector('#missionDeliverablesSummary');
  const addDeliverableButton = sectionContainer.querySelector('[data-action="add-deliverable"]');
  const feedbackContainer = sectionContainer.querySelector('#missionAdminFeedback');
  const saveButton = sectionContainer.querySelector('#missionAdminSaveBtn');
  const roleInputs = Array.from(sectionContainer.querySelectorAll('.mission-role-option'));
  let isCreatingNewMission = false;
  let missionContentExtras = {};

  function updateMissionExtrasFeedback(message) {
    if (missionExtrasFeedback) {
      missionExtrasFeedback.innerHTML = message
        ? `<div class="status-error"><p>${escapeHtml(message)}</p></div>`
        : '';
    }
    if (missionExtrasEditor) {
      if (message) {
        missionExtrasEditor.setAttribute('aria-invalid', 'true');
      } else {
        missionExtrasEditor.removeAttribute('aria-invalid');
      }
    }
    if (missionExtrasAdvancedDetails && message) {
      missionExtrasAdvancedDetails.setAttribute('open', 'open');
    }
  }

  function serializeMissionExtras(extras) {
    if (!extras || typeof extras !== 'object' || Array.isArray(extras)) {
      return '';
    }
    try {
      return JSON.stringify(extras, null, 2);
    } catch (err) {
      return '';
    }
  }

  function setMissionExtrasEditorValue(extras) {
    if (missionExtrasEditor) {
      const serialized = serializeMissionExtras(extras);
      missionExtrasEditor.value = serialized || '{}';
    }
    updateMissionExtrasFeedback('');
  }

  function syncExtrasFromEditor({ fromSubmit = false } = {}) {
    if (!missionExtrasEditor) {
      return true;
    }
    const rawValue = missionExtrasEditor.value;
    const trimmed = rawValue.trim();
    if (!trimmed) {
      missionContentExtras = {};
      updateMissionExtrasFeedback('');
      resetMissionSectionFieldValues();
      return true;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('El JSON debe representar un objeto con pares clave-valor.');
      }
      missionContentExtras = parsed;
      updateMissionExtrasFeedback('');
      syncMissionSectionFieldsFromExtras(missionContentExtras);
      return true;
    } catch (err) {
      const detail = err && err.message ? ` Detalle: ${err.message}` : '';
      const feedbackMessage = fromSubmit
        ? `El contenido extra no es un JSON válido.${detail}`
        : `JSON inválido.${detail}`;
      updateMissionExtrasFeedback(feedbackMessage);
      return false;
    }
  }

  function createEmptyMissionDisplaySections() {
    const initialValues = {};
    missionExtraFieldDefinitions.forEach((definition) => {
      initialValues[definition.key] = '';
    });
    return initialValues;
  }

  function setMissionSectionFieldValues(values) {
    missionExtraFieldDefinitions.forEach((definition) => {
      const field = missionExtrasFieldNodes[definition.key];
      if (field) {
        const fieldValue = values && typeof values[definition.key] === 'string' ? values[definition.key] : '';
        field.value = fieldValue;
      }
    });
  }

  function setMissionSectionFieldError(fieldKey, hasError) {
    const field = missionExtrasFieldNodes[fieldKey];
    if (!field) {
      return;
    }
    if (hasError) {
      field.setAttribute('aria-invalid', 'true');
    } else {
      field.removeAttribute('aria-invalid');
    }
  }

  function clearMissionSectionFieldErrors() {
    missionExtraFieldDefinitions.forEach((definition) => {
      setMissionSectionFieldError(definition.key, false);
    });
  }

  function resetMissionSectionFieldValues() {
    missionDisplaySectionValues = createEmptyMissionDisplaySections();
    setMissionSectionFieldValues(missionDisplaySectionValues);
    clearMissionSectionFieldErrors();
  }

  function collectMissionSectionFieldValues() {
    const values = createEmptyMissionDisplaySections();
    const missing = [];
    missionExtraFieldDefinitions.forEach((definition) => {
      const field = missionExtrasFieldNodes[definition.key];
      const rawValue = field ? field.value : '';
      values[definition.key] = rawValue;
      const normalized = typeof rawValue === 'string' ? rawValue.trim() : '';
      if (!normalized) {
        missing.push({ ...definition, heading: definition.fullHeading || definition.heading });
        setMissionSectionFieldError(definition.key, true);
      } else {
        setMissionSectionFieldError(definition.key, false);
      }
    });
    return { values, missing };
  }

  function normalizeMissionExtraHeading(text) {
    return typeof text === 'string' ? text.replace(/\s+/g, ' ').trim().toLowerCase() : '';
  }

  function parseMissionExtrasDisplaySections(displayHtml) {
    const parsedValues = createEmptyMissionDisplaySections();
    if (!displayHtml || typeof displayHtml !== 'string') {
      return parsedValues;
    }
    if (typeof document === 'undefined') {
      return parsedValues;
    }
    const container = document.createElement('div');
    container.innerHTML = displayHtml;
    const missionSection = container.querySelector('section.mission');
    const root = missionSection || container;
    const headingElements = Array.from(root.querySelectorAll('h3'));
    const headingMap = new Map();
    headingElements.forEach((element) => {
      const normalized = normalizeMissionExtraHeading(element.textContent);
      if (!normalized) {
        return;
      }
      if (!headingMap.has(normalized)) {
        headingMap.set(normalized, []);
      }
      headingMap.get(normalized).push(element);
    });

    const collectContentUntilNextHeading = (headingElement) => {
      const fragmentContainer = document.createElement('div');
      let sibling = headingElement.nextSibling;
      while (sibling) {
        if (sibling.nodeType === 1 && sibling.tagName) {
          const tagName = sibling.tagName.toLowerCase();
          if (tagName === 'h3') {
            break;
          }
        }
        fragmentContainer.appendChild(sibling.cloneNode(true));
        sibling = sibling.nextSibling;
      }
      return fragmentContainer.innerHTML.trim();
    };

    const extractByHeadings = (candidateHeadings) => {
      for (const headingText of candidateHeadings) {
        const normalized = normalizeMissionExtraHeading(headingText);
        if (!normalized) {
          continue;
        }
        const elements = headingMap.get(normalized);
        if (elements && elements.length > 0) {
          const headingElement = elements[0];
          return collectContentUntilNextHeading(headingElement);
        }
      }
      return '';
    };

    missionExtraSectionDefinitions.forEach((definition) => {
      if (definition.type === 'group' && Array.isArray(definition.subfields) && definition.subfields.length) {
        const contractContainer = root.querySelector(`[data-contract="${definition.key}"]`);
        let fallbackGroupHtml = '';
        if (!contractContainer) {
          const candidateGroupHeadings = [definition.heading]
            .concat(Array.isArray(definition.legacyHeadings) ? definition.legacyHeadings : []);
          fallbackGroupHtml = extractByHeadings(candidateGroupHeadings);
        }
        definition.subfields.forEach((subfield) => {
          const headingTagName = (subfield.headingTag || definition.subheadingTag || 'h4').toLowerCase();
          let content = '';
          if (contractContainer) {
            const itemElement = contractContainer.querySelector(`[data-contract-part="${subfield.key}"]`);
            if (itemElement) {
              const clone = itemElement.cloneNode(true);
              const headingElement = clone.querySelector(headingTagName);
              if (headingElement && headingElement.parentNode) {
                headingElement.parentNode.removeChild(headingElement);
              }
              content = clone.innerHTML.trim();
            }
          }
          if (!content && fallbackGroupHtml) {
            const fragment = document.createElement('div');
            fragment.innerHTML = fallbackGroupHtml;
            const candidateSubHeadings = [subfield.heading]
              .concat(Array.isArray(subfield.legacyHeadings) ? subfield.legacyHeadings : [])
              .map((text) => normalizeMissionExtraHeading(text))
              .filter((text) => Boolean(text));
            const subheadingElements = Array.from(fragment.querySelectorAll(headingTagName));
            const matchedHeading = subheadingElements.find((element) => {
              const normalizedText = normalizeMissionExtraHeading(element.textContent);
              return candidateSubHeadings.includes(normalizedText);
            });
            if (matchedHeading) {
              const subFragment = document.createElement('div');
              let sibling = matchedHeading.nextSibling;
              while (sibling) {
                if (
                  sibling.nodeType === 1 &&
                  sibling.tagName &&
                  sibling.tagName.toLowerCase() === headingTagName
                ) {
                  break;
                }
                subFragment.appendChild(sibling.cloneNode(true));
                sibling = sibling.nextSibling;
              }
              content = subFragment.innerHTML.trim();
            }
          }
          if (!content) {
            const fallbackHeadings = [subfield.heading]
              .concat(Array.isArray(subfield.legacyHeadings) ? subfield.legacyHeadings : []);
            content = extractByHeadings(fallbackHeadings);
          }
          parsedValues[subfield.key] = content;
        });
        return;
      }
      const candidateHeadings = [definition.heading]
        .concat(Array.isArray(definition.legacyHeadings) ? definition.legacyHeadings : []);
      parsedValues[definition.key] = extractByHeadings(candidateHeadings);
    });
    return parsedValues;
  }

  function syncMissionSectionFieldsFromExtras(extras) {
    const html = extras && typeof extras.display_html === 'string' ? extras.display_html : '';
    const parsedSections = parseMissionExtrasDisplaySections(html);
    missionDisplaySectionValues = { ...createEmptyMissionDisplaySections(), ...parsedSections };
    setMissionSectionFieldValues(missionDisplaySectionValues);
    clearMissionSectionFieldErrors();
  }

  function buildMissionExtrasDisplayHtml(sectionValues) {
    const values = sectionValues || {};
    const sectionHtmlParts = missionExtraSectionDefinitions.map((definition) => {
      if (definition.type === 'group' && Array.isArray(definition.subfields) && definition.subfields.length) {
        const headingLines = [`<h3>${definition.heading}</h3>`];
        const containerLines = [`<div class="mission-contract" data-contract="${definition.key}">`];
        definition.subfields.forEach((subfield) => {
          const headingTagName = (subfield.headingTag || definition.subheadingTag || 'h4').toLowerCase();
          const content = typeof values[subfield.key] === 'string' ? values[subfield.key].trim() : '';
          const itemLines = [
            `<div class="mission-contract__item" data-contract-part="${subfield.key}">`,
            `  <${headingTagName}>${subfield.heading}</${headingTagName}>`,
          ];
          if (content) {
            content.split('\n').forEach((line) => {
              itemLines.push(line);
            });
          }
          itemLines.push(`</div>`);
          containerLines.push(itemLines.join('\n'));
        });
        containerLines.push(`</div>`);
        return headingLines.concat(containerLines).join('\n');
      }
      const content = typeof values[definition.key] === 'string' ? values[definition.key].trim() : '';
      return `<h3>${definition.heading}</h3>${content}`;
    });
    return `<section class="mission">\n${sectionHtmlParts.join('\n')}\n</section>`;
  }

  const handleDeliverablesChange = () => {
    const { deliverables, errors } = collectDeliverablesFromEditor(deliverablesList);
    renderAdminDeliverablesSummary(deliverablesSummary, deliverables, errors);
  };
  if (missionExtrasEditor) {
    missionExtrasEditor.addEventListener('input', () => {
      syncExtrasFromEditor({ fromSubmit: false });
    });
    missionExtrasEditor.addEventListener('blur', () => {
      syncExtrasFromEditor({ fromSubmit: true });
    });
  }
  setMissionExtrasEditorValue(missionContentExtras);
  syncMissionSectionFieldsFromExtras(missionContentExtras);
  updateDeliverablesEmptyState(deliverablesList);
  handleDeliverablesChange();
  function showFeedback(message, type = 'info') {
    if (!feedbackContainer) {
      return;
    }
    if (!message) {
      feedbackContainer.innerHTML = '';
      return;
    }
    const typeClass =
      type === 'success' ? 'status-success' : type === 'error' ? 'status-error' : 'status-info';
    feedbackContainer.innerHTML = `<div class="${typeClass}">${escapeHtml(message)}</div>`;
  }
  function setCreationMode(enabled) {
    isCreatingNewMission = Boolean(enabled);
    if (missionIdField) {
      if (enabled) {
        missionIdField.removeAttribute('hidden');
      } else {
        missionIdField.setAttribute('hidden', 'hidden');
      }
    }
    if (missionIdInput) {
      missionIdInput.disabled = !enabled;
      if (enabled) {
        missionIdInput.value = '';
        missionIdInput.focus();
      } else {
        missionIdInput.value = '';
      }
    }
    if (enabled) {
      if (missionSelect) {
        missionSelect.value = '';
      }
      if (missionTitleInput) {
        missionTitleInput.value = '';
      }
      if (missionVerificationSelect) {
        missionVerificationSelect.value = '';
      }
      if (missionSourceRepositoryInput) {
        missionSourceRepositoryInput.value = '';
      }
      if (missionSourceBranchInput) {
        missionSourceBranchInput.value = '';
      }
      if (missionSourceBasePathInput) {
        missionSourceBasePathInput.value = '';
      }
      renderDeliverablesEditor(deliverablesList, [], { onChange: handleDeliverablesChange });
      handleDeliverablesChange();
      missionContentExtras = {};
      setMissionExtrasEditorValue(missionContentExtras);
      resetMissionSectionFieldValues();
      roleInputs.forEach((input) => {
        input.checked = false;
      });
      if (saveButton) {
        saveButton.disabled = false;
      }
      showFeedback('Completa los campos para crear una nueva misión.', 'info');
    }
  }

  function repopulateMissionSelect(selectedMissionId) {
    if (!missionSelect) {
      return;
    }
    const missionOptionsHtml = missions
      .map((mission) => {
        const optionId = mission && mission.mission_id != null ? String(mission.mission_id) : '';
        if (!optionId) {
          return '';
        }
        return `<option value="${escapeHtml(optionId)}">${escapeHtml(optionId)}</option>`;
      })
      .join('');
    missionSelect.innerHTML = `<option value="">Selecciona una misión</option>${missionOptionsHtml}`;
    if (selectedMissionId) {
      missionSelect.value = selectedMissionId;
    }
  }

  function fillMissionForm(missionId) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    if (isCreatingNewMission) {
      setCreationMode(false);
    }
    const normalizedMissionId = missionId != null ? String(missionId) : '';
    const mission = missions.find((m) => {
      if (!m || !Object.prototype.hasOwnProperty.call(m, 'mission_id')) {
        return false;
      }
      const candidateId = m.mission_id != null ? String(m.mission_id) : '';
      return candidateId === normalizedMissionId;
    });
    if (!mission) {
      if (missionIdInput) {
        missionIdInput.value = '';
      }
      if (missionTitleInput) {
        missionTitleInput.value = '';
      }
      if (missionVerificationSelect) {
        missionVerificationSelect.value = '';
      }
      if (missionSourceRepositoryInput) {
        missionSourceRepositoryInput.value = '';
      }
      if (missionSourceBranchInput) {
        missionSourceBranchInput.value = '';
      }
      if (missionSourceBasePathInput) {
        missionSourceBasePathInput.value = '';
      }
      renderDeliverablesEditor(deliverablesList, [], { onChange: handleDeliverablesChange });
      handleDeliverablesChange();
      missionContentExtras = {};
      setMissionExtrasEditorValue(missionContentExtras);
      resetMissionSectionFieldValues();
      roleInputs.forEach((input) => {
        input.checked = false;
      });
      showFeedback('Selecciona una misión para comenzar.', 'info');
      if (saveButton) {
        saveButton.disabled = true;
      }
      return;
    }
    if (missionIdInput) {
      missionIdInput.value = normalizedMissionId;
    }
    if (missionTitleInput) {
      missionTitleInput.value = mission.title || '';
    }
    const normalizedRoles = Array.isArray(mission.roles) ? mission.roles : [];
    roleInputs.forEach((input) => {
      input.checked = normalizedRoles.includes(input.value);
    });
    const contentValue = mission && mission.content && typeof mission.content === 'object' ? mission.content : {};
    const { verificationType, source, deliverables, extras } = splitMissionContent(contentValue);
    missionContentExtras = cloneMissionContentExtras(extras);
    setMissionExtrasEditorValue(missionContentExtras);
    syncMissionSectionFieldsFromExtras(missionContentExtras);
    if (missionVerificationSelect) {
      const targetValue = verificationType || '';
      missionVerificationSelect.value = targetValue;
      if (targetValue && missionVerificationSelect.value !== targetValue) {
        const customOption = document.createElement('option');
        customOption.value = targetValue;
        customOption.textContent = targetValue;
        missionVerificationSelect.appendChild(customOption);
        missionVerificationSelect.value = targetValue;
      }
    }
    if (missionSourceRepositoryInput) {
      missionSourceRepositoryInput.value = source.repository || '';
    }
    if (missionSourceBranchInput) {
      missionSourceBranchInput.value = source.default_branch || '';
    }
    if (missionSourceBasePathInput) {
      missionSourceBasePathInput.value = source.base_path || '';
    }
    renderDeliverablesEditor(deliverablesList, deliverables, { onChange: handleDeliverablesChange });
    handleDeliverablesChange();
    if (saveButton) {
      saveButton.disabled = false;
    }
    showFeedback('', 'info');
  }
  if (missionSelect) {
    missionSelect.onchange = () => {
      if (isCreatingNewMission) {
        setCreationMode(false);
      }
      fillMissionForm(missionSelect.value);
    };
  }
  if (missions.length > 0 && missionSelect) {
    const firstMissionId = missions[0] && missions[0].mission_id != null ? String(missions[0].mission_id) : '';
    if (firstMissionId) {
      missionSelect.value = firstMissionId;
      fillMissionForm(firstMissionId);
    }
  } else if (saveButton) {
    saveButton.disabled = true;
    showFeedback('No hay misiones disponibles para editar. Crea una nueva misión para comenzar.', 'info');
  }
  const missionForm = sectionContainer.querySelector('#missionAdminForm');
  const newMissionButton = sectionContainer.querySelector('[data-action="new-mission"]');
  if (newMissionButton) {
    newMissionButton.onclick = () => {
      setCreationMode(true);
    };
  }
  if (addDeliverableButton) {
    addDeliverableButton.onclick = () => {
      if (deliverablesList) {
        const row = createDeliverableEditorRow(
          {},
          {
            listContainer: deliverablesList,
            onChange: handleDeliverablesChange,
            onRemove: handleDeliverablesChange,
          }
        );
        deliverablesList.appendChild(row);
        updateDeliverablesEmptyState(deliverablesList);
      }
      handleDeliverablesChange();
    };
  }
  if (missionForm) {
    missionForm.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      const creationMode = isCreatingNewMission;
      const missionIdSource = creationMode ? missionIdInput : missionSelect;
      const missionId = missionIdSource && missionIdSource.value != null ? missionIdSource.value.trim() : '';
      if (!missionId) {
        showFeedback(
          creationMode ? 'Ingresa un identificador para la nueva misión.' : 'Selecciona una misión antes de guardar.',
          'error'
        );
        return;
      }
      const payload = {};
      if (missionTitleInput) {
        payload.title = missionTitleInput.value;
      }
      const selectedRoles = roleInputs
        .filter((input) => input.checked)
        .map((input) => input.value);
      payload.roles = selectedRoles;
      const verificationType = missionVerificationSelect
        ? missionVerificationSelect.value.trim()
        : '';
      if (!verificationType) {
        showFeedback('Selecciona un tipo de verificación para la misión.', 'error');
        return;
      }
      const source = {
        repository: missionSourceRepositoryInput
          ? missionSourceRepositoryInput.value.trim()
          : '',
        default_branch: missionSourceBranchInput ? missionSourceBranchInput.value.trim() : '',
        base_path: missionSourceBasePathInput ? missionSourceBasePathInput.value.trim() : '',
      };
      if (!source.repository || !source.default_branch || !source.base_path) {
        showFeedback(
          'Completa la información del repositorio (nombre, rama y base path) para continuar.',
          'error'
        );
        return;
      }
      const { deliverables, errors: deliverableErrors } = collectDeliverablesFromEditor(
        deliverablesList
      );
      if (deliverableErrors.length > 0) {
        showFeedback(deliverableErrors[0], 'error');
        return;
      }
      if (verificationType === 'evidence' && deliverables.length === 0) {
        showFeedback('Agrega al menos un deliverable para las misiones de evidencia.', 'error');
        return;
      }
      const extrasAreValid = syncExtrasFromEditor({ fromSubmit: true });
      if (!extrasAreValid) {
        showFeedback('Corrige el JSON del contenido adicional antes de guardar.', 'error');
        if (missionExtrasEditor) {
          missionExtrasEditor.focus();
        }
        return;
      }
      const { values: sectionValues, missing: missingSections } = collectMissionSectionFieldValues();
      if (missingSections.length > 0) {
        const missingSection = missingSections[0];
        showFeedback(`Completa el bloque "${missingSection.heading}" antes de guardar.`, 'error');
        const missingField = missionExtrasFieldNodes[missingSection.key];
        if (missingField) {
          missingField.focus();
        }
        return;
      }
      missionDisplaySectionValues = { ...createEmptyMissionDisplaySections(), ...sectionValues };
      const displayHtml = buildMissionExtrasDisplayHtml(missionDisplaySectionValues);
      const extrasForPayload = cloneMissionContentExtras(missionContentExtras);
      extrasForPayload.display_html = displayHtml;
      missionContentExtras = extrasForPayload;
      setMissionExtrasEditorValue(missionContentExtras);
      syncMissionSectionFieldsFromExtras(missionContentExtras);
      payload.content = combineMissionContentParts({
        verificationType,
        source,
        deliverables,
        extras: extrasForPayload,
      });
      showFeedback('Guardando cambios...', 'info');
      try {
        const requestUrl = creationMode
          ? '/api/admin/missions'
          : `/api/admin/missions/${encodeURIComponent(missionId)}`;
        const requestPayload = creationMode ? { ...payload, mission_id: missionId } : payload;
        const res = await apiFetch(requestUrl, {
          method: creationMode ? 'POST' : 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
          body: JSON.stringify(requestPayload),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(
            backendMessage ||
              (creationMode
                ? 'No pudimos crear la nueva misión.'
                : 'No pudimos guardar los cambios de la misión.')
          );
        }
        const updatedMission = data.mission;
        if (creationMode) {
          const normalizedMissionId = missionId != null ? String(missionId) : '';
          const newMission = {
            ...(updatedMission || {}),
            mission_id: normalizedMissionId,
          };
          if (typeof newMission.title !== 'string') {
            newMission.title = payload.title || '';
          }
          if (!Array.isArray(newMission.roles)) {
            newMission.roles = Array.isArray(payload.roles) ? payload.roles : [];
          }
          if (
            !newMission.content ||
            typeof newMission.content !== 'object' ||
            Array.isArray(newMission.content)
          ) {
            newMission.content = payload.content;
          }
          missions = missions.filter((missionItem) => {
            if (!missionItem || !Object.prototype.hasOwnProperty.call(missionItem, 'mission_id')) {
              return true;
            }
            const candidateId = missionItem.mission_id != null ? String(missionItem.mission_id) : '';
            return candidateId !== normalizedMissionId;
          });
          missions.push(newMission);
          repopulateMissionSelect(normalizedMissionId);
          setCreationMode(false);
          fillMissionForm(normalizedMissionId);
          showFeedback('La misión se creó correctamente.', 'success');
          return;
        }
        if (updatedMission) {
          const normalizedMissionId = missionId != null ? String(missionId) : '';
          const index = missions.findIndex((m) => {
            if (!m || !Object.prototype.hasOwnProperty.call(m, 'mission_id')) {
              return false;
            }
            const candidateId = m.mission_id != null ? String(m.mission_id) : '';
            return candidateId === normalizedMissionId;
          });
          if (index !== -1) {
            const mergedMission = {
              ...missions[index],
              ...updatedMission,
              mission_id: normalizedMissionId,
            };
            if (
              (!updatedMission.content || typeof updatedMission.content !== 'object') &&
              payload.content
            ) {
              mergedMission.content = payload.content;
            }
            missions[index] = mergedMission;
          }
          fillMissionForm(missionId);
        }
        showFeedback('Los cambios se guardaron correctamente.', 'success');
      } catch (saveError) {
        const message =
          saveError && saveError.message ? saveError.message : 'Ocurrió un error al guardar los cambios.';
        showFeedback(message, 'error');
      }
    };
  }
}

async function renderAdminIntegrationsSection(sectionContainer, moduleState) {
  if (!sectionContainer) {
    return;
  }
  const sectionKey = 'integrations';
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  sectionContainer.innerHTML =
    '<div class="admin-module__status admin-module__status--loading"><p>Cargando integraciones...</p></div>';
  const { token } = moduleState.session;
  let settings = [];
  try {
    const res = await apiFetch('/api/admin/integrations', {
      credentials: 'include',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    if (res.status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    if (res.status === 403) {
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>No tienes permisos para administrar integraciones.</p>
          <button type="button" class="admin-button" data-action="admin-back">Volver</button>
        </div>
      `;
      const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
      if (backBtn) {
        backBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    if (!res.ok) {
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      throw new Error(backendMessage || 'No fue posible obtener la configuración de integraciones.');
    }
    settings = Array.isArray(data.settings) ? data.settings : [];
  } catch (err) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const message =
      err && err.message
        ? err.message
        : 'Ocurrió un error al cargar la configuración de integraciones.';
    sectionContainer.innerHTML = `
      <div class="status-error">
        <p>${escapeHtml(message)}</p>
        <button type="button" class="admin-button admin-button--ghost" data-action="retry-integrations">Reintentar</button>
      </div>
    `;
    const retryBtn = sectionContainer.querySelector('[data-action="retry-integrations"]');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderAdminIntegrationsSection(sectionContainer, moduleState);
      };
    }
    return;
  }
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  const categoryGroups = new Map();
  settings.forEach((entry) => {
    if (!entry || typeof entry !== 'object') {
      return;
    }
    const rawCategory = entry.category != null ? String(entry.category) : 'general';
    const normalizedCategory = rawCategory.trim() ? rawCategory.trim() : 'general';
    if (!categoryGroups.has(normalizedCategory)) {
      categoryGroups.set(normalizedCategory, []);
    }
    categoryGroups.get(normalizedCategory).push(entry);
  });
  const sortedCategories = Array.from(categoryGroups.keys()).sort((a, b) => a.localeCompare(b));
  function formatCategoryLabel(category) {
    const normalized = typeof category === 'string' ? category.trim().toLowerCase() : '';
    if (!normalized) {
      return 'General';
    }
    if (normalized === 'github') {
      return 'GitHub';
    }
    if (normalized === 'openai') {
      return 'OpenAI';
    }
    return category.charAt(0).toUpperCase() + category.slice(1);
  }
  function buildSettingField(setting) {
    const key = setting && setting.key != null ? String(setting.key) : '';
    if (!key) {
      return '';
    }
    const label = setting.label != null ? String(setting.label) : key;
    const helpText = setting.help_text != null ? String(setting.help_text) : '';
    const placeholder = setting.placeholder != null ? String(setting.placeholder) : '';
    const defaultValue = setting.default != null ? String(setting.default) : '';
    const isSecret = Boolean(setting.is_secret);
    const configured = Boolean(setting.configured);
    const storedValue = !isSecret && setting.value != null ? String(setting.value) : '';
    const fieldId = `adminIntegration_${key}`;
    const initialValueAttr = escapeHtml(storedValue);
    const defaultAttr = defaultValue ? ` data-default-value="${escapeHtml(defaultValue)}"` : '';
    const placeholderAttr = placeholder ? ` placeholder="${escapeHtml(placeholder)}"` : '';
    const valueAttr = !isSecret && storedValue ? ` value="${escapeHtml(storedValue)}"` : '';
    const secretNotice = isSecret
      ? `<p class="admin-card__hint">${
          configured
            ? 'Hay un valor almacenado. Deja el campo vacío si no deseas reemplazarlo.'
            : 'Ingresa el valor proporcionado por el servicio.'
        }</p>`
      : '';
    const helpBlock = helpText ? `<p class="admin-card__hint">${escapeHtml(helpText)}</p>` : '';
    const defaultBlock = defaultValue
      ? `<p class="admin-card__hint">Valor predeterminado: ${escapeHtml(defaultValue)}</p>`
      : '';
    const clearControl = isSecret
      ? `
        <div class="admin-field admin-field--checkbox admin-integration-clear">
          <label class="admin-checkbox">
            <input type="checkbox" data-role="clear-secret" data-setting-key="${escapeHtml(key)}">
            <span>Eliminar el valor almacenado</span>
          </label>
        </div>
      `
      : '';
    const defaultButton = defaultValue
      ? `
        <div class="admin-integration-field__actions">
          <button type="button" class="admin-button admin-button--ghost admin-integration-default" data-action="fill-default" data-setting-key="${escapeHtml(key)}">Usar valor predeterminado</button>
        </div>
      `
      : '';
    return `
      <div class="admin-integration-field" data-setting-key="${escapeHtml(key)}" data-secret="${
      isSecret ? 'true' : 'false'
    }" data-configured="${configured ? 'true' : 'false'}" data-initial-value="${initialValueAttr}"${defaultAttr}>
        <div class="admin-field">
          <label class="admin-field__label" for="${escapeHtml(fieldId)}">${escapeHtml(label)}</label>
          <input type="${isSecret ? 'password' : 'text'}" id="${escapeHtml(
            fieldId
          )}" class="admin-field__control admin-integration-input" autocomplete="off"${placeholderAttr}${valueAttr}>
          ${helpBlock}
          ${secretNotice}
          ${defaultBlock}
        </div>
        ${clearControl}
        ${defaultButton}
        <div class="admin-feedback admin-feedback--field" data-role="field-feedback"></div>
      </div>
    `;
  }
  const categoriesMarkup = sortedCategories
    .map((category) => {
      const label = formatCategoryLabel(category);
      const fields = categoryGroups
        .get(category)
        .map((entry) => buildSettingField(entry))
        .filter(Boolean)
        .join('');
      if (!fields) {
        return '';
      }
      return `
        <section class="admin-card admin-card--form admin-integration-category" data-category="${escapeHtml(
        category
      )}">
          <h4 class="admin-card__title">${escapeHtml(label)}</h4>
          ${fields}
        </section>
      `;
    })
    .filter(Boolean)
    .join('');
  const hasSettings = Boolean(categoriesMarkup);
  sectionContainer.innerHTML = `
    <div class="admin-section admin-section--integrations">
      <div class="admin-section__header">
        <div>
          <h3 class="admin-section__title">Integraciones</h3>
          <p class="admin-section__description">Configura las credenciales y parámetros de los servicios externos.</p>
        </div>
        <div class="admin-section__actions">
          <button type="button" class="admin-button admin-button--ghost" data-action="refresh-integrations">Actualizar</button>
        </div>
      </div>
      <div class="admin-section__body">
        ${
          hasSettings
            ? `
          <form id="adminIntegrationsForm" class="admin-form admin-form--integrations">
            <div class="admin-integration-groups">${categoriesMarkup}</div>
            <div id="adminIntegrationsFeedback" class="admin-feedback"></div>
            <div class="admin-form__actions">
              <button type="submit" class="admin-button">Guardar cambios</button>
            </div>
          </form>
        `
            : '<div class="status-info"><p>No hay integraciones configurables disponibles.</p></div>'
        }
      </div>
    </div>
  `;
  const refreshBtn = sectionContainer.querySelector('[data-action="refresh-integrations"]');
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      renderAdminIntegrationsSection(sectionContainer, moduleState);
    };
  }
  if (!hasSettings) {
    return;
  }
  const form = sectionContainer.querySelector('#adminIntegrationsForm');
  const feedbackContainer = sectionContainer.querySelector('#adminIntegrationsFeedback');
  const fieldContainers = Array.from(sectionContainer.querySelectorAll('.admin-integration-field'));
  const clearToggles = Array.from(sectionContainer.querySelectorAll('[data-role="clear-secret"]'));
  const defaultButtons = Array.from(sectionContainer.querySelectorAll('[data-action="fill-default"]'));
  const pendingFeedback =
    typeof moduleState.consumeIntegrationsFeedback === 'function'
      ? moduleState.consumeIntegrationsFeedback()
      : null;
  function showFeedback(message, type = 'info') {
    if (!feedbackContainer) {
      return;
    }
    if (!message) {
      feedbackContainer.innerHTML = '';
      return;
    }
    const typeClass =
      type === 'success' ? 'status-success' : type === 'error' ? 'status-error' : 'status-info';
    feedbackContainer.innerHTML = `<div class="${typeClass}">${escapeHtml(message)}</div>`;
  }
  function clearFieldErrors() {
    fieldContainers.forEach((field) => {
      field.classList.remove('has-error');
      const fieldFeedback = field.querySelector('[data-role="field-feedback"]');
      if (fieldFeedback) {
        fieldFeedback.innerHTML = '';
      }
    });
  }
  function showFieldError(fieldKey, message) {
    const field = fieldContainers.find((item) => item.dataset.settingKey === fieldKey);
    const safeMessage = message || 'Revisa el valor ingresado.';
    if (!field) {
      showFeedback(safeMessage, 'error');
      return;
    }
    const fieldFeedback = field.querySelector('[data-role="field-feedback"]');
    if (fieldFeedback) {
      fieldFeedback.innerHTML = `<div class="status-error">${escapeHtml(safeMessage)}</div>`;
    }
    field.classList.add('has-error');
    const input = field.querySelector('.admin-integration-input');
    if (input && typeof input.focus === 'function') {
      input.focus();
    }
  }
  if (pendingFeedback && pendingFeedback.message) {
    showFeedback(pendingFeedback.message, pendingFeedback.type || 'info');
  }
  clearToggles.forEach((toggle) => {
    toggle.addEventListener('change', () => {
      const field = toggle.closest('.admin-integration-field');
      const input = field ? field.querySelector('.admin-integration-input') : null;
      if (!input) {
        return;
      }
      if (toggle.checked) {
        input.value = '';
        input.disabled = true;
      } else {
        input.disabled = false;
        input.focus();
      }
    });
  });
  defaultButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.settingKey;
      const field = fieldContainers.find((item) => item.dataset.settingKey === key);
      if (!field) {
        return;
      }
      const defaultValue = field.dataset.defaultValue || '';
      const input = field.querySelector('.admin-integration-input');
      if (input) {
        input.disabled = false;
        input.value = defaultValue;
        if (typeof input.focus === 'function') {
          input.focus();
        }
      }
      const clearToggle = field.querySelector('[data-role="clear-secret"]');
      if (clearToggle) {
        clearToggle.checked = false;
      }
    });
  });
  if (form) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      clearFieldErrors();
      const updates = [];
      fieldContainers.forEach((field) => {
        const key = field.dataset.settingKey;
        if (!key) {
          return;
        }
        const isSecret = field.dataset.secret === 'true';
        const configured = field.dataset.configured === 'true';
        const initialValue = field.dataset.initialValue != null ? field.dataset.initialValue : '';
        const input = field.querySelector('.admin-integration-input');
        const clearToggle = field.querySelector('[data-role="clear-secret"]');
        const wantsClear = clearToggle ? clearToggle.checked : false;
        if (wantsClear) {
          if (configured || (!isSecret && initialValue)) {
            updates.push({ key, clear: true });
          }
          return;
        }
        const currentValue = input && !input.disabled ? input.value : '';
        if (isSecret) {
          if (currentValue) {
            updates.push({ key, value: currentValue });
          }
          return;
        }
        if (currentValue !== initialValue) {
          updates.push({ key, value: currentValue });
        }
      });
      if (!updates.length) {
        showFeedback('No hay cambios por guardar.', 'info');
        return;
      }
      showFeedback('Guardando configuraciones...', 'info');
      try {
        const res = await apiFetch('/api/admin/integrations', {
          method: 'PUT',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ updates }),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (sectionContainer.dataset.activeSection !== sectionKey) {
          return;
        }
        if (res.status === 401) {
          clearSession();
          sectionContainer.innerHTML = `
            <div class="status-error">
              <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
              <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
            </div>
          `;
          const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
          if (loginBtn) {
            loginBtn.onclick = () => {
              renderLoginForm();
            };
          }
          return;
        }
        if (res.status === 403) {
          sectionContainer.innerHTML = `
            <div class="status-error">
              <p>No tienes permisos para administrar integraciones.</p>
              <button type="button" class="admin-button" data-action="admin-back">Volver</button>
            </div>
          `;
          const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
          if (backBtn) {
            backBtn.onclick = () => {
              loadDashboard();
            };
          }
          return;
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          const fieldKey = typeof data.field === 'string' ? data.field : '';
          if (fieldKey) {
            showFieldError(fieldKey, backendMessage);
          } else {
            showFeedback(backendMessage || 'No se pudieron guardar los cambios.', 'error');
          }
          return;
        }
        if (typeof moduleState.setIntegrationsFeedback === 'function') {
          moduleState.setIntegrationsFeedback({
            type: 'success',
            message: 'Integraciones actualizadas correctamente.',
          });
        }
        moduleState.refreshCurrentSection();
      } catch (updateError) {
        const message =
          updateError && updateError.message
            ? updateError.message
            : 'No se pudieron guardar los cambios.';
        showFeedback(message, 'error');
      }
    };
  }
}

async function renderAdminUsersSection(sectionContainer, moduleState) {
  if (!sectionContainer) {
    return;
  }
  const sectionKey = 'users';
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  sectionContainer.innerHTML =
    '<div class="admin-module__status admin-module__status--loading"><p>Cargando usuarios...</p></div>';
  const { token } = moduleState.session;
  let students = [];
  try {
    const res = await apiFetch('/api/admin/students', {
      credentials: 'include',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    if (res.status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    if (res.status === 403) {
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>No tienes permisos para administrar usuarios.</p>
          <button type="button" class="admin-button" data-action="admin-back">Volver</button>
        </div>
      `;
      const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
      if (backBtn) {
        backBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    if (!res.ok) {
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      throw new Error(backendMessage || 'No fue posible obtener la lista de usuarios.');
    }
    students = Array.isArray(data.students) ? data.students : [];
  } catch (err) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const message = err && err.message ? err.message : 'Ocurrió un error al cargar los usuarios.';
    sectionContainer.innerHTML = `
      <div class="status-error">
        <p>${escapeHtml(message)}</p>
        <button type="button" class="admin-button admin-button--ghost" data-action="retry-users">Reintentar</button>
      </div>
    `;
    const retryBtn = sectionContainer.querySelector('[data-action="retry-users"]');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderAdminUsersSection(sectionContainer, moduleState);
      };
    }
    return;
  }
  let roles = [];
  let rolesLoadError = '';
  try {
    roles = await moduleState.loadRoles();
  } catch (rolesError) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const status = rolesError && rolesError.status;
    if (status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    if (status === 403) {
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>No tienes permisos para administrar usuarios.</p>
          <button type="button" class="admin-button" data-action="admin-back">Volver</button>
        </div>
      `;
      const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
      if (backBtn) {
        backBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    roles = [];
    rolesLoadError =
      rolesError && rolesError.message
        ? rolesError.message
        : 'No fue posible obtener el catálogo de roles. Podrás continuar, pero sin sugerencias.';
  }
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  const roleOptionsHtml = roles
    .map((role) => {
      const slug = role && role.slug ? String(role.slug) : '';
      const name = role && role.name ? String(role.name) : slug;
      if (!slug) {
        return '';
      }
      return `<option value="${escapeHtml(slug)}">${escapeHtml(name || slug)}</option>`;
    })
    .join('');
  sectionContainer.innerHTML = `
    <div class="admin-section admin-section--users">
      <div class="admin-section__header">
        <div>
          <h3 class="admin-section__title">Usuarios</h3>
          <p class="admin-section__description">Gestiona cuentas, privilegios y contraseñas desde un solo lugar.</p>
        </div>
        <button type="button" class="admin-button admin-button--ghost" data-action="refresh-users">Actualizar</button>
      </div>
      ${rolesLoadError ? `<div class="status-warning"><p>${escapeHtml(rolesLoadError)}</p></div>` : ''}
      <div class="admin-section__grid admin-section__grid--two-columns">
        <div class="admin-card admin-card--list">
          <h4 class="admin-card__title">Listado de usuarios</h4>
          <div class="admin-table" id="adminUsersTable"></div>
        </div>
        <div class="admin-card admin-card--form">
          <h4 class="admin-card__title">Crear usuario</h4>
          <form id="adminUserCreateForm" class="admin-form">
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreateSlug">Slug</label>
              <input type="text" id="adminCreateSlug" class="admin-field__control" required>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreateName">Nombre</label>
              <input type="text" id="adminCreateName" class="admin-field__control" required>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreateEmail">Correo electrónico</label>
              <input type="email" id="adminCreateEmail" class="admin-field__control" required>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreateRole">Rol</label>
              <select id="adminCreateRole" class="admin-field__control">
                <option value="">Sin rol asignado</option>
                ${roleOptionsHtml}
              </select>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreateWorkdir">Carpeta de trabajo (opcional)</label>
              <input type="text" id="adminCreateWorkdir" class="admin-field__control" placeholder="/home/usuario/proyecto">
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminCreatePassword">Contraseña temporal</label>
              <input type="password" id="adminCreatePassword" class="admin-field__control" required>
            </div>
            <div class="admin-field admin-field--checkbox">
              <label class="admin-checkbox">
                <input type="checkbox" id="adminCreateIsAdmin">
                <span>Con acceso administrativo</span>
              </label>
            </div>
            <div class="admin-form__actions">
              <button type="submit" class="admin-button">Crear usuario</button>
            </div>
          </form>
          <div id="adminUserCreateFeedback" class="admin-feedback"></div>
        </div>
      </div>
      <div class="admin-card admin-card--form admin-card--wide">
        <h4 class="admin-card__title">Editar usuario</h4>
        <p class="admin-card__hint">Selecciona un usuario de la lista para habilitar el formulario.</p>
        <form id="adminUserEditForm" class="admin-form" autocomplete="off">
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditSlug">Slug</label>
            <input type="text" id="adminEditSlug" class="admin-field__control" readonly>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditName">Nombre</label>
            <input type="text" id="adminEditName" class="admin-field__control" required>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditEmail">Correo electrónico</label>
            <input type="email" id="adminEditEmail" class="admin-field__control" required>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditRole">Rol</label>
            <select id="adminEditRole" class="admin-field__control">
              <option value="">Sin rol asignado</option>
              ${roleOptionsHtml}
            </select>
          </div>
          <div class="admin-field admin-field--checkbox">
            <label class="admin-checkbox">
              <input type="checkbox" id="adminEditIsAdmin">
              <span>Con acceso administrativo</span>
            </label>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditCurrentPassword">Contraseña actual (opcional)</label>
            <input type="password" id="adminEditCurrentPassword" class="admin-field__control">
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminEditPassword">Nueva contraseña (opcional)</label>
            <input type="password" id="adminEditPassword" class="admin-field__control">
          </div>
          <div class="admin-form__actions admin-form__actions--split">
            <button type="submit" class="admin-button" id="adminUserSaveBtn" disabled>Guardar cambios</button>
            <button type="button" class="admin-button admin-button--danger" id="adminUserDeleteBtn" disabled>Eliminar usuario</button>
          </div>
        </form>
        <div id="adminUserEditFeedback" class="admin-feedback"></div>
        <div id="adminUserProgress" class="admin-user-progress"></div>
      </div>
    </div>
  `;
  const refreshBtn = sectionContainer.querySelector('[data-action="refresh-users"]');
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      moduleState.invalidateRoles();
      renderAdminUsersSection(sectionContainer, moduleState);
    };
  }
  const tableContainer = sectionContainer.querySelector('#adminUsersTable');
  if (tableContainer) {
    tableContainer.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Slug</th>
            <th>Rol</th>
            <th>Admin</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="adminUsersTableBody"></tbody>
      </table>
    `;
  }
  const tableBody = sectionContainer.querySelector('#adminUsersTableBody');
  const createForm = sectionContainer.querySelector('#adminUserCreateForm');
  const createFeedback = sectionContainer.querySelector('#adminUserCreateFeedback');
  const createSlugInput = sectionContainer.querySelector('#adminCreateSlug');
  const createNameInput = sectionContainer.querySelector('#adminCreateName');
  const createEmailInput = sectionContainer.querySelector('#adminCreateEmail');
  const createRoleSelect = sectionContainer.querySelector('#adminCreateRole');
  const createWorkdirInput = sectionContainer.querySelector('#adminCreateWorkdir');
  const createPasswordInput = sectionContainer.querySelector('#adminCreatePassword');
  const createIsAdminInput = sectionContainer.querySelector('#adminCreateIsAdmin');
  const editForm = sectionContainer.querySelector('#adminUserEditForm');
  const editFeedback = sectionContainer.querySelector('#adminUserEditFeedback');
  const editSlugInput = sectionContainer.querySelector('#adminEditSlug');
  const editNameInput = sectionContainer.querySelector('#adminEditName');
  const editEmailInput = sectionContainer.querySelector('#adminEditEmail');
  const editRoleSelect = sectionContainer.querySelector('#adminEditRole');
  const editIsAdminInput = sectionContainer.querySelector('#adminEditIsAdmin');
  const editCurrentPasswordInput = sectionContainer.querySelector('#adminEditCurrentPassword');
  const editPasswordInput = sectionContainer.querySelector('#adminEditPassword');
  const editSaveBtn = sectionContainer.querySelector('#adminUserSaveBtn');
  const editDeleteBtn = sectionContainer.querySelector('#adminUserDeleteBtn');
  const progressContainer = sectionContainer.querySelector('#adminUserProgress');
  let selectedSlug = '';
  function showFeedback(container, message, type = 'info') {
    if (!container) {
      return;
    }
    if (!message) {
      container.innerHTML = '';
      return;
    }
    const typeClass =
      type === 'success' ? 'status-success' : type === 'error' ? 'status-error' : type === 'warning' ? 'status-warning' : 'status-info';
    container.innerHTML = `<div class="${typeClass}">${escapeHtml(message)}</div>`;
  }
  function renderUsersTable() {
    if (!tableBody) {
      return;
    }
    if (!students.length) {
      tableBody.innerHTML = '<tr><td colspan="5">No hay usuarios registrados.</td></tr>';
      return;
    }
    tableBody.innerHTML = students
      .map((student) => {
        const slug = student && student.slug ? String(student.slug) : '';
        const name = student && student.name ? String(student.name) : slug;
        const email = student && student.email ? String(student.email) : '';
        const roleName = student && student.role_name ? student.role_name : student && student.role ? student.role : '—';
        const isAdmin = _normalizeBooleanFlag(student && student.is_admin);
        const isSelected = slug && slug === selectedSlug;
        return `
          <tr data-slug="${escapeHtml(slug)}" class="${isSelected ? 'is-selected' : ''}">
            <td>
              <div class="admin-table__primary">${escapeHtml(name || slug)}</div>
              ${email ? `<div class="admin-table__secondary">${escapeHtml(email)}</div>` : ''}
            </td>
            <td>${escapeHtml(slug)}</td>
            <td>${escapeHtml(roleName || '—')}</td>
            <td>${isAdmin ? 'Sí' : 'No'}</td>
            <td class="admin-table__actions">
              <button type="button" class="admin-button admin-button--small" data-action="select-user" data-slug="${escapeHtml(slug)}">Editar</button>
            </td>
          </tr>
        `;
      })
      .join('');
  }
  function updateProgress(student) {
    if (!progressContainer) {
      return;
    }
    const completed = student && Array.isArray(student.completed_missions) ? student.completed_missions : [];
    if (!completed.length) {
      progressContainer.innerHTML = '<p class="admin-user-progress__empty">Sin misiones completadas registradas.</p>';
      return;
    }
    const items = completed
      .map((missionId) => `<li>${escapeHtml(String(missionId))}</li>`)
      .join('');
    progressContainer.innerHTML = `
      <p class="admin-user-progress__title">Misiones completadas</p>
      <ul class="admin-user-progress__list">${items}</ul>
    `;
  }
  function clearProgress() {
    if (progressContainer) {
      progressContainer.innerHTML = '';
    }
  }
  function selectUser(slug) {
    if (!editForm) {
      return;
    }
    const normalizedSlug = slug != null ? String(slug) : '';
    const student = students.find((entry) => entry && entry.slug && String(entry.slug) === normalizedSlug);
    if (!student) {
      return;
    }
    selectedSlug = normalizedSlug;
    if (tableBody) {
      Array.from(tableBody.querySelectorAll('tr')).forEach((row) => {
        row.classList.toggle('is-selected', row.dataset.slug === normalizedSlug);
      });
    }
    if (editSlugInput) {
      editSlugInput.value = normalizedSlug;
    }
    if (editNameInput) {
      editNameInput.value = student.name || '';
    }
    if (editEmailInput) {
      editEmailInput.value = student.email || '';
    }
    if (editRoleSelect) {
      editRoleSelect.value = student.role || '';
    }
    if (editIsAdminInput) {
      editIsAdminInput.checked = _normalizeBooleanFlag(student.is_admin);
    }
    if (editCurrentPasswordInput) {
      editCurrentPasswordInput.value = '';
    }
    if (editPasswordInput) {
      editPasswordInput.value = '';
    }
    showFeedback(editFeedback, '', 'info');
    updateProgress(student);
    if (editSaveBtn) {
      editSaveBtn.disabled = false;
    }
    if (editDeleteBtn) {
      editDeleteBtn.disabled = false;
    }
  }
  function resetEditForm() {
    selectedSlug = '';
    if (editForm) {
      editForm.reset();
      editForm.dataset.slug = '';
    }
    if (editSaveBtn) {
      editSaveBtn.disabled = true;
    }
    if (editDeleteBtn) {
      editDeleteBtn.disabled = true;
    }
    if (tableBody) {
      Array.from(tableBody.querySelectorAll('tr')).forEach((row) => {
        row.classList.remove('is-selected');
      });
    }
    showFeedback(editFeedback, 'Selecciona un usuario para editar sus datos.', 'info');
    clearProgress();
  }
  renderUsersTable();
  if (createForm) {
    createForm.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      const slug = (createSlugInput && createSlugInput.value ? createSlugInput.value : '').trim();
      const name = (createNameInput && createNameInput.value ? createNameInput.value : '').trim();
      const email = (createEmailInput && createEmailInput.value ? createEmailInput.value : '').trim();
      const role = createRoleSelect ? createRoleSelect.value : '';
      const workdir = (createWorkdirInput && createWorkdirInput.value ? createWorkdirInput.value : '').trim();
      const password = createPasswordInput ? createPasswordInput.value : '';
      const isAdmin = createIsAdminInput ? createIsAdminInput.checked : false;
      if (!slug || !name || !email || !password) {
        showFeedback(createFeedback, 'Completa los campos obligatorios antes de continuar.', 'error');
        return;
      }
      const payload = {
        slug,
        name,
        email,
        password,
        is_admin: isAdmin,
      };
      if (role) {
        payload.role = role;
      }
      if (workdir) {
        payload.workdir = workdir;
      }
      showFeedback(createFeedback, 'Creando usuario...', 'info');
      try {
        const res = await apiFetch('/api/admin/students', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
          body: JSON.stringify(payload),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudo crear el usuario.');
        }
        if (data.student) {
          const createdSlug = data.student.slug ? String(data.student.slug) : slug;
          const index = students.findIndex((entry) => entry && entry.slug && String(entry.slug) === createdSlug);
          if (index === -1) {
            students.push(data.student);
          } else {
            students[index] = data.student;
          }
        } else if (Array.isArray(data.students)) {
          students = data.students;
        } else {
          moduleState.refreshCurrentSection();
          return;
        }
        renderUsersTable();
        if (createForm) {
          createForm.reset();
        }
        showFeedback(createFeedback, 'Usuario creado correctamente.', 'success');
      } catch (createError) {
        const message =
          createError && createError.message ? createError.message : 'No se pudo crear el usuario.';
        showFeedback(createFeedback, message, 'error');
      }
    };
  }
  if (tableContainer) {
    tableContainer.addEventListener('click', (event) => {
      const target = event.target instanceof HTMLElement ? event.target.closest('[data-action="select-user"]') : null;
      if (!target) {
        return;
      }
      event.preventDefault();
      const slug = target.getAttribute('data-slug');
      if (slug) {
        selectUser(slug);
      }
    });
  }
  if (editForm) {
    editForm.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      if (!selectedSlug) {
        showFeedback(editFeedback, 'Selecciona un usuario de la lista.', 'error');
        return;
      }
      const name = (editNameInput && editNameInput.value ? editNameInput.value : '').trim();
      const email = (editEmailInput && editEmailInput.value ? editEmailInput.value : '').trim();
      const role = editRoleSelect ? editRoleSelect.value : '';
      const isAdmin = editIsAdminInput ? editIsAdminInput.checked : false;
      if (!name || !email) {
        showFeedback(editFeedback, 'Nombre y correo electrónico son obligatorios.', 'error');
        return;
      }
      const payload = {
        name,
        email,
        is_admin: isAdmin,
      };
      payload.role = role || null;
      const newPassword = editPasswordInput ? editPasswordInput.value : '';
      const currentPassword = editCurrentPasswordInput ? editCurrentPasswordInput.value : '';
      if (newPassword) {
        payload.password = newPassword;
      }
      if (currentPassword) {
        payload.current_password = currentPassword;
      }
      showFeedback(editFeedback, 'Guardando cambios...', 'info');
      try {
        const res = await apiFetch(`/api/admin/students/${encodeURIComponent(selectedSlug)}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
          body: JSON.stringify(payload),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudieron guardar los cambios.');
        }
        if (data.student) {
          const updatedSlug = data.student.slug ? String(data.student.slug) : selectedSlug;
          const index = students.findIndex((entry) => entry && entry.slug && String(entry.slug) === updatedSlug);
          if (index !== -1) {
            students[index] = data.student;
          }
          renderUsersTable();
          selectUser(updatedSlug);
          showFeedback(editFeedback, 'Los cambios se guardaron correctamente.', 'success');
        } else {
          moduleState.refreshCurrentSection();
        }
      } catch (updateError) {
        const message =
          updateError && updateError.message ? updateError.message : 'No se pudieron guardar los cambios.';
        showFeedback(editFeedback, message, 'error');
      }
    };
  }
  if (editDeleteBtn) {
    editDeleteBtn.onclick = async () => {
      if (!selectedSlug) {
        showFeedback(editFeedback, 'Selecciona un usuario antes de eliminar.', 'error');
        return;
      }
      const confirmed =
        typeof window !== 'undefined'
          ? window.confirm(`¿Deseas eliminar al usuario ${selectedSlug}? Esta acción no se puede deshacer.`)
          : true;
      if (!confirmed) {
        return;
      }
      showFeedback(editFeedback, 'Eliminando usuario...', 'info');
      try {
        const res = await apiFetch(`/api/admin/students/${encodeURIComponent(selectedSlug)}`, {
          method: 'DELETE',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudo eliminar el usuario.');
        }
        students = students.filter((entry) => !entry || String(entry.slug) !== selectedSlug);
        renderUsersTable();
        resetEditForm();
        showFeedback(editFeedback, 'Usuario eliminado correctamente.', 'success');
      } catch (deleteError) {
        const message =
          deleteError && deleteError.message ? deleteError.message : 'No se pudo eliminar el usuario.';
        showFeedback(editFeedback, message, 'error');
      }
    };
  }
  if (editForm && !selectedSlug) {
    showFeedback(editFeedback, 'Selecciona un usuario para editar sus datos.', 'info');
  }
}

async function renderAdminRolesSection(sectionContainer, moduleState) {
  if (!sectionContainer) {
    return;
  }
  const sectionKey = 'roles';
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  sectionContainer.innerHTML =
    '<div class="admin-module__status admin-module__status--loading"><p>Cargando roles...</p></div>';
  const { token } = moduleState.session;
  let roles = [];
  try {
    roles = await moduleState.loadRoles(true);
  } catch (err) {
    if (sectionContainer.dataset.activeSection !== sectionKey) {
      return;
    }
    const status = err && err.status;
    if (status === 401) {
      clearSession();
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button type="button" class="admin-button" data-action="admin-login">Iniciar sesión</button>
        </div>
      `;
      const loginBtn = sectionContainer.querySelector('[data-action="admin-login"]');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    if (status === 403) {
      sectionContainer.innerHTML = `
        <div class="status-error">
          <p>No tienes permisos para administrar roles.</p>
          <button type="button" class="admin-button" data-action="admin-back">Volver</button>
        </div>
      `;
      const backBtn = sectionContainer.querySelector('[data-action="admin-back"]');
      if (backBtn) {
        backBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    const message = err && err.message ? err.message : 'No fue posible obtener los roles.';
    sectionContainer.innerHTML = `
      <div class="status-error">
        <p>${escapeHtml(message)}</p>
        <button type="button" class="admin-button admin-button--ghost" data-action="retry-roles">Reintentar</button>
      </div>
    `;
    const retryBtn = sectionContainer.querySelector('[data-action="retry-roles"]');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderAdminRolesSection(sectionContainer, moduleState);
      };
    }
    return;
  }
  if (sectionContainer.dataset.activeSection !== sectionKey) {
    return;
  }
  sectionContainer.innerHTML = `
    <div class="admin-section admin-section--roles">
      <div class="admin-section__header">
        <div>
          <h3 class="admin-section__title">Roles</h3>
          <p class="admin-section__description">Define los perfiles disponibles y su metadata asociada.</p>
        </div>
        <button type="button" class="admin-button admin-button--ghost" data-action="refresh-roles">Actualizar</button>
      </div>
      <div class="admin-section__grid admin-section__grid--two-columns">
        <div class="admin-card admin-card--list">
          <h4 class="admin-card__title">Roles registrados</h4>
          <div class="admin-table" id="adminRolesTable"></div>
        </div>
        <div class="admin-card admin-card--form">
          <h4 class="admin-card__title">Crear rol</h4>
          <form id="adminRoleCreateForm" class="admin-form">
            <div class="admin-field">
              <label class="admin-field__label" for="adminRoleCreateSlug">Identificador</label>
              <input type="text" id="adminRoleCreateSlug" class="admin-field__control" required>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminRoleCreateName">Nombre</label>
              <input type="text" id="adminRoleCreateName" class="admin-field__control" required>
            </div>
            <div class="admin-field">
              <label class="admin-field__label" for="adminRoleCreateMetadata">Metadata (JSON)</label>
              <textarea id="adminRoleCreateMetadata" class="admin-field__control admin-field__control--textarea" rows="8" placeholder='{"description": "..."}'></textarea>
            </div>
            <div class="admin-form__actions">
              <button type="submit" class="admin-button">Crear rol</button>
            </div>
          </form>
          <div id="adminRoleCreateFeedback" class="admin-feedback"></div>
        </div>
      </div>
      <div class="admin-card admin-card--form admin-card--wide">
        <h4 class="admin-card__title">Editar rol</h4>
        <p class="admin-card__hint">El slug es inmutable. Ajusta nombre y metadata según sea necesario.</p>
        <form id="adminRoleEditForm" class="admin-form">
          <div class="admin-field">
            <label class="admin-field__label" for="adminRoleEditSlug">Identificador</label>
            <input type="text" id="adminRoleEditSlug" class="admin-field__control" readonly>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminRoleEditName">Nombre</label>
            <input type="text" id="adminRoleEditName" class="admin-field__control" required>
          </div>
          <div class="admin-field">
            <label class="admin-field__label" for="adminRoleEditMetadata">Metadata (JSON)</label>
            <textarea id="adminRoleEditMetadata" class="admin-field__control admin-field__control--textarea" rows="10"></textarea>
          </div>
          <div class="admin-form__actions admin-form__actions--split">
            <button type="submit" class="admin-button" id="adminRoleSaveBtn" disabled>Guardar cambios</button>
            <button type="button" class="admin-button admin-button--danger" id="adminRoleDeleteBtn" disabled>Eliminar rol</button>
          </div>
        </form>
        <div id="adminRoleEditFeedback" class="admin-feedback"></div>
      </div>
    </div>
  `;
  const refreshBtn = sectionContainer.querySelector('[data-action="refresh-roles"]');
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      moduleState.invalidateRoles();
      renderAdminRolesSection(sectionContainer, moduleState);
    };
  }
  const tableContainer = sectionContainer.querySelector('#adminRolesTable');
  if (tableContainer) {
    tableContainer.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Slug</th>
            <th>Nombre</th>
            <th>Descripción</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="adminRolesTableBody"></tbody>
      </table>
    `;
  }
  const tableBody = sectionContainer.querySelector('#adminRolesTableBody');
  const createForm = sectionContainer.querySelector('#adminRoleCreateForm');
  const createFeedback = sectionContainer.querySelector('#adminRoleCreateFeedback');
  const createSlugInput = sectionContainer.querySelector('#adminRoleCreateSlug');
  const createNameInput = sectionContainer.querySelector('#adminRoleCreateName');
  const createMetadataInput = sectionContainer.querySelector('#adminRoleCreateMetadata');
  const editForm = sectionContainer.querySelector('#adminRoleEditForm');
  const editFeedback = sectionContainer.querySelector('#adminRoleEditFeedback');
  const editSlugInput = sectionContainer.querySelector('#adminRoleEditSlug');
  const editNameInput = sectionContainer.querySelector('#adminRoleEditName');
  const editMetadataInput = sectionContainer.querySelector('#adminRoleEditMetadata');
  const editSaveBtn = sectionContainer.querySelector('#adminRoleSaveBtn');
  const editDeleteBtn = sectionContainer.querySelector('#adminRoleDeleteBtn');
  let selectedRole = '';
  function showFeedback(container, message, type = 'info') {
    if (!container) {
      return;
    }
    if (!message) {
      container.innerHTML = '';
      return;
    }
    const typeClass =
      type === 'success' ? 'status-success' : type === 'error' ? 'status-error' : type === 'warning' ? 'status-warning' : 'status-info';
    container.innerHTML = `<div class="${typeClass}">${escapeHtml(message)}</div>`;
  }
  function renderRolesTable() {
    if (!tableBody) {
      return;
    }
    if (!roles.length) {
      tableBody.innerHTML = '<tr><td colspan="4">Aún no hay roles registrados.</td></tr>';
      return;
    }
    tableBody.innerHTML = roles
      .map((role) => {
        const slug = role && role.slug ? String(role.slug) : '';
        const name = role && role.name ? String(role.name) : slug;
        const metadata = role && role.metadata && typeof role.metadata === 'object' ? role.metadata : {};
        const description = metadata && metadata.description ? String(metadata.description) : '';
        const isSelected = slug && slug === selectedRole;
        return `
          <tr data-slug="${escapeHtml(slug)}" class="${isSelected ? 'is-selected' : ''}">
            <td>${escapeHtml(slug)}</td>
            <td>${escapeHtml(name)}</td>
            <td>${escapeHtml(description || '—')}</td>
            <td class="admin-table__actions">
              <button type="button" class="admin-button admin-button--small" data-action="select-role" data-slug="${escapeHtml(slug)}">Editar</button>
            </td>
          </tr>
        `;
      })
      .join('');
  }
  function selectRole(slug) {
    if (!editForm) {
      return;
    }
    const normalizedSlug = slug != null ? String(slug) : '';
    const role = roles.find((entry) => entry && entry.slug && String(entry.slug) === normalizedSlug);
    if (!role) {
      return;
    }
    selectedRole = normalizedSlug;
    if (tableBody) {
      Array.from(tableBody.querySelectorAll('tr')).forEach((row) => {
        row.classList.toggle('is-selected', row.dataset.slug === normalizedSlug);
      });
    }
    if (editSlugInput) {
      editSlugInput.value = normalizedSlug;
    }
    if (editNameInput) {
      editNameInput.value = role.name || '';
    }
    if (editMetadataInput) {
      const metadata = role && role.metadata && typeof role.metadata === 'object' ? role.metadata : {};
      editMetadataInput.value = JSON.stringify(metadata, null, 2);
    }
    showFeedback(editFeedback, '', 'info');
    if (editSaveBtn) {
      editSaveBtn.disabled = false;
    }
    if (editDeleteBtn) {
      editDeleteBtn.disabled = false;
    }
  }
  renderRolesTable();
  if (createForm) {
    createForm.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      const slug = (createSlugInput && createSlugInput.value ? createSlugInput.value : '').trim();
      const name = (createNameInput && createNameInput.value ? createNameInput.value : '').trim();
      const metadataRaw = createMetadataInput && createMetadataInput.value ? createMetadataInput.value.trim() : '';
      if (!slug || !name) {
        showFeedback(createFeedback, 'Slug y nombre son obligatorios.', 'error');
        return;
      }
      let metadataObj = {};
      if (metadataRaw) {
        try {
          const parsed = JSON.parse(metadataRaw);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            metadataObj = parsed;
          } else {
            throw new Error('La metadata debe ser un objeto JSON.');
          }
        } catch (parseError) {
          showFeedback(createFeedback, 'La metadata debe ser un objeto JSON válido.', 'error');
          return;
        }
      }
      const payload = {
        slug,
        name,
        metadata: metadataObj,
      };
      showFeedback(createFeedback, 'Creando rol...', 'info');
      try {
        const res = await apiFetch('/api/admin/roles', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
          body: JSON.stringify(payload),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudo crear el rol.');
        }
        if (data.role) {
          roles.push(data.role);
          moduleState.invalidateRoles();
          renderRolesTable();
        } else {
          moduleState.invalidateRoles();
          moduleState.refreshCurrentSection();
          return;
        }
        if (createForm) {
          createForm.reset();
        }
        showFeedback(createFeedback, 'Rol creado correctamente.', 'success');
      } catch (createError) {
        const message =
          createError && createError.message ? createError.message : 'No se pudo crear el rol.';
        showFeedback(createFeedback, message, 'error');
      }
    };
  }
  if (tableContainer) {
    tableContainer.addEventListener('click', (event) => {
      const target = event.target instanceof HTMLElement ? event.target.closest('[data-action="select-role"]') : null;
      if (!target) {
        return;
      }
      event.preventDefault();
      const slug = target.getAttribute('data-slug');
      if (slug) {
        selectRole(slug);
      }
    });
  }
  if (editForm) {
    editForm.onsubmit = async (event) => {
      event.preventDefault();
      if (sectionContainer.dataset.activeSection !== sectionKey) {
        return;
      }
      if (!selectedRole) {
        showFeedback(editFeedback, 'Selecciona un rol para continuar.', 'error');
        return;
      }
      const name = (editNameInput && editNameInput.value ? editNameInput.value : '').trim();
      const metadataRaw = editMetadataInput && editMetadataInput.value ? editMetadataInput.value.trim() : '';
      if (!name) {
        showFeedback(editFeedback, 'El nombre es obligatorio.', 'error');
        return;
      }
      let metadataObj = null;
      if (metadataRaw) {
        try {
          const parsed = JSON.parse(metadataRaw);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            metadataObj = parsed;
          } else {
            throw new Error('La metadata debe ser un objeto JSON.');
          }
        } catch (parseError) {
          showFeedback(editFeedback, 'La metadata debe ser un objeto JSON válido.', 'error');
          return;
        }
      }
      const payload = { name };
      if (metadataObj !== null) {
        payload.metadata = metadataObj;
      }
      showFeedback(editFeedback, 'Guardando cambios...', 'info');
      try {
        const res = await apiFetch(`/api/admin/roles/${encodeURIComponent(selectedRole)}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
          body: JSON.stringify(payload),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudieron guardar los cambios.');
        }
        if (data.role) {
          const index = roles.findIndex((entry) => entry && entry.slug && String(entry.slug) === selectedRole);
          if (index !== -1) {
            roles[index] = data.role;
          }
          moduleState.invalidateRoles();
          renderRolesTable();
          selectRole(selectedRole);
          showFeedback(editFeedback, 'Los cambios se guardaron correctamente.', 'success');
        } else {
          moduleState.invalidateRoles();
          moduleState.refreshCurrentSection();
        }
      } catch (updateError) {
        const message =
          updateError && updateError.message ? updateError.message : 'No se pudieron guardar los cambios.';
        showFeedback(editFeedback, message, 'error');
      }
    };
  }
  if (editDeleteBtn) {
    editDeleteBtn.onclick = async () => {
      if (!selectedRole) {
        showFeedback(editFeedback, 'Selecciona un rol antes de eliminar.', 'error');
        return;
      }
      const confirmed =
        typeof window !== 'undefined'
          ? window.confirm(`¿Deseas eliminar el rol ${selectedRole}? Esta acción no se puede deshacer.`)
          : true;
      if (!confirmed) {
        return;
      }
      showFeedback(editFeedback, 'Eliminando rol...', 'info');
      try {
        const res = await apiFetch(`/api/admin/roles/${encodeURIComponent(selectedRole)}`, {
          method: 'DELETE',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          credentials: 'include',
        });
        let data = {};
        try {
          data = await res.json();
        } catch (parseError) {
          data = {};
        }
        if (!res.ok) {
          const backendMessage = typeof data.error === 'string' ? data.error : '';
          throw new Error(backendMessage || 'No se pudo eliminar el rol.');
        }
        roles = roles.filter((entry) => !entry || String(entry.slug) !== selectedRole);
        moduleState.invalidateRoles();
        selectedRole = '';
        if (editForm) {
          editForm.reset();
        }
        if (editSaveBtn) {
          editSaveBtn.disabled = true;
        }
        if (editDeleteBtn) {
          editDeleteBtn.disabled = true;
        }
        renderRolesTable();
        showFeedback(editFeedback, 'Rol eliminado correctamente.', 'success');
      } catch (deleteError) {
        const message =
          deleteError && deleteError.message ? deleteError.message : 'No se pudo eliminar el rol.';
        showFeedback(editFeedback, message, 'error');
      }
    };
  }
  if (editForm && !selectedRole) {
    showFeedback(editFeedback, 'Selecciona un rol para editar sus datos.', 'info');
  }
}

function renderMissionAdminPanel(defaultSection) {
  renderAdminModule(resolvePreferredAdminSection(defaultSection));
}



/**
 * Confirma si una misión está desbloqueada para el estudiante actual.
 * @param {string} missionId
 * @returns {Promise<{allowed: boolean, action?: string, redirectTo?: string, message?: string, reason?: string}>}
 */
async function ensureMissionUnlocked(missionId) {
  const slug = getStoredSlug();
  const token = getStoredToken();
  if (!slug || !token) {
    clearSession();
    return {
      allowed: false,
      reason: 'missing-session',
      action: 'redirect',
      redirectTo: 'index.html',
      message: 'Debes iniciar sesión nuevamente desde el portal para continuar.',
    };
  }
  const initialSlug = slug;
  const headers = token
    ? {
        Authorization: `Bearer ${token}`,
      }
    : {};
  const statusUrl = `/api/status?${new URLSearchParams({ slug })}`;
  try {
    const res = await apiFetch(statusUrl, {
      credentials: 'include',
      headers,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseError) {
      data = {};
    }
    if (res.status === 401) {
      clearSession();
      return {
        allowed: false,
        reason: 'invalid-session',
        action: 'redirect',
        redirectTo: 'index.html',
        message: 'Tu sesión expiró o no es válida. Vuelve a iniciar sesión desde el portal.',
      };
    }
    if (!res.ok || !data.student) {
      clearSession();
      const backendMessage = typeof data.error === 'string' ? data.error : '';
      return {
        allowed: false,
        reason: 'invalid-session',
        action: 'redirect',
        redirectTo: 'index.html',
        message: backendMessage || 'No pudimos validar tu sesión. Ingresa desde el portal para continuar.',
      };
    }
    const student = data.student;
    const completed = Array.isArray(data.completed) ? data.completed : [];
    const currentSlug = getStoredSlug();
    if (!currentSlug || currentSlug !== initialSlug) {
      clearSession();
      return {
        allowed: false,
        reason: 'session-changed',
        action: 'redirect',
        redirectTo: 'index.html',
        message: 'Detectamos un cambio de sesión. Ingresa nuevamente desde el portal.',
      };
    }
    const canonicalSlug = student && student.slug ? student.slug : slug;
    const isAdminFlag =
      student && Object.prototype.hasOwnProperty.call(student, 'is_admin')
        ? student.is_admin
        : undefined;
    if (canonicalSlug && canonicalSlug !== currentSlug) {
      storeSession(canonicalSlug, token, isAdminFlag);
    } else if (typeof isAdminFlag !== 'undefined') {
      storeSession(currentSlug, token, isAdminFlag);
    }
    const missionsForRole = await fetchMissionsForRole(student ? student.role : '', token);
    const unlocked = calculateUnlockedMissions(missionsForRole, completed);
    const mission = missionsForRole.find(
      (m) => m && m.mission_id != null && String(m.mission_id) === missionId
    );
    if (!mission) {
      return {
        allowed: false,
        reason: 'not-for-role',
        action: 'message',
        message: 'Esta misión no está disponible para tu rol actual.',
      };
    }
    if (unlocked[missionId]) {
      return {
        allowed: true,
        reason: 'unlocked',
      };
    }
    clearSession();
    const missionIndex = missionsForRole.findIndex(
      (m) => m && m.mission_id != null && String(m.mission_id) === missionId
    );
    const previousMission = missionIndex > 0 ? missionsForRole[missionIndex - 1] : null;
    let message = 'Debes completar la misión anterior antes de continuar.';
    if (previousMission) {
      const previousTitle = previousMission.title || String(previousMission.mission_id || '');
      message = `Debes completar la misión ${previousTitle} antes de acceder a esta.`;
    }
    return {
      allowed: false,
      reason: 'locked',
      action: 'message',
      message,
    };
  } catch (err) {
    return {
      allowed: false,
      reason: 'network-error',
      action: 'message',
      message: 'No pudimos validar tu acceso. Intenta abrir la misión desde el portal nuevamente.',
    };
  }
}

/**
 * Verifica una misión desde una página de misión.
 * @param {string} missionId
 * @param {HTMLElement} resultContainer
 */
async function verifyMission(missionId, resultContainer) {
  const slug = getStoredSlug();
  const token = getStoredToken();
  if (!slug || !token) {
    clearSession();
    resultContainer.textContent = 'Debes volver a matricularte.';
    return;
  }
  resultContainer.textContent = 'Verificando...';
  try {
    const res = await apiFetch('/api/verify_mission', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ slug, mission_id: missionId }),
    });
    let data = {};
    try {
      data = await res.json();
    } catch (parseErr) {
      data = {};
    }
    if (res.status === 401) {
      clearSession();
      resultContainer.innerHTML =
        '<p class="error">Tu sesión expiró o es inválida. Vuelve a iniciar sesión en el portal.</p>';
      return;
    }
    if (res.ok) {
      if (data.verified) {
        resultContainer.innerHTML = `<p class="success">¡Misión verificada con éxito! Puedes volver al portal.</p>`;
      } else {
        let feedbackList = '<ul>';
        (data.feedback || []).forEach((msg) => {
          feedbackList += `<li>${msg}</li>`;
        });
        feedbackList += '</ul>';
        resultContainer.innerHTML = `<p class="fail">La verificación falló:</p>${feedbackList}`;
      }
    } else {
      resultContainer.innerHTML = `<p>Error: ${data.error || 'Verificación fallida.'}</p>`;
    }
  } catch (err) {
    resultContainer.textContent = 'Error de conexión durante la verificación.';
  }
}

function buildDeliverablesSummary(contract) {
  if (!contract || typeof contract !== 'object') {
    return null;
  }
  const deliverables = Array.isArray(contract.deliverables)
    ? contract.deliverables
    : [];
  if (deliverables.length === 0) {
    return null;
  }
  const section = document.createElement('section');
  section.className = 'mission-contract-summary';
  section.dataset.generated = 'deliverables';
  const heading = document.createElement('h3');
  heading.textContent = '📦 Resumen automático de entregables';
  section.appendChild(heading);
  const list = document.createElement('ul');
  deliverables.forEach((item) => {
    if (!item || typeof item !== 'object') {
      return;
    }
    const descriptionParts = [];
    const itemType = typeof item.type === 'string' ? item.type.trim() : '';
    const path = typeof item.path === 'string' ? item.path.trim() : '';
    if (itemType) {
      descriptionParts.push(itemType);
    }
    if (path) {
      descriptionParts.push(path);
    }
    if (descriptionParts.length === 0) {
      return;
    }
    const entry = document.createElement('li');
    entry.textContent = descriptionParts.join(' — ');
    list.appendChild(entry);
  });
  if (!list.children.length) {
    return null;
  }
  section.appendChild(list);
  return section;
}

function updateMissionHeader(mission) {
  const heading = document.querySelector('[data-mission-title]') || document.querySelector('.portal-header__heading');
  if (heading && mission && typeof mission.title === 'string' && mission.title.trim()) {
    heading.textContent = mission.title.trim();
  }
  if (mission && mission.title) {
    document.title = `${mission.title} — Portal de Misiones`;
  }
}

function renderLockedMission(message) {
  const container = document.querySelector('main');
  if (container) {
    container.removeAttribute('hidden');
    container.innerHTML = `
      <section class="status-error">
        <h2>Acceso restringido</h2>
        <p>${message || 'Debes abrir esta misión desde el portal principal.'}</p>
        <p><a href="index.html">Volver al portal</a></p>
      </section>
    `;
  } else {
    document.body.innerHTML = `
      <main class="mission-locked">
        <section class="status-error">
          <h2>Acceso restringido</h2>
          <p>${message || 'Debes abrir esta misión desde el portal principal.'}</p>
          <p><a href="index.html">Volver al portal</a></p>
        </section>
      </main>
    `;
  }
}

async function renderMissionContent(missionId) {
  const missionKey = typeof missionId === 'string' ? missionId.trim() : '';
  const mainElement = document.querySelector('main');
  if (!missionKey || !mainElement) {
    return;
  }
  try {
    const access = await ensureMissionUnlocked(missionKey);
    if (!access.allowed) {
      if (access.action === 'redirect' && access.redirectTo) {
        window.location.href = access.redirectTo;
        return;
      }
      renderLockedMission(access.message);
      return;
    }
    setCurrentMission(missionKey);
  } catch (err) {
    renderLockedMission('No pudimos validar tu acceso. Abre la misión desde el portal principal.');
    return;
  }

  const token = getStoredToken();
  const mission = await fetchMissionById(missionKey, token);
  if (!mission) {
    mainElement.removeAttribute('hidden');
    mainElement.innerHTML = `
      <section class="status-error">
        <p>No encontramos el contenido de esta misión. Intenta regresar al portal.</p>
        <p><a href="index.html">Volver al portal</a></p>
      </section>
    `;
    return;
  }

  updateMissionHeader(mission);

  const content = mission.content && typeof mission.content === 'object' ? mission.content : {};
  const displayHtml = typeof content.display_html === 'string' ? content.display_html : '';
  if (displayHtml) {
    mainElement.innerHTML = displayHtml;
  } else {
    mainElement.innerHTML = `
      <section class="status-info">
        <p>Esta misión aún no tiene contenido cargado. Contacta a tu mentor.</p>
      </section>
    `;
  }
  mainElement.removeAttribute('hidden');

  const verifyBtn = mainElement.querySelector('#verifyBtn');
  const resultContainer = mainElement.querySelector('#verifyResult');
  if (verifyBtn && resultContainer) {
    verifyBtn.addEventListener('click', () => {
      verifyMission(missionKey, resultContainer);
    });
  }

  const summarySection = buildDeliverablesSummary(content);
  if (summarySection) {
    mainElement.appendChild(summarySection);
  }
}

function setupAccessLinks() {
  const attachHandler = (elements, handler) => {
    elements.forEach((element) => {
      if (!element || element.dataset.accessHandlerBound === 'true') {
        return;
      }
      element.addEventListener('click', (event) => {
        event.preventDefault();
        handler(event, element);
      });
      element.dataset.accessHandlerBound = 'true';
    });
  };

  const enrollLinks = document.querySelectorAll('[data-action="enroll"]');
  attachHandler(enrollLinks, () => {
    clearSession();
    renderEnrollForm();
  });

  const loginLinks = document.querySelectorAll('[data-action="login"]');
  attachHandler(loginLinks, () => {
    clearSession();
    renderLoginForm();
  });

  const legacyEnrollLinks = document.querySelectorAll('a[href="m1.html"]');
  legacyEnrollLinks.forEach((link) => {
    link.href = '#';
  });
  attachHandler(legacyEnrollLinks, () => {
    clearSession();
    renderEnrollForm();
  });
}

function isLandingPage() {
  const path = typeof window !== 'undefined' && window.location ? window.location.pathname || '' : '';
  if (!path || path === '/') {
    return true;
  }
  const normalizedPath = path.toLowerCase();
  return normalizedPath.endsWith('/index.html') || normalizedPath.endsWith('index.html');
}

function initializeLandingView() {
  if (!isLandingPage()) {
    return;
  }
  const searchParams = new URLSearchParams(window.location.search);
  if (searchParams.has('enroll')) {
    clearSession();
    renderEnrollForm();
    return;
  }
  if (searchParams.has('login')) {
    clearSession();
    renderLoginForm();
    return;
  }
  const slug = getStoredSlug();
  const token = getStoredToken();
  if (slug && token) {
    loadDashboard();
    return;
  }
  clearSession();
  renderLandingContent();
}

if (typeof window !== 'undefined') {
  window.renderMissionContent = renderMissionContent;
}

document.addEventListener('DOMContentLoaded', () => {
  setupAccessLinks();
  initializeLandingView();
});

window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    initializeLandingView();
  }
});
