FROM python:3.11-slim

RUN useradd -m -u 1001 opsscope

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY app ./app
COPY frontend ./frontend

ENV OPS_SCOPE_DATA=/data
RUN mkdir -p /data && chown -R opsscope:opsscope /app /data
VOLUME /data
EXPOSE 8000

USER opsscope

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/overview')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
