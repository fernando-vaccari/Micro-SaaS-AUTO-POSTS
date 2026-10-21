import json
import os
import urllib.request

from scripts.render_job import main as render_video


def main():
    api_url = os.environ.get("AUTOPOSTS_API_URL", "").rstrip("/")
    api_secret = os.environ.get("AUTOPOSTS_API_SECRET", "")

    if not api_url.startswith("https://") or not api_secret:
        raise RuntimeError("Configure AUTOPOSTS_API_URL e AUTOPOSTS_API_SECRET.")

    request = urllib.request.Request(
        f"{api_url}/api/jobs/next",
        headers={
            "Authorization": f"Bearer {api_secret}",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)

    job = data.get("job")

    if not job:
        print("Nenhum vídeo pendente na fila.")
        return

    if job.get("status") != "pending":
        raise RuntimeError("O trabalho não está pendente.")

    job_id = job.get("id")
    topic = job.get("topic")

    if not isinstance(job_id, str) or not isinstance(topic, str):
        raise RuntimeError("Dados inválidos recebidos da API.")

    print(f"Vídeo encontrado: {job_id}")
    print(f"Assunto: {topic}")

    os.environ["AUTOPOSTS_JOB_ID"] = job_id
    os.environ["AUTOPOSTS_TOPIC"] = topic

    render_video()

    print("MP4 gerado com sucesso!")


if __name__ == "__main__":
    main()
