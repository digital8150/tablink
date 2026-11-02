# progress

## 2026-11-02
- `macos-port` 브랜치(origin/main 7dcd004 기반, 커밋 bc0c9b4, 미푸시)에 macOS 포팅 완료.
- `helper-mac/` Swift 헬퍼: 프로토콜은 Windows 헬퍼와 동일. `swift build -c release` 통과.
- 실기기(SM-X910, 192.168.1.179) E2E 통과: attach→ctrl alive, UHID 장치 등록, info 이벤트, audio running, 가장자리 진입 active:true, toggle 복귀.
- 버그 수정: ProcessRegistry가 자식 stdout을 종료 후에 읽어 dumpsys(130KB)에서 데드락 → 파이프를 실행 중 드레인하도록 변경.
- 패키징: `npm run build:mac` → dist/TabLink-macos-arm64.zip (arm64, 미서명). icon은 패키저 기본 이름 electron.icns로 들어감(내용은 TabLink 아이콘).
- 권한: 헬퍼/터미널에 손쉬운 사용 + 입력 모니터링 필요. 현재 개발 실행 환경에서는 탭 생성 성공.
- 다음: 실제 마우스로 태블릿 이동/키보드 라우팅 수동 확인, 패키징 앱(TabLink.app) 권한 설정 흐름 확인, 필요 시 서명/공증.
- 함정: 무선 디버깅 포트는 재연결마다 바뀜 → mDNS 시리얼(adb-<id>._adb-tls-connect._tcp) 사용. 페어링 포트(41445류)와 연결 포트(39579류)는 다름.
