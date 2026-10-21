import os
import re
import tempfile
from pathlib import Path

from autoposts import core, media


def main():
    job_id = os.environ.get("AUTOPOSTS_JOB_ID", "teste-001")
    topic = os.environ.get(
        "AUTOPOSTS_TOPIC",
        "Por que sua empresa precisa de um site profissional?"
    ).strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise ValueError("ID do vídeo inválido")

    if not topic or len(topic) > 500:
        raise ValueError("Assunto do vídeo inválido")

    with tempfile.TemporaryDirectory() as directory:
        core.settings.data_dir = Path(directory)
        core.init_db()

        core.execute(
            """
            INSERT INTO users
            (id, email, name, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "renderer",
                "renderer@example.com",
                "Auto Posts",
                "unused",
                core.now()
            )
        )

        post = {
            "id": job_id,
            "user_id": "renderer",
            "title": topic[:120],
            "caption": topic,
            "duration": 8,
            "theme": "ocean",
            "scenes": [
                {
                    "text": topic[:100]
                }
            ]
        }

        filename = media.render_post(post)

        output = Path("artifacts")
        output.mkdir(exist_ok=True)

        source = Path(directory) / "videos" / filename
        destination = output / filename

        destination.write_bytes(source.read_bytes())

        print(f"Vídeo gerado: {destination}")


if __name__ == "__main__":
    main()
