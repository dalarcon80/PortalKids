"""PortalKids web application entry-point."""
from __future__ import annotations

from typing import Dict, List

from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

# Datos de ejemplo para las misiones disponibles en el portal.
MISSIONS: List[Dict[str, str]] = [
    {
        "title": "Exploración de la Nebulosa Aurora",
        "description": "Recolecta muestras de partículas luminosas para el laboratorio.",
        "status": "Activa",
        "due_date": "2024-09-30",
        "location": "Sector Boreal",
    },
    {
        "title": "Rescate del Satélite Eco",
        "description": "Ayuda a reparar el satélite de comunicaciones Eco antes de que se apague.",
        "status": "Urgente",
        "due_date": "2024-08-18",
        "location": "Órbita Sincrónica",
    },
    {
        "title": "Cartografía del Cinturón Prisma",
        "description": "Crea un mapa detallado del campo de asteroides Prisma con la tripulación.",
        "status": "Programada",
        "due_date": "2024-11-05",
        "location": "Cinturón Prisma",
    },
]

# Credenciales mínimas para validar el acceso al portal.
CREW_MEMBERS: Dict[str, Dict[str, str]] = {
    "capitana-nova": {"password": "orbita"},
    "piloto-cometa": {"password": "halo"},
    "especialista-quantum": {"password": "quasar"},
}


def _normalize_slug(value: str) -> str:
    """Normaliza el identificador recibido desde el formulario."""

    return value.strip().lower()


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    """Muestra el formulario de acceso y valida las credenciales enviadas."""

    error = None
    if request.method == "POST":
        slug = _normalize_slug(request.form.get("slug", ""))
        password = request.form.get("password", "")

        member = CREW_MEMBERS.get(slug)
        if member and password == member.get("password"):
            return redirect(url_for("missions", slug=slug))

        error = "Usuario o contraseña incorrectos. Inténtalo nuevamente."

    return render_template("login.html", error=error)


@app.route("/inscripcion", methods=["GET"])
def inscripcion():
    """Renderiza la página de inscripción existente."""

    return render_template("inscripcion.html")


@app.route("/misiones", methods=["GET"])
def missions():
    """Muestra el tablero con las misiones disponibles."""

    return render_template("missions.html", missions=MISSIONS)


if __name__ == "__main__":
    app.run(debug=True)
