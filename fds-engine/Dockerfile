FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

RUN useradd -r -u 10001 fdsuser
USER fdsuser

# 8001 = main app, 9090 = dedicated metrics listener (baseline dual-port
# metrics contract, infra-kubernetes#7 SEC-05). Both are served by run.py
# in the same process — see run.py docstring for why this can't be two
# separate `uvicorn` invocations.
EXPOSE 8001 9090
CMD ["python", "run.py"]
