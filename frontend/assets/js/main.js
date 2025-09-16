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

document.addEventListener('DOMContentLoaded', () => {
  const enrollLink = document.querySelector('a[href="m1.html"]');
  if (enrollLink) {
    enrollLink.href = '#';
    enrollLink.addEventListener('click', (e) => {
      e.preventDefault();
      localStorage.removeItem('student_slug');
      renderEnrollForm();
    });
  }
});

/**
 * Carga el tablero de misiones según el estudiante.
 */
async function loadDashboard() {
  const slug = localStorage.getItem('student_slug');
  const initialSlug = slug;
  if (!slug) {
    renderEnrollForm();
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
    renderEnrollForm();
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

// Al cargar la página, decide qué mostrar
window.addEventListener('load', () => {
  const searchParams = new URLSearchParams(window.location.search);
  const forceEnroll = searchParams.has('enroll');
  if (forceEnroll) {
    localStorage.removeItem('student_slug');
    renderEnrollForm();
    return;
  }
  const slug = localStorage.getItem('student_slug');
  if (
    window.location.pathname.endsWith('index.html') ||
    window.location.pathname === '/' ||
    window.location.pathname === ''
  ) {
    if (!slug) {
      renderEnrollForm();
    } else {
      loadDashboard();
    }
  }
});