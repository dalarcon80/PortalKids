// main.js - lógica del portal de misiones

const API_BASE = '';
const STORAGE_KEYS = {
  slug: 'student_slug',
  token: 'session_token',
};

const MISSION_CONFIG_KEY = 'mission_visibility';

const MISSIONS = [
  { id: 'm1', title: 'M1 — La Puerta de la Base', roles: ['Ventas', 'Operaciones'] },
  { id: 'm2', title: 'M2 — Despierta a tu Aliado', roles: ['Ventas', 'Operaciones'] },
  { id: 'm3', title: 'M3 — Cofres CSV y DataFrames', roles: ['Ventas', 'Operaciones'] },
  { id: 'm4', title: 'M4 — Bronze: Ingesta y Copia fiel', roles: ['Ventas', 'Operaciones'] },
  { id: 'm5', title: 'M5 — Silver: Limpieza y Tipos', roles: ['Ventas', 'Operaciones'] },
  { id: 'm6v', title: 'M6 — Gold (VENTAS): Une y mide', roles: ['Ventas'] },
  { id: 'm6o', title: 'M6 — Gold (OPERACIONES): Une y mide', roles: ['Operaciones'] },
  { id: 'm7', title: 'M7 — Consejo de la Tienda', roles: ['Ventas', 'Operaciones'] },
];

function storeSession(slug, token) {
  if (slug) {
    localStorage.setItem(STORAGE_KEYS.slug, slug);
  }
  if (token) {
    localStorage.setItem(STORAGE_KEYS.token, token);
  } else {
    localStorage.removeItem(STORAGE_KEYS.token);
  }
}

function clearSession() {
  localStorage.removeItem(STORAGE_KEYS.slug);
  localStorage.removeItem(STORAGE_KEYS.token);
}

function getStoredSlug() {
  return localStorage.getItem(STORAGE_KEYS.slug);
}

function getStoredToken() {
  return localStorage.getItem(STORAGE_KEYS.token);
}

function loadMissionVisibilityConfig() {
  try {
    const raw = localStorage.getItem(MISSION_CONFIG_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      return parsed;
    }
  } catch (err) {
    console.warn('No se pudo cargar la configuración de misiones.', err);
  }
  return {};
}

function saveMissionVisibilityConfig(config) {
  try {
    localStorage.setItem(MISSION_CONFIG_KEY, JSON.stringify(config));
  } catch (err) {
    console.warn('No se pudo guardar la configuración de misiones.', err);
    throw err;
  }
}

function resetMissionVisibilityConfig() {
  try {
    localStorage.removeItem(MISSION_CONFIG_KEY);
  } catch (err) {
    console.warn('No se pudo restablecer la configuración de misiones.', err);
  }
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

/**
 * Renderiza el formulario de matrícula.
 */
function renderEnrollForm() {
  const content = getContentContainer();
  content.innerHTML = `
    <section class="enroll">
      <h2>Matrícula</h2>
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
      const res = await fetch('/api/enroll', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, email, password, slug, role, workdir }),
      });
      const data = await res.json();
      if (res.ok) {
        let sessionToken = '';
        try {
          const loginRes = await fetch('/api/login', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ slug, password }),
          });
          if (loginRes.ok) {
            const loginData = await loginRes.json();
            if (loginData && loginData.authenticated && loginData.token) {
              sessionToken = loginData.token;
            }
          }
        } catch (loginErr) {
          console.warn('No se pudo iniciar sesión automáticamente tras la matrícula.', loginErr);
        }
        if (sessionToken) {
          storeSession(slug, sessionToken);
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
      const res = await fetch('/api/login', {
        method: 'POST',
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
        storeSession(confirmedSlug, sessionToken);
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
        const res = await fetch('/api/students');
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

function renderMissionConfigurator() {
  const content = getContentContainer();
  const visibility = loadMissionVisibilityConfig();
  const missionItems = MISSIONS.map((mission) => {
    const isVisible = visibility[mission.id] !== false;
    const roles = mission.roles.join(', ');
    return `
      <li class="mission-config__item">
        <label>
          <input type="checkbox" name="missionVisibility" value="${mission.id}" ${
            isVisible ? 'checked' : ''
          } />
          <span class="mission-config__details">
            <span class="mission-config__title">${mission.title}</span>
            <span class="mission-config__roles">Roles: ${roles}</span>
          </span>
        </label>
      </li>
    `;
  }).join('');

  content.innerHTML = `
    <section class="mission-config">
      <h2>Configurar misiones</h2>
      <p>Activa o desactiva las misiones que estarán disponibles en el dashboard principal. Los cambios se guardan automáticamente.</p>
      <form id="missionConfigForm">
        <ul class="mission-config__list">
          ${missionItems}
        </ul>
        <div class="mission-config__actions">
          <button type="button" id="resetMissionConfig">Restablecer visibilidad</button>
        </div>
      </form>
      <div id="missionConfigMsg" class="msg" role="status" aria-live="polite"></div>
    </section>
  `;

  const form = $('#missionConfigForm');
  if (!form) {
    return;
  }

  const checkboxes = Array.from(form.querySelectorAll('input[type="checkbox"]'));
  const message = $('#missionConfigMsg');

  const showMessage = (text) => {
    if (!message) {
      return;
    }
    message.textContent = text;
    if (text) {
      setTimeout(() => {
        if (message.textContent === text) {
          message.textContent = '';
        }
      }, 2500);
    }
  };

  const persistConfig = () => {
    const updated = {};
    checkboxes.forEach((checkbox) => {
      updated[checkbox.value] = checkbox.checked;
    });
    try {
      saveMissionVisibilityConfig(updated);
      showMessage('Cambios guardados.');
    } catch (err) {
      showMessage('No se pudo guardar la configuración. Revisa los permisos del navegador.');
    }
  };

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener('change', persistConfig);
  });

  const resetBtn = $('#resetMissionConfig');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      resetMissionVisibilityConfig();
      checkboxes.forEach((checkbox) => {
        checkbox.checked = true;
      });
      showMessage('Se restauró la visibilidad predeterminada.');
    });
  }
  setupAccessLinks();
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
    const res = await fetch(`/api/status?slug=${encodeURIComponent(slug)}`, {
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
    if (canonicalSlug && canonicalSlug !== currentSlug) {
      storeSession(canonicalSlug, token);
    }
    renderDashboard(student, completed);
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
function renderDashboard(student, completed) {
  const content = $('#content');
  const visibility = loadMissionVisibilityConfig();
  const missionsForRole = MISSIONS.filter(
    (mission) => mission.roles.includes(student.role) && visibility[mission.id] !== false,
  );
  const unlocked = {};
  if (missionsForRole.length > 0) {
    unlocked[missionsForRole[0].id] = true;
  }
  missionsForRole.forEach((mission, idx) => {
    if (completed.includes(mission.id)) {
      unlocked[mission.id] = true;
      if (idx + 1 < missionsForRole.length) {
        unlocked[missionsForRole[idx + 1].id] = true;
      }
    }
  });
  let html = `<section class="dashboard">
    <h2>Bienvenido, ${student.name}</h2>
    <p>Rol: ${student.role}</p>`;
  if (missionsForRole.length > 0) {
    html += `
    <p>Selecciona una misión para continuar:</p>
    <ul class="missions-grid">`;
    missionsForRole.forEach((mission) => {
      const isCompleted = completed.includes(mission.id);
      const isUnlocked = unlocked[mission.id] || false;
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
        html += `<li class="mission-card ${statusClass}"><a href="${mission.id}.html">${mission.title}</a><span class="status">${statusText}</span></li>`;
      } else {
        html += `<li class="mission-card ${statusClass}">${mission.title}<span class="status">${statusText}</span></li>`;
      }
    });
    html += '</ul>';
  } else {
    html += `
    <p class="dashboard__empty">No hay misiones visibles para tu rol. Usa <a href="#" data-action="configure">Configurar misiones</a> en la parte superior para activarlas.</p>`;
  }
  html += '<button id="logoutBtn">Salir</button>';
  html += '</section>';
  content.innerHTML = html;
  const logoutBtn = $('#logoutBtn');
  if (logoutBtn) {
    logoutBtn.onclick = () => {
      clearSession();
      renderLoginForm();
    };
  }
  setupAccessLinks();
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
    const res = await fetch('/api/verify_mission', {
      method: 'POST',
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

  const configureLinks = document.querySelectorAll('[data-action="configure"]');
  attachHandler(configureLinks, () => {
    renderMissionConfigurator();
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
  const slug = getStoredSlug();
  const token = getStoredToken();
  if (!slug || !token) {
    clearSession();
    renderLoginForm();
    return;
  }
  loadDashboard();
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
