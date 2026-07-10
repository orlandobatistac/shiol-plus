# SHIOL+ v9 — Motor de estrategias (Python), corre como Cloudflare Container.
# Ver docs/adr/0001-python-first-engine-docker-cloudflare-standby.md
#
# IMPORTANTE: este Dockerfile espera que el build context sea la RAÍZ del
# repo (shiol-plus-v9/), no engine/ — porque necesita requirements.txt, que
# vive en la raíz. Por DEFECTO Wrangler usa como build context la carpeta
# donde vive este Dockerfile (engine/), no la raíz — hay que overridearlo
# explícitamente con `image_build_context` en wrangler.toml (Fase 2):
#   [[containers]]
#   image = "./engine/Dockerfile"
#   image_build_context = "."
#
# Prueba local sin Cloudflare (desde la raíz del repo):
#   docker build -f engine/Dockerfile -t shiolplus-engine .
#   docker run -p 8000:8000 shiolplus-engine

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# nvidia-nccl-cu12 es una dependencia transitiva de xgboost (soporte multi-GPU/
# distribuido) que este proyecto no usa -- el motor entrena XGBClassifier 100%
# CPU, sin ningún flag de GPU. Verificado (2026-07-05): entrenar y predecir con
# XGBClassifier, y correr xgboost_ml/hybrid_ensemble end-to-end, funciona igual
# sin este paquete. Se borra en la MISMA capa del pip install (~400MB, ~22% del
# tamaño de la imagen) -- si se borrara en un RUN separado, Docker no reduciría
# el tamaño final, solo ocultaría los archivos en una capa nueva.
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /usr/local/lib/python3.11/site-packages/nvidia*

COPY engine/ ./engine/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "engine.server:app", "--host", "0.0.0.0", "--port", "8000"]
