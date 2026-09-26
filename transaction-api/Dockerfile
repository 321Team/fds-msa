ARG BUILDER_IMAGE=docker.io/library/python@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ARG RUNTIME_IMAGE=gcr.io/distroless/python3-debian13@sha256:8ee214843129f43e2ebf5e0ca9f2e4e6d8292143d1b8a6787f169b5898578884

FROM ${BUILDER_IMAGE} AS build
WORKDIR /app
RUN ln -sf /usr/local/bin/python /usr/bin/python && /usr/bin/python -m venv /venv
COPY --from=python-wheels / /opt/wheels/
COPY requirements-runtime.lock .
RUN PIP_CONFIG_FILE=/dev/null /venv/bin/python -I -m pip --isolated --disable-pip-version-check --no-cache-dir install --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r requirements-runtime.lock \
    && PIP_CONFIG_FILE=/dev/null /venv/bin/python -I -m pip --isolated --disable-pip-version-check check \
    && rm -rf /opt/wheels

FROM ${RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=build /venv /venv
COPY app ./app
COPY run.py .
USER 65532:65532
EXPOSE 8000 9091
ENTRYPOINT ["/venv/bin/python3"]
CMD ["run.py"]
