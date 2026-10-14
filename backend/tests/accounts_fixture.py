"""Isolated account-login browser backend, never opens production stores."""
import os
from pathlib import Path
from fastapi import FastAPI
from src.agent.runtime import AgentRuntime
from src.api import evaluation, chat, files
from src.evaluation.auth import password_hash
from src.evaluation.contracts import AccessFile
from src.evaluation.service import EvaluationService
from src.evaluation.store import EvaluationStore
from src.storage.run_store import RunStore


def create_app():
    root = Path(os.environ['ACCOUNTS_TEST_ROOT'])
    root.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    encoded = password_hash('CauTest123456')
    specs = [('cau_dev', 'developer'), ('cau_expert1', 'reviewer'), ('cau_expert2', 'reviewer'),
             ('cau_tester1', 'tester'), ('cau_tester2', 'tester'), ('cau_tester3', 'tester')]
    app.state.eval_access = AccessFile(users=[{'tester_id': name, 'username': name, 'role': role,
                                             'password_hash': encoded} for name, role in specs])
    runs = RunStore(root / 'runs.sqlite3')
    app.state.agent_runtime = AgentRuntime(runs=runs)
    store = EvaluationStore(runs)
    store.seed(Path(__file__).resolve().parents[2] / 'data/eval')
    app.state.evaluation = EvaluationService(store)
    app.include_router(evaluation.router, prefix='/api')
    app.include_router(chat.router, prefix='/api')
    app.include_router(files.router, prefix='/api')
    return app
