"""内存 job 表 + 进度事件。单机单用户，不建库、不落盘。"""
import threading
import uuid


class Job:
    def __init__(self, filename: str, style: str):
        self.id = uuid.uuid4().hex[:12]
        self.filename = filename
        self.style = style
        self.phase = "starting"   # starting/体检/抽字/ai/done/error
        self.progress = 0         # ai 阶段的百分比
        self.message = "排队中…"
        self.result = None        # 完成时: {id, title, file, gaps}
        self.error = None
        self.lock = threading.Lock()

    def update(self, phase=None, progress=None, message=None):
        with self.lock:
            if phase is not None:
                self.phase = phase
            if progress is not None:
                self.progress = progress
            if message is not None:
                self.message = message

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "filename": self.filename,
                "style": self.style,
                "phase": self.phase,
                "progress": self.progress,
                "message": self.message,
                "result": self.result,
                "error": self.error,
            }


# 并发防护：converter 结束（成功/失败）都打这把锁的开关
WAITERS: dict[str, threading.Event] = {}


def create(filename: str, style: str) -> Job:
    job = Job(filename, style)
    WAITERS[job.id] = threading.Event()
    JOBS[job.id] = job
    return job


def get(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def finish(job_id: str):
    ev = WAITERS.get(job_id)
    if ev:
        ev.set()


JOBS: dict[str, Job] = {}
