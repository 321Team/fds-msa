## 문제와 변경

- 책임 티켓/정본 절·AC:
- 정본 필수 / 기존 승인 구현 / 이번 운영 세칙 중 해당 구분:
- 검토 HEAD / 원본 commit:
- 변경 경로·영향·복구 방법:
- 이번 단계: 소스 이관 / 소비자 전환 / Runtime (해당 단계 명시)

## 검증과 제한

| 단계 | 결과 | 환경·명령·rc·로그·근거 |
|---|---|---|
| STATIC | NOT RUN | |
| MOCK/UNIT | NOT RUN | |
| CI | NOT RUN | 0건을 PASS로 표시하지 않음 |
| RUNTIME | NOT RUN | 대상·계정·KST 시각·source/bundle SHA |

- CI 미실행 사유와 실제 로컬 보상 증적:
- 과거 원본 시험을 인용하는 경우 원본 SHA/Run/Attempt·파일 동일성·적용 한계:
- 이번 단계의 미해결 차단사항 / 후속 Runtime·P1/P2 잔여:

- [ ] 개인키·토큰·실제 Secret 없음, 공개 자료와 테스트 fixture 구분
- [ ] source pin·상대 경로·의존성·만료된 예외·복구 영향 확인
- [ ] 최신 HEAD의 작성자 외 독립 검토 결과와 승인 근거 연결 (검토 전에는 미체크)
- [ ] CI NOT RUN·과거 이력·미실행 시험의 제한 수용 여부를 독립 검토자가 기록

REVIEW=PENDING / MERGE=NOT_DONE / PUBLICATION=NOT_DONE
소스 병합·Runtime·영구 반영·정본 발행·티켓 종결 승인은 별도다.
