FROM docker.io/library/python@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79

WORKDIR /app
COPY --from=python-wheels / /opt/wheels/
COPY requirements-runtime.lock .
RUN PIP_CONFIG_FILE=/dev/null python -I -m pip --isolated --disable-pip-version-check --no-cache-dir install --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r requirements-runtime.lock && python -I -m pip check && rm -r /opt/wheels

COPY app ./app
COPY run.py .
RUN useradd -r -u 10001 fdsuser
USER fdsuser
EXPOSE 8001 9090
CMD ["python", "run.py"]
