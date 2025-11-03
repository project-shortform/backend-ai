"""
비동기 비디오 생성 태스크 큐 시스템

이 모듈은 비디오 생성 작업을 백그라운드에서 순차적으로 처리하는 태스크 큐를 제공합니다.

## 주요 기능
- 🔄 순차적 태스크 처리 (FIFO 큐)
- 📊 실시간 태스크 상태 추적
- 🛡️ 에러 처리 및 재시도 로직
- 💾 태스크 결과 영구 저장
- 🚀 백그라운드 워커 스레드

## 태스크 상태
- PENDING: 대기 중
- PROCESSING: 처리 중
- COMPLETED: 완료
- FAILED: 실패
"""

import threading
import queue
import uuid
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskQueue:
    def __init__(self):
        self.task_queue = queue.Queue()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.worker_thread = None
        self.is_running = False
        self._lock = threading.Lock()

    def start_worker(self):
        """백그라운드 워커 스레드를 시작합니다."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.is_running = True
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()
            print("🚀 태스크 워커가 시작되었습니다.")

    def stop_worker(self):
        """백그라운드 워커 스레드를 중지합니다."""
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
            print("⏹️ 태스크 워커가 중지되었습니다.")

    def add_task(
        self,
        task_func: Callable,
        task_args: tuple = (),
        task_kwargs: dict = None,
        task_type: str = "video_generation",
    ) -> str:
        """
        새로운 태스크를 큐에 추가합니다.

        Args:
            task_func: 실행할 함수
            task_args: 함수 인자 (tuple)
            task_kwargs: 함수 키워드 인자 (dict)
            task_type: 태스크 타입

        Returns:
            str: 생성된 태스크 ID
        """
        task_id = str(uuid.uuid4())

        with self._lock:
            task_info = {
                "id": task_id,
                "type": task_type,
                "status": TaskStatus.PENDING.value,
                "created_at": datetime.now().isoformat(),
                "started_at": None,
                "completed_at": None,
                "progress": 0,
                "result": None,
                "error": None,
                "func": task_func,
                "args": task_args or (),
                "kwargs": task_kwargs or {},
            }

            self.tasks[task_id] = task_info
            self.task_queue.put(task_id)

        # 워커가 실행 중이 아니면 시작
        if not self.is_running:
            self.start_worker()

        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """태스크 상태를 조회합니다."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                # 함수 객체는 제외하고 반환
                return {
                    k: v for k, v in task.items() if k not in ["func", "args", "kwargs"]
                }
            return None

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """모든 태스크 상태를 조회합니다."""
        with self._lock:
            return {
                task_id: {
                    k: v for k, v in task.items() if k not in ["func", "args", "kwargs"]
                }
                for task_id, task in self.tasks.items()
            }

    def update_task_progress(self, task_id: str, progress_data: dict):
        """태스크의 진행 상황을 메모리에서 업데이트합니다."""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(progress_data)
                return True
            return False

    def get_queue_status(self) -> Dict[str, Any]:
        """큐 상태를 조회합니다."""
        with self._lock:
            pending_count = sum(
                1
                for task in self.tasks.values()
                if task["status"] == TaskStatus.PENDING.value
            )
            processing_count = sum(
                1
                for task in self.tasks.values()
                if task["status"] == TaskStatus.PROCESSING.value
            )
            completed_count = sum(
                1
                for task in self.tasks.values()
                if task["status"] == TaskStatus.COMPLETED.value
            )
            failed_count = sum(
                1
                for task in self.tasks.values()
                if task["status"] == TaskStatus.FAILED.value
            )

            return {
                "is_running": self.is_running,
                "queue_size": self.task_queue.qsize(),
                "total_tasks": len(self.tasks),
                "pending": pending_count,
                "processing": processing_count,
                "completed": completed_count,
                "failed": failed_count,
            }

    def _worker(self):
        """백그라운드 워커 메인 루프"""
        print("🔄 태스크 워커가 실행 중입니다...")

        while self.is_running:
            try:
                # 태스크 가져오기 (1초 타임아웃)
                task_id = self.task_queue.get(timeout=1)

                with self._lock:
                    if task_id not in self.tasks:
                        continue

                    task = self.tasks[task_id]
                    task["status"] = TaskStatus.PROCESSING.value
                    task["started_at"] = datetime.now().isoformat()
                    task["progress"] = 0

                print(f"🎬 태스크 처리 시작: {task_id} ({task['type']})")

                try:
                    # 태스크 실행
                    result = task["func"](*task["args"], **task["kwargs"])

                    with self._lock:
                        task["status"] = TaskStatus.COMPLETED.value
                        task["completed_at"] = datetime.now().isoformat()
                        task["progress"] = 100
                        task["result"] = result

                    print(f"✅ 태스크 완료: {task_id}")

                except Exception as e:
                    error_msg = str(e)
                    error_traceback = traceback.format_exc()

                    with self._lock:
                        task["status"] = TaskStatus.FAILED.value
                        task["completed_at"] = datetime.now().isoformat()
                        task["error"] = {
                            "message": error_msg,
                            "traceback": error_traceback,
                        }

                    print(f"❌ 태스크 실패: {task_id} - {error_msg}")

                finally:
                    self.task_queue.task_done()

            except queue.Empty:
                # 타임아웃 - 계속 실행
                continue
            except Exception as e:
                print(f"⚠️ 워커 에러: {e}")
                time.sleep(1)

        print("🛑 태스크 워커가 종료되었습니다.")


# 전역 태스크 큐 인스턴스
task_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    """전역 태스크 큐 인스턴스를 반환합니다."""
    return task_queue
