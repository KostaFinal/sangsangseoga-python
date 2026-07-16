# app/utils/perf_logger.py
#
# 임시 성능 계측용 로거. [AI-PERF] 블록을 stdout에 출력한다.
# 병목 위치를 찾기 위한 조사용 코드이며, 조사가 끝나면 제거하거나
# logging 모듈 기반으로 정리하는 것을 권장한다.

from pathlib import Path
from typing import Any, Dict, Optional


LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "ai_perf.log"


def log_ai_perf(request_id: str, task_type: Optional[str], timings: Dict[str, Any]) -> None:
    """
    [AI-PERF]
    requestId=...
    taskType=...
    ...Ms=...
    형식으로 한 요청의 구간별 소요시간을 출력한다.

    timings의 키 순서가 그대로 출력 순서가 되므로, 호출부에서 보고 싶은
    순서대로 dict를 구성해서 넘긴다.

    stdout(uvicorn 콘솔) 출력에 더해 logs/ai_perf.log에도 같은 내용을 append한다.
    """
    lines = ["[AI-PERF]", f"requestId={request_id}", f"taskType={task_type or ''}"]

    for key, value in timings.items():
        if isinstance(value, float):
            value = round(value, 1)
        lines.append(f"{key}={value}")

    text = "\n".join(lines)
    print(text)

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
