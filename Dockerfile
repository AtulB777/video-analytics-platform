FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt requirements-yolo.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Optional: build with --build-arg INSTALL_YOLO=true to add Ultralytics (large)
ARG INSTALL_YOLO=false
RUN if [ "$INSTALL_YOLO" = "true" ]; then pip install --no-cache-dir -r requirements-yolo.txt; fi

COPY app ./app
COPY dashboard ./dashboard
COPY configs ./configs
COPY scripts ./scripts

EXPOSE 8000 8501
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
