FROM python:3.10-slim

RUN apt-get update && apt-get install -y curl

COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install -r requirements.txt
COPY app.py /app/app.py

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]