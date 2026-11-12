FROM python:3.13-alpine

# Sem dependências externas: só a biblioteca padrão do Python.
# Roda como root dentro do contêiner porque o disco da Fly.io é montado como root em /data.
WORKDIR /app
COPY skinmon ./skinmon
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    SKINMON_DATA=/data \
    PANEL_HOST=0.0.0.0 \
    PANEL_PORT=8787
VOLUME /data
EXPOSE 8787

CMD ["python", "-m", "skinmon"]
