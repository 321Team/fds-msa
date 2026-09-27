# BUILDER_IMAGE and RUNTIME_IMAGE must come from the repo-pinned apko configs/lockfiles.
ARG BUILDER_IMAGE
ARG RUNTIME_IMAGE

FROM ${BUILDER_IMAGE} AS build
WORKDIR /app
RUN python3.13 -m venv --copies /venv
COPY --from=python-wheels / /opt/wheels/
COPY requirements-runtime.lock .
RUN PIP_CONFIG_FILE=/dev/null /venv/bin/python -I -m pip --isolated --disable-pip-version-check --no-cache-dir install --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r requirements-runtime.lock \
    && PIP_CONFIG_FILE=/dev/null /venv/bin/python -I -m pip --isolated --disable-pip-version-check check \
    && PIP_CONFIG_FILE=/dev/null /venv/bin/python -I -m pip --isolated --disable-pip-version-check uninstall -y pip setuptools \
    && rm -rf /opt/wheels

FROM ${RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=build /venv /venv
COPY app ./app
COPY run.py .
USER 10001:999
EXPOSE 8000 9091
ENTRYPOINT ["/venv/bin/python3"]
CMD ["run.py"]
