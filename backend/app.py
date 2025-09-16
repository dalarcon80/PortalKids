from pathlib import Path

from flask import Flask, render_template

BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)


@app.route("/login")
def login():
    """Renderiza la página de inicio de sesión."""
    return render_template("login.html")


@app.route("/register")
def register():
    """Renderiza la página de registro."""
    return render_template("inscripcion.html")


@app.route("/missions")
def missions():
    """Renderiza el listado de misiones disponibles."""
    missions_data = [
        {
            "title": "Limpieza de paneles solares",
            "description": "Asegura el máximo rendimiento energético limpiando los paneles principales.",
            "status": "Disponible",
            "due_date": "2024-07-01",
            "location": "Módulo exterior Alfa",
            "link": True,
        },
        {
            "title": "Mantenimiento del sistema de oxígeno",
            "description": "Revisa los niveles y filtros del sistema de soporte vital.",
            "status": "En curso",
            "due_date": "2024-06-15",
            "location": "Laboratorio central",
            "link": True,
        },
        {
            "title": "Exploración geológica",
            "description": "Recolecta muestras de la superficie para analizarlas en el laboratorio.",
            "status": "Próximamente",
            "due_date": "2024-08-10",
            "location": "Sector Delta",
            "link": False,
        },
    ]
    return render_template("missions.html", missions=missions_data)


if __name__ == "__main__":
    app.run(debug=True)
