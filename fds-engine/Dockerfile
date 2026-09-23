FROM docker.io/library/python@sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b

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
