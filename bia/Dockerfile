FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY answers.py bootstrap.py config.py contracts.py engine.py forms.py gateway.py knowledge.json repository.py server.py smtp.py transport.py conversation.py guided_ai.py context_ia.py real_journey.py real_operations.py playwright_client.py ./
COPY verify_private.py ./
COPY pilot_scope.py conversao.py retomada.py reconferencia.py ./
COPY demo_router.py ./
COPY demo_flow.py ./
COPY recovery.py ./
COPY forms_compat.py ./
COPY retention.py ./
COPY followup.py ./
COPY receipt_grounding.py ./
COPY nome_contextual.py ./
COPY data/ ./data/
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 60 --access-logfile /dev/null --error-logfile - 'bootstrap:create_app()'"]
