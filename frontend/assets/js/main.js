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
}

const ADMIN_AVAILABLE_ROLES = ['Ventas', 'Operaciones'];

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
  const missionsArray = Array.isArray(missions) ? missions : [];
  const missionsForRole = missionsArray.filter((mission) => {
    if (!mission || mission.mission_id == null) {
      return false;
    }
    const missionRoles = Array.isArray(mission.roles)
      ? mission.roles.filter((role) => typeof role === 'string' && role)
      : [];
    if (missionRoles.length === 0) {
      return true;
    }
    if (!studentRole) {
      return false;
    }
    return missionRoles.includes(studentRole);
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
  if (isAdmin) {
    html += '<button id="missionAdminBtn">Configurar misiones</button>';
  }
  html += '<button id="logoutBtn">Salir</button>';
  html += '</div>';
  html += '</section>';
  content.innerHTML = html;
  $('#logoutBtn').onclick = () => {
    clearSession();
    renderLandingContent();
  };
  if (isAdmin) {
    const missionAdminBtn = $('#missionAdminBtn');
    if (missionAdminBtn) {
      missionAdminBtn.onclick = () => {
        renderMissionAdminPanel();
      };
    }
  }
}

async function renderMissionAdminPanel() {
  const slug = getStoredSlug();
  const token = getStoredToken();
  const isAdmin = getStoredIsAdmin();
  if (!slug || !token || !_normalizeBooleanFlag(isAdmin)) {
    clearSession();
    renderLoginForm();
    return;
  }
  const content = $('#content');
  content.innerHTML = `
    <section class="mission-admin">
      <h2>Configuración de misiones</h2>
      <p>Cargando misiones disponibles...</p>
    </section>
  `;
  let missions = [];
  try {
    const headers = {
      Authorization: `Bearer ${token}`,
    };
    const res = await apiFetch('/api/admin/missions', {
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
      content.innerHTML = `
        <section class="status-error">
          <p>Tu sesión expiró. Vuelve a iniciar sesión para continuar.</p>
          <button id="adminLoginBtn">Iniciar sesión</button>
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
    if (res.status === 403) {
      content.innerHTML = `
        <section class="status-error">
          <p>No tienes permisos para configurar misiones.</p>
          <button id="backToDashboardBtn">Volver</button>
        </section>
      `;
      const backBtn = $('#backToDashboardBtn');
      if (backBtn) {
        backBtn.onclick = () => {
          const storedSlug = getStoredSlug();
          const storedToken = getStoredToken();
          const storedAdmin = getStoredIsAdmin();
          if (storedSlug) {
            storeSession(storedSlug, storedToken, storedAdmin);
          }
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
    content.innerHTML = `
      <section class="status-error">
        <p>${err && err.message ? err.message : 'Ocurrió un error al cargar las misiones.'}</p>
        <button id="retryMissionAdminBtn">Reintentar</button>
      </section>
    `;
    const retryBtn = $('#retryMissionAdminBtn');
    if (retryBtn) {
      retryBtn.onclick = () => {
        renderMissionAdminPanel();
      };
    }
    return;
  }

  const missionOptions = missions
    .map((mission) => {
      const missionId = mission && mission.mission_id ? String(mission.mission_id) : '';
      if (!missionId) {
        return '';
      }
      return `<option value="${missionId}">${missionId}</option>`;
    })
    .join('');
  const roleOptions = [...ADMIN_AVAILABLE_ROLES];
  missions.forEach((mission) => {
    const missionRoles = Array.isArray(mission.roles) ? mission.roles : [];
    missionRoles.forEach((role) => {
      const normalizedRole = typeof role === 'string' ? role : '';
      if (normalizedRole && !roleOptions.includes(normalizedRole)) {
        roleOptions.push(normalizedRole);
      }
    });
  });
  const rolesCheckboxes = roleOptions
    .map(
      (role) =>
        `<label><input type="checkbox" class="mission-role-option" value="${role}"> ${role}</label>`
    )
    .join('');

  content.innerHTML = `
    <section class="mission-admin">
      <h2>Configuración de misiones</h2>
      <div class="mission-admin-selector">
        <label for="missionAdminSelect">Misiones disponibles</label>
        <select id="missionAdminSelect">
          <option value="">Selecciona una misión</option>
          ${missionOptions}
        </select>
      </div>
      <form id="missionAdminForm" class="mission-admin-form">
        <div class="form-field">
          <label for="missionTitleInput">Título</label>
          <input type="text" id="missionTitleInput" name="title">
        </div>
        <fieldset class="form-field">
          <legend>Roles disponibles</legend>
          <div class="mission-role-options">${rolesCheckboxes}</div>
        </fieldset>
        <div class="form-field">
          <label for="missionContentInput">Contenido (JSON)</label>
          <textarea id="missionContentInput" rows="12"></textarea>
        </div>
        <div id="missionAdminFeedback" class="mission-admin-feedback"></div>
        <div class="mission-admin-actions">
          <button type="submit" id="missionAdminSaveBtn">Guardar cambios</button>
          <button type="button" id="missionAdminBackBtn">Volver al dashboard</button>
        </div>
      </form>
    </section>
  `;

  const missionSelect = $('#missionAdminSelect');
  const missionTitleInput = $('#missionTitleInput');
  const missionContentInput = $('#missionContentInput');
  const feedbackContainer = $('#missionAdminFeedback');
  const saveButton = $('#missionAdminSaveBtn');
  const roleInputs = Array.from(
    document.querySelectorAll('.mission-role-option')
  );

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
    feedbackContainer.innerHTML = `<div class="${typeClass}">${message}</div>`;
  }

  function fillMissionForm(missionId) {
    const mission = missions.find((m) => m.mission_id === missionId);
    if (!mission) {
      if (missionTitleInput) {
        missionTitleInput.value = '';
      }
      if (missionContentInput) {
        missionContentInput.value = '';
      }
      roleInputs.forEach((input) => {
        input.checked = false;
      });
      return;
    }
    if (missionTitleInput) {
      missionTitleInput.value = mission.title || '';
    }
    const normalizedRoles = Array.isArray(mission.roles) ? mission.roles : [];
    roleInputs.forEach((input) => {
      input.checked = normalizedRoles.includes(input.value);
    });
    if (missionContentInput) {
      const contentValue =
        mission.content && typeof mission.content === 'object' ? mission.content : {};
      missionContentInput.value = JSON.stringify(contentValue, null, 2);
    }
    showFeedback('', 'info');
  }

  if (missionSelect) {
    missionSelect.onchange = () => {
      const selectedId = missionSelect.value;
      fillMissionForm(selectedId);
    };
  }

  if (missions.length > 0 && missionSelect) {
    const firstMissionId =
      missions[0] && missions[0].mission_id ? String(missions[0].mission_id) : '';
    if (firstMissionId) {
      missionSelect.value = firstMissionId;
      fillMissionForm(firstMissionId);
    }
    if (saveButton) {
      saveButton.disabled = false;
    }
  } else if (saveButton) {
    saveButton.disabled = true;
    showFeedback('No hay misiones disponibles para editar.', 'info');
  }

  const missionForm = $('#missionAdminForm');
  if (missionForm) {
    missionForm.onsubmit = async (event) => {
      event.preventDefault();
      const missionId = missionSelect ? missionSelect.value : '';
      if (!missionId) {
        showFeedback('Selecciona una misión antes de guardar.', 'error');
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
      let parsedContent = null;
      try {
        parsedContent = missionContentInput ? JSON.parse(missionContentInput.value || '{}') : {};
      } catch (parseError) {
        showFeedback('El contenido debe ser un JSON válido.', 'error');
        return;
      }
      if (parsedContent === null || typeof parsedContent !== 'object' || Array.isArray(parsedContent)) {
        showFeedback('El contenido debe ser un objeto JSON.', 'error');
        return;
      }
      payload.content = parsedContent;
      showFeedback('Guardando cambios...', 'info');
      try {
        const res = await apiFetch(`/api/admin/missions/${encodeURIComponent(missionId)}`, {
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
          throw new Error(backendMessage || 'No pudimos guardar los cambios de la misión.');
        }
        const updatedMission = data.mission;
        if (updatedMission) {
          const index = missions.findIndex((m) => m.mission_id === missionId);
          if (index !== -1) {
            missions[index] = updatedMission;
          }
          fillMissionForm(missionId);
        }
        showFeedback('Los cambios se guardaron correctamente.', 'success');
        setTimeout(() => {
          const storedSlug = getStoredSlug();
          const storedToken = getStoredToken();
          const storedAdmin = getStoredIsAdmin();
          if (storedSlug) {
            storeSession(storedSlug, storedToken, storedAdmin);
          }
          loadDashboard();
        }, 800);
      } catch (saveError) {
        showFeedback(
          saveError && saveError.message
            ? saveError.message
            : 'Ocurrió un error al guardar los cambios.',
          'error'
        );
      }
    };
  }

  const backBtn = $('#missionAdminBackBtn');
  if (backBtn) {
    backBtn.onclick = () => {
      const storedSlug = getStoredSlug();
      const storedToken = getStoredToken();
      const storedAdmin = getStoredIsAdmin();
      if (storedSlug) {
        storeSession(storedSlug, storedToken, storedAdmin);
      }
      loadDashboard();
    };
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
