FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*


# Install lightweight web framework and fastText-based dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

RUN mkdir -p /app/models/afrolid && \
    curl -L --fail --silent --show-error \
      -o /app/models/afrolid/lid.176.bin \
      https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin

COPY app /app/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
