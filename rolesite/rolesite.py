from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def serve_site():
    roles = [
        ("Mafia", 50),
        ("Citizen", 51),
        ("Sheriff", 52),
        ("Jester", 53),
        ("Executioner", 54),
        ("Survivor", 55),
        ("Doctor", 56),
        ("PI", 57),
        ("Lookout", 58),
        ("Jailor", 59),
    ]
    return render_template("index.html", roles=roles)


if __name__ == "__main__":
    app.run()
