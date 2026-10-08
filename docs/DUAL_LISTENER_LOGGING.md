# 두 listener의 공용 접근 로그 보존

연계: baseline#19 Edge Cutover 사전검증, P1-APP-01.

transaction-api는 동일 프로세스에서 업무8000과 metrics9091을 실행해 Prometheus registry를 공유한다. Uvicorn logger 역시 프로세스 전역이다. 두 번째 Config가 `log_level="warning"`을 지정하면 첫 번째 업무 서버의 INFO 접근 로그도 꺼진다.

metrics Config는 `log_config=None, log_level=None`으로 기존 업무 서버의 로깅 설정을 유지한다. 두 listener/포트·업무 처리·DB·metrics registry는 그대로다. metrics 접근 로그도 INFO로 출력되므로 기존보다 로그량이 증가한다. 로그에 URL 경로와 쿼리가 포함되는 Uvicorn 기본 형식이 유지되며 토큰 등 비밀을 쿼리로 보내면 안 된다.

검증은 실제 Uvicorn Config 두 개와 네트워크를 열지 않는 Server 대역을 사용한다. 두 서버 생성 뒤 INFO가 유지되고 표식 로그가 출력되는지 확인한다. 이는 HTTP/이미지/현장 검증을 대신하지 않는다.

운영 적용은 독립 코드 리뷰·병합 후 승인된 빌드/보안 검사·이미지 digest 고정·APP Lead의 배포 및 복구 계획이 필요하다. 기존 Edge upstream-only 승인을 앱 재배포 승인으로 확대하지 않는다. 배포 시 두 포트·정상 거래·metrics와 자원/로그량을 확인하고, 문제가 있으면 직전 승인 digest/배포 사양으로 복구한다. E-K3S와 Kubernetes 양쪽 관측을 복구해 fresh 표식 추적을 통과해야 #19 Cutover를 진행할 수 있다.

현재 live 이미지의 일부 source가 main과 같아도 main의 다른 변경까지 운영 승인됐다는 뜻은 아니다. 운영 빌드의 source lineage를 고정하고 필요한 경우 이 수정만 해당 승인 source에 반영해야 한다.
