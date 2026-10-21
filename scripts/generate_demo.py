import tempfile
from pathlib import Path

from autoposts import core, media

with tempfile.TemporaryDirectory() as directory:
    core.settings.data_dir = Path(directory)
    core.init_db()

    core.execute(
        """
        INSERT INTO users(id, email, name, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("demo", "demo@example.com", "Demo", "unused", core.now()),
    )

    post = {
        "id": "autoposts-demo",
        "user_id": "demo",
        "title": "Transforme suas ideias em resultados",
        "caption": "Automatize sua presença digital!",
        "duration": 6,
        "theme": "ocean",
        "scenes": [
            {"text": "Seu negócio merece destaque!"},
            {"text": "Crie conteúdo e publique com consistência."},
        ],
    }

    filename = media.render_post(post)

    output = Path("artifacts")
    output.mkdir(exist_ok=True)

    source = Path(directory) / "videos" / filename
    destination = output / filename
    destination.write_bytes(source.read_bytes())

    print(f"Vídeo gerado: {destination}")
