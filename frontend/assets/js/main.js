// main.js - lógica del portal de misiones

const API_BASE = '';

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
    const slug = $('#slug').value.trim();
    const role = $('#role').value;
    const workdir = $('#workdir').value.trim();
    if (!name || !slug || !role || !workdir) {
      $('#enrollMsg').textContent = 'Todos los campos son obligatorios.';
      return;
    }
    try {
      const res = await fetch('/api/enroll', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, slug, role, workdir }),
      });
      const data = await res.json();
      if (res.ok) {
        localStorage.setItem('student_slug', slug);
        $('#enrollMsg').textContent = '¡Matrícula exitosa! Redirigiendo...';
        setTimeout(() => {
          loadDashboard();
        }, 1000);
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
      <p>Ingresa tu slug para acceder al portal.</p>
      <form id="loginForm">
        <label>Selecciona tu usuario:<br />
          <select id="studentSelect">
            <option value="">Cargando estudiantes...</option>
          </select>
        </label><br />
        <label>Slug:<br /><input type="text" id="loginSlug" required /></label><br />
        <button type="submit">Ingresar</button>
      </form>
      <div id="loginMsg" class="msg"></div>
    </section>
  `;
  const loginForm = $('#loginForm');
  if (!loginForm) {
    return;
  }
  const slugInput = $('#loginSlug');
  const msg = $('#loginMsg');
  const studentSelect = $('#studentSelect');

  const attemptLogin = async (slugValue) => {
    if (!slugInput || !msg) {
      return;
    }
    const slug = (slugValue || '').trim();
    if (!slug) {
      msg.textContent = 'Debes ingresar tu slug.';
      return;
    }
    slugInput.value = slug;
    msg.textContent = 'Verificando tus datos...';
    try {
      const res = await fetch(`/api/status?slug=${encodeURIComponent(slug)}`);
      if (res.ok) {
        localStorage.setItem('student_slug', slug);
        msg.textContent = 'Ingreso exitoso. Cargando tu portal...';
        loadDashboard();
        return;
      }
      let errorMessage = 'No pudimos verificar tus datos.';
      let backendError = '';
      try {
        const data = await res.json();
        if (data && typeof data.error === 'string') {
          backendError = data.error;
          if (backendError.trim()) {
            errorMessage = backendError;
          }
        }
      } catch (parseErr) {
        // Ignorar errores de parseo y usar el mensaje predeterminado.
      }
      const normalizedError = backendError ? backendError.toLowerCase() : '';
      const shouldOfferEnroll =
        res.status === 404 || normalizedError.includes('student not found');
      if (shouldOfferEnroll) {
        localStorage.removeItem('student_slug');
        if (msg) {
          msg.textContent = '';
          const infoParagraph = document.createElement('p');
          let displayMessage = errorMessage;
          if (
            res.status === 404 ||
            normalizedError.includes('student not found') ||
            !displayMessage ||
            displayMessage === 'No pudimos verificar tus datos.'
          ) {
            displayMessage =
              'No encontramos tu matrícula. Haz clic en "Matricularme" para registrarte.';
          }
          infoParagraph.textContent = displayMessage;
          msg.appendChild(infoParagraph);
          const enrollBtn = document.createElement('button');
          enrollBtn.type = 'button';
          enrollBtn.id = 'goToEnrollBtn';
          enrollBtn.textContent = 'Matricularme';
          enrollBtn.onclick = (event) => {
            event.preventDefault();
            localStorage.removeItem('student_slug');
            renderEnrollForm();
          };
          msg.appendChild(enrollBtn);
        }
        return;
      }
      msg.textContent = errorMessage;
    } catch (err) {
      msg.textContent = 'Error de conexión. Intenta nuevamente.';
    }
  };

  loginForm.onsubmit = async (e) => {
    e.preventDefault();
    const currentSlug = slugInput ? slugInput.value : '';
    await attemptLogin(currentSlug);
  };

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
      attemptLogin(selectedSlug);
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

/**
 * Carga el tablero de misiones según el estudiante.
 */
async function loadDashboard() {
  const slug = localStorage.getItem('student_slug');
  const initialSlug = slug;
  if (!slug) {
    renderAccessOptions();
    return;
  }
  const content = $('#content');
  content.innerHTML = '<p>Cargando tu información...</p>';
  try {
    const res = await fetch(`/api/status?slug=${encodeURIComponent(slug)}`);
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
      if (studentNotFound) {
        localStorage.removeItem('student_slug');
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
    const currentSlug = localStorage.getItem('student_slug');
    if (!currentSlug || currentSlug !== initialSlug) {
      return;
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
  // Definición de las misiones y sus roles permitidos
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
  // Filtrar misiones según rol
  const missionsForRole = MISSIONS.filter((m) => m.roles.includes(student.role));
  // Determinar misiones desbloqueadas
  const unlocked = {};
  // La primera misión siempre se desbloquea
  if (missionsForRole.length > 0) {
    unlocked[missionsForRole[0].id] = true;
  }
  // Si completaste una misión, desbloquea la siguiente de tu rol
  missionsForRole.forEach((m, idx) => {
    if (completed.includes(m.id)) {
      unlocked[m.id] = true;
      // Desbloquea la siguiente misión
      if (idx + 1 < missionsForRole.length) {
        unlocked[missionsForRole[idx + 1].id] = true;
      }
    }
  });
  let html = `<section class="dashboard">
    <h2>Bienvenido, ${student.name}</h2>
    <p>Rol: ${student.role}</p>
    <p>Selecciona una misión para continuar:</p>
    <ul class="missions-grid">`;
  missionsForRole.forEach((m) => {
    const isCompleted = completed.includes(m.id);
    const isUnlocked = unlocked[m.id] || false;
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
      html += `<li class="mission-card ${statusClass}"><a href="${m.id}.html">${m.title}</a><span class="status">${statusText}</span></li>`;
    } else {
      html += `<li class="mission-card ${statusClass}">${m.title}<span class="status">${statusText}</span></li>`;
    }
  });
  html += '</ul>';
  html += '<button id="logoutBtn">Salir</button>';
  html += '</section>';
  content.innerHTML = html;
  $('#logoutBtn').onclick = () => {
    localStorage.removeItem('student_slug');
    renderAccessOptions();
  };
}

/**
 * Verifica una misión desde una página de misión.
 * @param {string} missionId
 * @param {HTMLElement} resultContainer
 */
async function verifyMission(missionId, resultContainer) {
  const slug = localStorage.getItem('student_slug');
  if (!slug) {
    resultContainer.textContent = 'Debes volver a matricularte.';
    return;
  }
  resultContainer.textContent = 'Verificando...';
  try {
    const res = await fetch('/api/verify_mission', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ slug, mission_id: missionId }),
    });
    const data = await res.json();
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

/**
 * Muestra las opciones iniciales para matricularse o ingresar.
 */
function renderAccessOptions() {
  const content = getContentContainer();
  content.innerHTML = `
    <section class="access-options">
      <h2>Bienvenido al Portal de Misiones</h2>
      <p>Selecciona una opción para continuar.</p>
      <div class="access-options__actions">
        <button id="accessEnrollBtn">Matricularme</button>
        <button id="accessLoginBtn">Ya estoy matriculado</button>
      </div>
    </section>
  `;
  const enrollBtn = $('#accessEnrollBtn');
  if (enrollBtn) {
    enrollBtn.onclick = () => {
      renderEnrollForm();
    };
  }
  const loginBtn = $('#accessLoginBtn');
  if (loginBtn) {
    loginBtn.onclick = () => {
      renderLoginForm();
    };
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
    localStorage.removeItem('student_slug');
    renderEnrollForm();
  });

  const loginLinks = document.querySelectorAll('[data-action="login"]');
  attachHandler(loginLinks, () => {
    localStorage.removeItem('student_slug');
    renderLoginForm();
  });

  const legacyEnrollLinks = document.querySelectorAll('a[href="m1.html"]');
  legacyEnrollLinks.forEach((link) => {
    link.href = '#';
  });
  attachHandler(legacyEnrollLinks, () => {
    localStorage.removeItem('student_slug');
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
    localStorage.removeItem('student_slug');
    renderEnrollForm();
    return;
  }
  const slug = localStorage.getItem('student_slug');
  if (!slug) {
    renderAccessOptions();
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
