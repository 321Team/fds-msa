# 엔드페이지 이미지 — 정적 파일 4개와 nginx 설정만 얹는다. 앱 코드·의존성 없음.
# 기반 이미지는 Red Hat UBI nginx(root 아닌 UID, 8080). 태그는 빌드 회차에서 digest로 고정한다.
# 결정 필요: 기반 이미지 선택(UBI vs 기존 Wolfi 계열)과 버전 — 리뷰에서 확정.
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/nginx-124
FROM ${BASE_IMAGE}

COPY --chown=1001:0 nginx.conf /opt/app-root/etc/end-nginx.conf
COPY --chown=1001:0 end-headers.conf /opt/app-root/etc/end-headers.conf
COPY --chown=1001:0 index.html app.css app.js /opt/app-root/src/end/

# OpenShift 임의 UID는 GID 0으로 돈다 — 그룹이 소유자와 같은 읽기 권한을 갖게 한다.
USER 0
RUN chmod -R g=u /opt/app-root/src/end /opt/app-root/etc/end-nginx.conf /opt/app-root/etc/end-headers.conf
USER 1001

EXPOSE 8080
# -e stderr: 설정을 읽기 전 기본 로그 파일(/var/log/nginx)을 열지 않는다(읽기 전용 루트).
CMD ["nginx", "-e", "stderr", "-c", "/opt/app-root/etc/end-nginx.conf", "-g", "daemon off;"]
