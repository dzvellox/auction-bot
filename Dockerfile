FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium
COPY . .
# In Docker use Playwright's bundled Chromium rather than Windows Edge.
ENV BROWSER_CHANNEL=""
CMD ["python", "main.py"]
