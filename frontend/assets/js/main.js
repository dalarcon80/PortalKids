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

const missionsCache = {
  all: [],
  byRole: new Map(),
  byId: new Map(),
};

function missionIdKey(id) {
  if (typeof id === 'string') {
    return id.trim();
  }
  if (typeof id === 'number') {
    return String(id).trim();
  }
  return '';
}

function invalidateMissionsCache() {
  missionsCache.all = [];
  missionsCache.byRole.clear();
  missionsCache.byId.clear();
}

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
  invalidateMissionsCache();
}

function calculateUnlockedMissions(missionsForRole, completed) {
  const unlocked = {};
  if (!Array.isArray(missionsForRole) || missionsForRole.length === 0) {
    return unlocked;
  }
  const completedSet = new Set(Array.isArray(completed) ? completed : []);
  unlocked[missionsForRole[0].id] = true;
  missionsForRole.forEach((mission, index) => {
    if (completedSet.has(mission.id)) {
      unlocked[mission.id] = true;
      if (index + 1 < missionsForRole.length) {
        unlocked[missionsForRole[index + 1].id] = true;
      }
    }
  });
  return unlocked;
}

function normalizeMissionRoles(rawRoles) {
  if (!rawRoles) {
    return [];
  }
  if (Array.isArray(rawRoles)) {
    return rawRoles
      .map((role) => (typeof role === 'string' || typeof role === 'number' ? String(role).trim() : ''))
      .filter((role) => role);
  }
  if (typeof rawRoles === 'string') {
    return rawRoles
      .split(/[,;\n]+/)
      .map((role) => role.trim())
      .filter((role) => role);
  }
  return [];
}

function normalizeMission(rawMission) {
  if (!rawMission) {
    return null;
  }
  const missionId = missionIdKey(rawMission.mission_id || rawMission.id);
  if (!missionId) {
    return null;
  }
  const rawTitle = rawMission.title || rawMission.name || '';
  const title = String(rawTitle || '').trim() || missionId;
  const roles = normalizeMissionRoles(rawMission.roles);
  const content = rawMission && typeof rawMission.content === 'object' && rawMission.content !== null
    ? rawMission.content
    : {};
  const updatedAt = rawMission.updated_at || rawMission.updatedAt || null;
  return {
    id: missionId,
    title,
    roles,
    content,
    updatedAt,
  };
}

function cacheMissionsList(rawMissions, roleKey) {
  const normalizedList = [];
  if (!Array.isArray(rawMissions)) {
    return normalizedList;
  }
  rawMissions.forEach((rawMission) => {
    const normalized = normalizeMission(rawMission);
    if (!normalized) {
      return;
    }
    const cacheKey = missionIdKey(normalized.id);
    if (cacheKey) {
      missionsCache.byId.set(cacheKey, normalized);
    }
    normalizedList.push(normalized);
  });
  if (typeof roleKey === 'string' && roleKey) {
    missionsCache.byRole.set(roleKey, normalizedList);
  } else if (!roleKey) {
    missionsCache.all = normalizedList;
  }
  return normalizedList;
}

function getCachedMissionsForRole(role) {
  const key = typeof role === 'string' ? role.trim().toLowerCase() : '';
  if (!key) {
    return [];
  }
  return missionsCache.byRole.get(key) || [];
}

function getMissionFromCache(missionId) {
  const key = missionIdKey(missionId);
  if (!key) {
    return null;
  }
  return missionsCache.byId.get(key) || null;
}

async function fetchMissionsForRole(role, options = {}) {
  const { forceRefresh = false } = options || {};
  const key = typeof role === 'string' ? role.trim().toLowerCase() : '';
  if (!forceRefresh && key && missionsCache.byRole.has(key)) {
    return missionsCache.byRole.get(key);
  }
  let url = '/api/missions';
  if (key) {
    url += `?${new URLSearchParams({ role: key })}`;
  }
  let res;
  try {
    res = await apiFetch(url, {
      credentials: 'include',
    });
  } catch (err) {
    throw new Error('network-error');
  }
  let data = {};
  try {
    data = await res.json();
  } catch (parseErr) {
    data = {};
  }
  if (!res.ok) {
    const error = new Error(data && data.error ? data.error : 'failed-to-load-missions');
    error.status = res.status;
    throw error;
  }
  const missions = Array.isArray(data.missions) ? data.missions : [];
  return cacheMissionsList(missions, key);
}

async function fetchAdminMissions() {
  const token = getStoredToken();
  if (!token) {
    const error = new Error('missing-session');
    error.code = 'missing-session';
    throw error;
  }
  let res;
  try {
    res = await apiFetch('/api/admin/missions', {
      method: 'GET',
      credentials: 'include',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  } catch (err) {
    const error = new Error('network-error');
    error.code = 'network-error';
    throw error;
  }
  let data = {};
  try {
    data = await res.json();
  } catch (parseErr) {
    data = {};
  }
  if (res.status === 401 || res.status === 403) {
    const error = new Error((data && data.error) || 'Unauthorized.');
    error.status = res.status;
    throw error;
  }
  if (!res.ok) {
    const error = new Error((data && data.error) || 'Failed to load missions.');
    error.status = res.status;
    throw error;
  }
  const missions = Array.isArray(data.missions) ? data.missions : [];
  return cacheMissionsList(missions);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeForTextarea(value) {
  return escapeHtml(value).replace(/<\/textarea>/gi, '&lt;/textarea&gt;');
}

function renderTextBlock(text) {
  if (!text && text !== 0) {
    return '';
  }
  const raw = Array.isArray(text) ? text : String(text).split(/\n+/);
  const paragraphs = raw
    .map((item) => (typeof item === 'string' || typeof item === 'number' ? String(item).trim() : ''))
    .filter((line) => line);
  if (paragraphs.length === 0) {
    return '';
  }
  return paragraphs.map((line) => `<p>${escapeHtml(line)}</p>`).join('');
}

function renderBulletList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return '';
  }
  const listItems = items
    .map((item) => {
      if (item && typeof item === 'object' && 'text' in item) {
        return `<li>${escapeHtml(String(item.text || '').trim())}</li>`;
      }
      if (typeof item === 'string' || typeof item === 'number') {
        return `<li>${escapeHtml(String(item))}</li>`;
      }
      if (item && typeof item === 'object') {
        return `<li><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></li>`;
      }
      return '';
    })
    .filter((entry) => entry);
  if (listItems.length === 0) {
    return '';
  }
  return `<ul>${listItems.join('')}</ul>`;
}

function renderDeliverablesSection(deliverables) {
  if (!Array.isArray(deliverables) || deliverables.length === 0) {
    return '';
  }
  const items = deliverables
    .map((deliverable) => {
      if (!deliverable || typeof deliverable !== 'object') {
        return '';
      }
      const details = [];
      if (deliverable.path) {
        details.push(`<span class="mission-detail__field"><strong>Ruta:</strong> ${escapeHtml(deliverable.path)}</span>`);
      }
      if (deliverable.type) {
        details.push(`<span class="mission-detail__field"><strong>Tipo:</strong> ${escapeHtml(deliverable.type)}</span>`);
      }
      if (deliverable.content) {
        details.push(`<span class="mission-detail__field"><strong>Contenido esperado:</strong> ${escapeHtml(String(deliverable.content))}</span>`);
      }
      if (deliverable.feedback_fail) {
        details.push(
          `<span class="mission-detail__field"><strong>Feedback si falla:</strong> ${escapeHtml(deliverable.feedback_fail)}</span>`
        );
      }
      if (details.length === 0) {
        return '';
      }
      return `<li>${details.join('<br />')}</li>`;
    })
    .filter((item) => item);
  if (items.length === 0) {
    return '';
  }
  return `
    <section class="mission-section mission-section--deliverables">
      <h3>Entregables</h3>
      <ul>
        ${items.join('')}
      </ul>
    </section>
  `;
}

function renderValidationsSection(validations) {
  if (!Array.isArray(validations) || validations.length === 0) {
    return '';
  }
  const items = validations
    .map((validation) => {
      if (!validation || typeof validation !== 'object') {
        return '';
      }
      const parts = [];
      if (validation.type) {
        parts.push(`<span class="mission-detail__field"><strong>Tipo:</strong> ${escapeHtml(validation.type)}</span>`);
      }
      if (validation.text) {
        parts.push(`<span class="mission-detail__field"><strong>Texto:</strong> ${escapeHtml(validation.text)}</span>`);
      }
      if (validation.path) {
        parts.push(`<span class="mission-detail__field"><strong>Ruta:</strong> ${escapeHtml(validation.path)}</span>`);
      }
      if (validation.feedback_fail) {
        parts.push(
          `<span class="mission-detail__field"><strong>Feedback si falla:</strong> ${escapeHtml(validation.feedback_fail)}</span>`
        );
      }
      if (parts.length === 0) {
        return '';
      }
      return `<li>${parts.join('<br />')}</li>`;
    })
    .filter((entry) => entry);
  if (items.length === 0) {
    return '';
  }
  return `
    <section class="mission-section mission-section--validations">
      <h3>Validaciones</h3>
      <ul>
        ${items.join('')}
      </ul>
    </section>
  `;
}

function renderMissionContent(content) {
  if (!content || typeof content !== 'object') {
    return '<p>No hay contenido configurado para esta misión.</p>';
  }
  const parts = [];
  if (typeof content.html === 'string' && content.html.trim()) {
    parts.push(content.html);
  }
  if (content.story) {
    parts.push(`<section class="mission-section"><h3>Historia</h3>${renderTextBlock(content.story)}</section>`);
  }
  if (content.summary) {
    parts.push(`<section class="mission-section"><h3>Resumen</h3>${renderTextBlock(content.summary)}</section>`);
  }
  if (content.instructions) {
    parts.push(
      `<section class="mission-section"><h3>Instrucciones</h3>${renderTextBlock(content.instructions)}</section>`
    );
  }
  if (Array.isArray(content.sections)) {
    content.sections.forEach((section) => {
      if (!section || typeof section !== 'object') {
        return;
      }
      const title = section.title || section.heading || '';
      const sectionParts = [];
      if (section.body) {
        sectionParts.push(renderTextBlock(section.body));
      }
      if (section.description) {
        sectionParts.push(renderTextBlock(section.description));
      }
      if (section.items) {
        sectionParts.push(renderBulletList(section.items));
      }
      if (section.html) {
        sectionParts.push(section.html);
      }
      if (sectionParts.length === 0) {
        sectionParts.push(`<pre>${escapeHtml(JSON.stringify(section, null, 2))}</pre>`);
      }
      parts.push(
        `<section class="mission-section">${title ? `<h3>${escapeHtml(title)}</h3>` : ''}${sectionParts.join('')}</section>`
      );
    });
  }
  if (content.resources) {
    parts.push(
      `<section class="mission-section"><h3>Recursos</h3>${renderBulletList(Array.isArray(content.resources) ? content.resources : [content.resources])}</section>`
    );
  }
  const deliverables = renderDeliverablesSection(content.deliverables);
  if (deliverables) {
    parts.push(deliverables);
  }
  const validations = renderValidationsSection(content.validations);
  if (validations) {
    parts.push(validations);
  }
  if (content.verification_type) {
    parts.push(
      `<p class="mission-detail__field"><strong>Tipo de verificación:</strong> ${escapeHtml(content.verification_type)}</p>`
    );
  }
  if (content.script_path) {
    parts.push(
      `<p class="mission-detail__field"><strong>Script de verificación:</strong> ${escapeHtml(content.script_path)}</p>`
    );
  }
  if (content.source) {
    parts.push(
      `<details class="mission-section mission-section--source"><summary>Fuente de datos</summary><pre>${escapeHtml(
        JSON.stringify(content.source, null, 2)
      )}</pre></details>`
    );
  }
  if (parts.length === 0) {
    return `<pre>${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
  }
  parts.push(
    `<details class="mission-section mission-section--raw"><summary>Ver JSON bruto</summary><pre>${escapeHtml(
      JSON.stringify(content, null, 2)
    )}</pre></details>`
  );
  return parts.join('');
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
  const content = getContentContainer();
  if (!landingContentHTML) {
    content.innerHTML = '';
    return;
  }
  content.innerHTML = landingContentHTML;
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
    let missionsForRole = [];
    try {
      missionsForRole = await fetchMissionsForRole(student.role, { forceRefresh: true });
    } catch (missionsError) {
      let errorMessage = 'No pudimos cargar las misiones configuradas en este momento.';
      if (missionsError && missionsError.message && missionsError.message !== 'network-error') {
        if (missionsError.message === 'failed-to-load-missions') {
          errorMessage = 'No pudimos obtener la lista de misiones.';
        } else {
          errorMessage = missionsError.message;
        }
      }
      content.innerHTML = `
        <section class="status-error">
          <p>${escapeHtml(errorMessage)}</p>
          <button id="retryMissionsBtn">Reintentar</button>
        </section>
      `;
      const retryMissionsBtn = $('#retryMissionsBtn');
      if (retryMissionsBtn) {
        retryMissionsBtn.onclick = () => {
          loadDashboard();
        };
      }
      return;
    }
    const unlockedMap = calculateUnlockedMissions(missionsForRole, completed);
    const storedMissionId = getCurrentMission();
    if (storedMissionId) {
      const missionFromCache =
        missionsForRole.find((mission) => mission.id === storedMissionId) ||
        getMissionFromCache(storedMissionId);
      if (missionFromCache && unlockedMap[storedMissionId]) {
        renderMissionDetail(missionFromCache, { student, completed });
        return;
      }
      if (!missionFromCache || !unlockedMap[storedMissionId]) {
        clearCurrentMission();
      }
    }
    renderDashboard(student, completed, missionsForRole);
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
 * @param {string[]} completed
 */
function renderDashboard(student, completed, missions) {
  const content = $('#content');
  const safeCompleted = Array.isArray(completed) ? completed : [];
  const missionsForRole = Array.isArray(missions) && missions.length > 0
    ? missions
    : getCachedMissionsForRole(student.role);
  const unlocked = calculateUnlockedMissions(missionsForRole, safeCompleted);
  const isAdmin = Boolean(getStoredIsAdmin());
  const roleLabel = student && student.role ? String(student.role) : '';
  const nameLabel = student && student.name ? String(student.name) : '';
  let html = `<section class="dashboard">
    <h2>Bienvenido, ${escapeHtml(nameLabel)}</h2>
    <p>Rol: ${escapeHtml(roleLabel)}</p>
    <p>Selecciona una misión para continuar:</p>
    <div class="dashboard-message" id="dashboardMessage" role="status" aria-live="polite"></div>`;
  if (missionsForRole.length === 0) {
    html += `<p class="no-missions">No hay misiones configuradas para tu rol en este momento.</p>`;
  } else {
    html += '<ul class="missions-grid">';
    missionsForRole.forEach((mission) => {
      const missionId = mission.id;
      const missionTitle = mission.title || missionId;
      const isCompleted = safeCompleted.includes(missionId);
      const isUnlocked = Boolean(unlocked[missionId]);
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
      const missionTitleHtml = `<span class="mission-title">${escapeHtml(missionTitle)}</span>`;
      if (isUnlocked) {
        html += `
          <li class="mission-card ${statusClass}">
            <button type="button" class="mission-card__link" data-mission-id="${escapeHtml(missionId)}">
              ${missionTitleHtml}
            </button>
            <span class="status">${statusText}</span>
          </li>`;
      } else {
        html += `
          <li class="mission-card ${statusClass}">
            ${missionTitleHtml}
            <span class="status">${statusText}</span>
          </li>`;
      }
    });
    html += '</ul>';
  }
  html += '<div class="dashboard-actions">';
  if (isAdmin) {
    html += '<button type="button" id="adminMissionsBtn">Configurar misiones</button>';
  }
  html += '<button type="button" id="logoutBtn">Salir</button>';
  html += '</div>';
  html += '</section>';
  content.innerHTML = html;

  const logoutBtn = $('#logoutBtn');
  if (logoutBtn) {
    logoutBtn.onclick = () => {
      clearSession();
      clearCurrentMission();
      renderLandingContent();
    };
  }

  const adminBtn = $('#adminMissionsBtn');
  if (adminBtn) {
    adminBtn.onclick = () => {
      renderAdminMissionsView();
    };
  }

  const missionButtons = content.querySelectorAll('[data-mission-id]');
  const messageBox = $('#dashboardMessage');
  missionButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      const missionId = button.getAttribute('data-mission-id');
      if (!missionId) {
        return;
      }
      if (!unlocked[missionId]) {
        if (messageBox) {
          const missionIndex = missionsForRole.findIndex((mission) => mission.id === missionId);
          const previousMission = missionIndex > 0 ? missionsForRole[missionIndex - 1] : null;
          const previousLabel = previousMission ? previousMission.title || previousMission.id : '';
          const lockedMessage = previousLabel
            ? `Debes completar la misión "${previousLabel}" antes de acceder a esta.`
            : 'Debes completar la misión anterior antes de acceder a esta.';
          messageBox.textContent = lockedMessage;
        }
        return;
      }
      const mission = missionsForRole.find((item) => item.id === missionId) || getMissionFromCache(missionId);
      if (!mission) {
        if (messageBox) {
          messageBox.textContent = 'No pudimos encontrar la información de esa misión. Intenta recargar.';
        }
        return;
      }
      setCurrentMission(missionId);
      renderMissionDetail(mission, { student, completed: safeCompleted });
    });
  });
}

function renderMissionDetail(mission, options = {}) {
  if (!mission) {
    return;
  }
  const { student = null, completed = [] } = options || {};
  const content = $('#content');
  const rolesLabel = mission.roles && mission.roles.length > 0
    ? mission.roles.join(', ')
    : 'Todos los roles';
  const isCompleted = Array.isArray(completed) && completed.includes(mission.id);
  const missionStatus = isCompleted ? 'Completada' : 'Pendiente';
  const updatedLabel = mission.updatedAt ? `Última actualización: ${escapeHtml(mission.updatedAt)}` : '';
  const studentName = student && student.name ? escapeHtml(String(student.name)) : '';
  const studentRole = student && student.role ? escapeHtml(String(student.role)) : '';
  let studentInfoHtml = '';
  if (studentName || studentRole) {
    const parts = [];
    if (studentName) {
      parts.push(`Estudiante: ${studentName}`);
    }
    if (studentRole) {
      parts.push(`Rol: ${studentRole}`);
    }
    studentInfoHtml = `<p class="mission-detail__student">${parts.join(' · ')}</p>`;
  }
  const missionContent = renderMissionContent(mission.content);
  content.innerHTML = `
    <section class="mission-detail">
      <header class="mission-detail__header">
        <button type="button" id="backToDashboardBtn" class="mission-detail__back">← Volver al portal</button>
        <h2>${escapeHtml(mission.title || mission.id)}</h2>
        <p class="mission-detail__meta">
          <span><strong>ID:</strong> ${escapeHtml(mission.id)}</span>
          <span><strong>Estado:</strong> ${escapeHtml(missionStatus)}</span>
          <span><strong>Roles:</strong> ${escapeHtml(rolesLabel)}</span>
          ${updatedLabel ? `<span>${updatedLabel}</span>` : ''}
        </p>
        ${studentInfoHtml}
      </header>
      <article class="mission-detail__content">
        ${missionContent}
      </article>
      <footer class="mission-detail__footer">
        <button type="button" id="verifyMissionBtn" class="mission-detail__verify">Verificar misión</button>
        <div id="missionVerifyResult" class="mission-detail__result" aria-live="polite"></div>
      </footer>
    </section>
  `;
  const backBtn = $('#backToDashboardBtn');
  if (backBtn) {
    backBtn.onclick = () => {
      clearCurrentMission();
      loadDashboard();
    };
  }
  const verifyBtn = $('#verifyMissionBtn');
  const resultContainer = $('#missionVerifyResult');
  if (verifyBtn && resultContainer) {
    verifyBtn.onclick = () => {
      verifyMission(mission.id, resultContainer);
    };
  }
}

async function renderAdminMissionsView() {
  const content = getContentContainer();
  const token = getStoredToken();
  if (!token) {
    clearSession();
    renderLoginForm();
    return;
  }
  content.innerHTML = `
    <section class="admin-missions admin-missions--loading">
      <h2>Configurar misiones</h2>
      <p>Cargando misiones...</p>
    </section>
  `;
  let missions = [];
  try {
    missions = await fetchAdminMissions();
  } catch (error) {
    if (error && (error.status === 401 || error.status === 403)) {
      clearSession();
      content.innerHTML = `
        <section class="admin-missions admin-missions--error">
          <h2>Configurar misiones</h2>
          <p>No tienes permisos para acceder a esta sección o tu sesión expiró.</p>
          <div class="admin-missions__actions">
            <button type="button" id="adminLoginBtn">Iniciar sesión</button>
          </div>
        </section>
      `;
      const loginBtn = $('#adminLoginBtn');
      if (loginBtn) {
        loginBtn.onclick = () => {
          renderLoginForm();
        };
      }
      return;
    }
    content.innerHTML = `
      <section class="admin-missions admin-missions--error">
        <h2>Configurar misiones</h2>
        <p>No pudimos cargar la lista de misiones. Intenta nuevamente.</p>
        <div class="admin-missions__actions">
          <button type="button" id="adminRetryBtn">Reintentar</button>
          <button type="button" id="adminBackBtn">Volver</button>
        </div>
      </section>
    `;
    const retryBtn = $('#adminRetryBtn');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderAdminMissionsView();
      };
    }
    const backBtn = $('#adminBackBtn');
    if (backBtn) {
      backBtn.onclick = () => {
        loadDashboard();
      };
    }
    return;
  }
  const missionsToRender = Array.isArray(missions) ? [...missions] : [];
  missionsToRender.sort((a, b) => a.id.localeCompare(b.id, 'es', { numeric: true, sensitivity: 'base' }));
  const adminWarning = getStoredIsAdmin()
    ? ''
    : '<p class="admin-missions__warning">Tu sesión actual no tiene la marca de administrador guardada localmente. Si ves errores de permisos, vuelve a iniciar sesión.</p>';
  content.innerHTML = `
    <section class="admin-missions">
      <header class="admin-missions__header">
        <h2>Configurar misiones</h2>
        <div class="admin-missions__header-actions">
          <button type="button" id="adminBackBtn">Volver al portal</button>
          <button type="button" id="adminReloadBtn">Recargar</button>
        </div>
      </header>
      ${adminWarning}
      <p class="admin-missions__summary">${missionsToRender.length} misión(es) configuradas.</p>
      <div id="adminMissionsList" class="admin-missions__list"></div>
      <section class="admin-missions__create">
        <h3>Crear nueva misión</h3>
        <form id="adminCreateMissionForm" class="admin-mission-form admin-mission-form--create">
          <label>Identificador<br /><input type="text" name="mission_id" required /></label>
          <label>Título<br /><input type="text" name="title" /></label>
          <label>Roles permitidos<br /><input type="text" name="roles" placeholder="Ej. ventas, operaciones" /></label>
          <label>Contenido (JSON)<br /><textarea name="content" rows="8" placeholder="{ }"></textarea></label>
          <div class="admin-mission-form__actions">
            <button type="submit">Crear misión</button>
            <span class="admin-mission-form__status" aria-live="polite"></span>
          </div>
        </form>
      </section>
    </section>
  `;

  const backBtn = $('#adminBackBtn');
  if (backBtn) {
    backBtn.onclick = () => {
      loadDashboard();
    };
  }
  const reloadBtn = $('#adminReloadBtn');
  if (reloadBtn) {
    reloadBtn.onclick = () => {
      renderAdminMissionsView();
    };
  }

  const missionsList = $('#adminMissionsList');
  if (missionsList) {
    missionsToRender.forEach((mission) => {
      const form = document.createElement('form');
      form.className = 'admin-mission-form';
      form.dataset.missionId = mission.id;
      const rolesValue = mission.roles && mission.roles.length > 0 ? mission.roles.join(', ') : '';
      const updatedInfo = mission.updatedAt ? `<p class="admin-mission-form__meta">Actualizado: ${escapeHtml(mission.updatedAt)}</p>` : '';
      const contentJson = JSON.stringify(mission.content || {}, null, 2);
      form.innerHTML = `
        <fieldset>
          <legend>${escapeHtml(mission.title || mission.id)} (${escapeHtml(mission.id)})</legend>
          ${updatedInfo}
          <label>Identificador<br /><input type="text" value="${escapeHtml(mission.id)}" disabled /></label>
          <label>Título<br /><input type="text" name="title" value="${escapeHtml(mission.title || '')}" /></label>
          <label>Roles permitidos<br /><input type="text" name="roles" value="${escapeHtml(rolesValue)}" placeholder="Separados por comas" /></label>
          <label>Contenido (JSON)<br /><textarea name="content" rows="8">${escapeForTextarea(contentJson)}</textarea></label>
        </fieldset>
        <div class="admin-mission-form__actions">
          <button type="submit">Guardar cambios</button>
          <span class="admin-mission-form__status" aria-live="polite"></span>
        </div>
      `;
      missionsList.appendChild(form);
    });
  }

  const disableFormControls = (form, disabled) => {
    const controls = form.querySelectorAll('input, textarea, button');
    controls.forEach((control) => {
      control.disabled = disabled;
    });
  };

  const handleUpdateSubmit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const missionId = form.dataset.missionId;
    if (!missionId) {
      return;
    }
    const statusEl = form.querySelector('.admin-mission-form__status');
    const titleInput = form.querySelector('input[name="title"]');
    const rolesInput = form.querySelector('input[name="roles"]');
    const contentTextarea = form.querySelector('textarea[name="content"]');
    if (!statusEl || !titleInput || !rolesInput || !contentTextarea) {
      return;
    }
    let contentPayload;
    try {
      const rawValue = contentTextarea.value && contentTextarea.value.trim() ? contentTextarea.value : '{}';
      contentPayload = JSON.parse(rawValue);
    } catch (parseErr) {
      statusEl.textContent = 'El contenido debe ser un JSON válido.';
      return;
    }
    const rolesPayload = normalizeMissionRoles(rolesInput.value);
    const payload = {
      title: titleInput.value,
      roles: rolesPayload,
      content: contentPayload,
    };
    const authToken = getStoredToken();
    if (!authToken) {
      clearSession();
      renderLoginForm();
      return;
    }
    disableFormControls(form, true);
    statusEl.textContent = 'Guardando cambios...';
    let response;
    try {
      response = await apiFetch(`/api/admin/missions/${encodeURIComponent(missionId)}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(payload),
      });
    } catch (networkErr) {
      statusEl.textContent = 'Error de red al guardar los cambios.';
      disableFormControls(form, false);
      return;
    }
    let responseData = {};
    try {
      responseData = await response.json();
    } catch (parseErr) {
      responseData = {};
    }
    if (response.status === 401 || response.status === 403) {
      clearSession();
      renderLoginForm();
      return;
    }
    if (!response.ok) {
      const backendError = responseData && typeof responseData.error === 'string' ? responseData.error : '';
      statusEl.textContent = backendError || 'No pudimos guardar los cambios.';
      disableFormControls(form, false);
      return;
    }
    statusEl.textContent = 'Cambios guardados. Actualizando...';
    invalidateMissionsCache();
    setTimeout(() => {
      renderAdminMissionsView();
    }, 500);
  };

  const missionForms = content.querySelectorAll('.admin-mission-form[data-mission-id]');
  missionForms.forEach((form) => {
    form.addEventListener('submit', handleUpdateSubmit);
  });

  const createForm = $('#adminCreateMissionForm');
  if (createForm) {
    createForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!(createForm instanceof HTMLFormElement)) {
        return;
      }
      const statusEl = createForm.querySelector('.admin-mission-form__status');
      const idInput = createForm.querySelector('input[name="mission_id"]');
      const titleInput = createForm.querySelector('input[name="title"]');
      const rolesInput = createForm.querySelector('input[name="roles"]');
      const contentTextarea = createForm.querySelector('textarea[name="content"]');
      if (!statusEl || !idInput || !titleInput || !rolesInput || !contentTextarea) {
        return;
      }
      const missionId = missionIdKey(idInput.value);
      if (!missionId) {
        statusEl.textContent = 'Debes indicar un identificador para la misión.';
        return;
      }
      let contentPayload;
      try {
        const rawValue = contentTextarea.value && contentTextarea.value.trim() ? contentTextarea.value : '{}';
        contentPayload = JSON.parse(rawValue);
      } catch (parseErr) {
        statusEl.textContent = 'El contenido debe ser un JSON válido.';
        return;
      }
      const payload = {
        mission_id: missionId,
        title: titleInput.value,
        roles: normalizeMissionRoles(rolesInput.value),
        content: contentPayload,
      };
      const authToken = getStoredToken();
      if (!authToken) {
        clearSession();
        renderLoginForm();
        return;
      }
      disableFormControls(createForm, true);
      statusEl.textContent = 'Creando misión...';
      let response;
      try {
        response = await apiFetch('/api/admin/missions', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify(payload),
        });
      } catch (networkErr) {
        statusEl.textContent = 'Error de red al crear la misión.';
        disableFormControls(createForm, false);
        return;
      }
      let responseData = {};
      try {
        responseData = await response.json();
      } catch (parseErr) {
        responseData = {};
      }
      if (response.status === 401 || response.status === 403) {
        clearSession();
        renderLoginForm();
        return;
      }
      if (!response.ok) {
        const backendError = responseData && typeof responseData.error === 'string' ? responseData.error : '';
        statusEl.textContent = backendError || 'No pudimos crear la misión.';
        disableFormControls(createForm, false);
        return;
      }
      statusEl.textContent = 'Misión creada correctamente. Actualizando...';
      invalidateMissionsCache();
      setTimeout(() => {
        renderAdminMissionsView();
      }, 500);
    });
  }
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
    let missionsForRole = [];
    try {
      missionsForRole = await fetchMissionsForRole(student.role);
    } catch (missionsError) {
      return {
        allowed: false,
        reason: 'missions-unavailable',
        action: 'message',
        message: 'No pudimos obtener la configuración de misiones para tu rol en este momento.',
      };
    }
    const unlocked = calculateUnlockedMissions(missionsForRole, completed);
    const mission = missionsForRole.find((m) => m.id === missionId);
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
    const missionIndex = missionsForRole.findIndex((m) => m.id === missionId);
    const previousMission = missionIndex > 0 ? missionsForRole[missionIndex - 1] : null;
    let message = 'Debes completar la misión anterior antes de continuar.';
    if (previousMission) {
      message = `Debes completar la misión ${previousMission.title} antes de acceder a esta.`;
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

document.addEventListener('DOMContentLoaded', () => {
  setupAccessLinks();
  initializeLandingView();
});

window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    initializeLandingView();
  }
});
