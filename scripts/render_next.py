import json
import os
import urllib.request
import urllib.error

from scripts.render_job import main as render_video


API_URL = os.environ.get("AUTOPOSTS_API_URL", "").rstrip("/")
API_SECRET = os.environ.get("AUTOPOSTS_API_SECRET", "")


def chamar_api(caminho, dados=None):
    """Envia uma requisição autenticada à Cloudflare."""

    url = f"{API_URL}{caminho}"

    headers = {
        "Authorization": f"Bearer {API_SECRET}",
        "Accept": "*/*",
        "User-Agent": "curl/8.5.0",
    }

    if dados is not None:
        headers["Content-Type"] = "application/json"
        corpo = json.dumps(dados).encode("utf-8")
        metodo = "POST"
    else:
        corpo = None
        metodo = "GET"

    request = urllib.request.Request(
        url,
        data=corpo,
        headers=headers,
        method=metodo,
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    if not API_URL.startswith("https://") or not API_SECRET:
        raise RuntimeError(
            "Configure AUTOPOSTS_API_URL e AUTOPOSTS_API_SECRET."
        )

    print("Procurando próximo vídeo na fila...")

    # Reservar um vídeo pendente
    resposta = chamar_api("/api/jobs/claim", {})

    job = resposta.get("job")

    if not job:
        print("Nenhum vídeo pendente encontrado.")
        return

    job_id = job["id"]
    topic = job["topic"]

    print(f"Vídeo reservado: {job_id}")
    print(f"Assunto: {topic}")

    os.environ["AUTOPOSTS_JOB_ID"] = job_id
    os.environ["AUTOPOSTS_TOPIC"] = topic

    try:
        print("Iniciando geração do MP4...")

        # Gerar vídeo com FFmpeg
        render_video()

        print("MP4 gerado com sucesso!")

    except Exception as erro:
        print(f"Falha ao gerar vídeo: {erro}")

        # Informar falha à Cloudflare
        try:
            chamar_api(
                f"/api/jobs/{job_id}/result",
                {
                    "status": "failed",
                    "error": str(erro)[:500],
                },
            )
        except Exception as erro_api:
            print(f"Não foi possível registrar a falha: {erro_api}")

        raise

    # Registrar geração concluída
    chamar_api(
        f"/api/jobs/{job_id}/result",
        {
            "status": "completed",
        },
    )

    print("Status atualizado para COMPLETED!")
    print("Processamento finalizado.")


if __name__ == "__main__":
    main()
