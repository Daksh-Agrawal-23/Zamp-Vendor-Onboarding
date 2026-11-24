FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-hin libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY --chown=app:app . .
RUN mkdir -p data/uploads && chown -R app:app data
ENV PYTHONPATH=/app PORT=7860 DEMO=1 WORKERS=2
USER app
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/healthz')" || exit 1
# demo documents are built once at start; set DEMO=0 and real SMTP/USERS/SECRET_KEY/FIELD_KEY for anything beyond a demo
CMD ["sh","-c","python make_demo.py && gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT} app:app"]
