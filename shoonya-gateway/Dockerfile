FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway ./gateway
RUN mkdir -p /data
ENV PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "-m", "gateway.main"]
