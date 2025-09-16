from __future__ import annotations

import os
from typing import Dict, List

from flask import Flask, render_template, flash, redirect, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

# Almacenamiento sencillo en memoria para usuarios registrados durante
# el ciclo de vida de la aplicación.
registered_users: List[Dict[str, str]] = []


@app.route("/inscripcion", methods=["GET"])
def inscripcion() -> str:
    """Renderiza el formulario de inscripción."""
    return render_template("inscripcion.html", usuarios=registered_users)


@app.route("/register", methods=["POST"])
def register():
    """Procesa el formulario de inscripción y almacena al nuevo usuario."""
    nombre = request.form.get("nombre", "").strip()
    slug = request.form.get("slug", "").strip()
    email = request.form.get("email", "").strip()

    if not nombre or not slug or not email:
        flash("Todos los campos son obligatorios.", "error")
        return redirect(url_for("inscripcion"))

    registered_users.append({"nombre": nombre, "slug": slug, "email": email})
    flash("Registro completado correctamente.", "success")
    return redirect(url_for("inscripcion"))


@app.route("/")
def index() -> str:
    return redirect(url_for("inscripcion"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
