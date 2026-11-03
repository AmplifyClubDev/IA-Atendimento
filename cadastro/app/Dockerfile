FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=3000
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app
EXPOSE 3000
# Um processo com várias threads: a fila da ponte de agenciamento e o estado temporário
# das sessões ficam num só lugar. O wrapper mantém o link /cadastro/ensaio da Bia.
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "1", "--threads", "16", "--timeout", "90", "--graceful-timeout", "100", "cadastro_pilot:create_app()"]
