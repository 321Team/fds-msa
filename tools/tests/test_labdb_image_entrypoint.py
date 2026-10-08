"""고정 digest rhel9/postgresql-16 이미지의 실제 시작 경로로 lab-db schema 훅을 확인한다(격리 컨테이너, 클러스터 없음).

FDS_LABDB_IMAGE_IT=1 이고 docker가 있을 때만 실행한다(workflow `labdb-image-it`). 이미지 pull 외 네트워크를 쓰지 않는다.
매니페스트와 같은 조건으로 띄운다: 임의 UID(gid 0), 읽기 전용 루트, capability 전부 제거, no-new-privileges,
HOME·소켓·/tmp 쓰기 볼륨, 훅은 postgresql-start에 읽기 전용. seccomp는 Docker 기본 프로필(RuntimeDefault에 해당).
시나리오: (1) 빈 HOME 첫 기동 (2) 같은 데이터 재시작 (3) 깨진 SQL 첫 기동 실패 + 같은 데이터 재시작도 실패 (4) 고친 SQL로 복구.
"""
from pathlib import Path
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
LABDB = ROOT / "deploy" / "components" / "lab-db"
UID = "1000770000:0"
READY_TIMEOUT = 180


def image_ref():
    img = yaml.safe_load((LABDB / "kustomization.yaml").read_text(encoding="utf-8"))["images"][0]
    return f"{img['newName']}@{img['digest']}"


def docker(*args, check=True):
    done = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and done.returncode:
        raise AssertionError(f"docker {' '.join(args[:2])} rc={done.returncode}: {done.stderr[-500:]}")
    return done


@unittest.skipUnless(os.environ.get("FDS_LABDB_IMAGE_IT") == "1" and shutil.which("docker"),
                     "FDS_LABDB_IMAGE_IT=1 과 docker 필요 — workflow labdb-image-it에서 실행")
class LabDbImageStartContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = image_ref()
        docker("pull", "--platform", "linux/amd64", cls.image)
        print("image:", docker("image", "inspect", "--format", "{{json .RepoDigests}} {{.Id}}", cls.image).stdout.strip())

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="labdb-it-", dir=os.environ.get("RUNNER_TEMP")))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.password = secrets.token_hex(16)
        self.names = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for name in self.names:
            print(f"----- logs {name}\n" + docker("logs", name, check=False).stdout[-4000:]
                  + docker("logs", name, check=False).stderr[-4000:])
            docker("rm", "-f", name, check=False)

    def volumes(self, tag, sql_text=None):
        base = self.root / tag
        dirs = {}
        for key in ("home", "run", "tmp", "start"):
            d = base / key
            d.mkdir(parents=True)
            os.chmod(d, 0o777)
            dirs[key] = d
        shutil.copy(LABDB / "10-fds-schema.sh", dirs["start"] / "10-fds-schema.sh")
        if sql_text is None:
            shutil.copy(LABDB / "fds-schema.sql", dirs["start"] / "fds-schema.sql")
        else:
            (dirs["start"] / "fds-schema.sql").write_text(sql_text, encoding="utf-8")
        for f in dirs["start"].iterdir():
            os.chmod(f, 0o644)
        return dirs

    def create(self, tag, dirs):
        name = f"labdb-it-{tag}-{secrets.token_hex(3)}"
        docker("create", "--name", name, "--user", UID, "--read-only", "--network", "none",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "-v", f"{dirs['home']}:/var/lib/pgsql", "-v", f"{dirs['run']}:/var/run/postgresql",
               "-v", f"{dirs['tmp']}:/tmp", "-v", f"{dirs['start']}:/opt/app-root/src/postgresql-start:ro",
               "-e", "POSTGRESQL_USER=fds_lab", "-e", f"POSTGRESQL_PASSWORD={self.password}",
               "-e", "POSTGRESQL_DATABASE=fds_lab", self.image)
        self.names.append(name)
        return name

    def wait(self, name):
        """ready면 ('ready', None), Ready 전에 끝나면 ('exited', 종료 코드)."""
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            state = docker("inspect", "--format", "{{.State.Running}} {{.State.ExitCode}}", name).stdout.split()
            if state[0] != "true":
                return "exited", int(state[1])
            if docker("exec", name, "/usr/libexec/check-container", check=False).returncode == 0:
                return "ready", None
            time.sleep(2)
        raise AssertionError(f"{name}: {READY_TIMEOUT}s 안에 ready도 종료도 아님")

    def sql(self, name, query):
        done = docker("exec", "-e", f"PGPASSWORD={self.password}", name, "psql", "-X", "-q", "-At",
                      "-h", "127.0.0.1", "-U", "fds_lab", "-d", "fds_lab", "-v", "ON_ERROR_STOP=1", "-c", query,
                      check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def logs(self, name):
        done = docker("logs", name, check=False)
        return done.stdout + done.stderr

    def test_image_is_postgresql_16_non_root(self):
        version = docker("run", "--rm", "--network", "none", "--user", UID, "--entrypoint", "postgres", self.image,
                         "--version").stdout.strip()
        print("postgres:", version)
        self.assertRegex(version, r"^postgres \(PostgreSQL\) 16\.\d+", "PG17 금지 — db01과 같은 16 계열")
        user = docker("image", "inspect", "--format", "{{.Config.User}}", self.image).stdout.strip()
        self.assertNotIn(user, ("", "0", "root"))

    def test_image_start_order_matches_hook_choice(self):
        script = docker("run", "--rm", "--network", "none", "--entrypoint", "cat", self.image,
                        "/usr/bin/run-postgresql").stdout
        order = [script.index(s) for s in ("postgresql-init", "create_users\n", "postgresql-start", "exec postgres")]
        self.assertEqual(order, sorted(order), "start 훅은 계정·DB 생성 뒤, 서버 기동 전이어야 한다")

    def test_fresh_restart_broken_and_recovery(self):
        # (1) 빈 HOME 첫 기동
        good = self.volumes("good")
        name = self.create("good", good)
        docker("start", name)
        self.assertEqual(self.wait(name), ("ready", None), self.logs(name)[-3000:])
        self.assertIn("schema 0003 적용 완료", self.logs(name))
        self.assertEqual(self.sql(name, "select version_num from alembic_version"), "0003")
        self.assertEqual(self.sql(name, "select string_agg(distinct tableowner, ',') from pg_tables "
                                        "where schemaname='public'"), "fds_lab")
        self.assertEqual(self.sql(name, "select count(*) from pg_indexes where tablename='transactions'"), "3")
        self.assertEqual(self.sql(name, "insert into transactions (transaction_id, account_id, amount, "
                                        "transaction_type, occurred_at, received_at) values "
                                        "('it-1','a1',1,'TRANSFER',now(),now()) returning fds_evaluation_skipped"), "f")

        # (2) 같은 데이터로 재시작: 재적용 없이 ready, 데이터 유지
        docker("restart", name)
        self.assertEqual(self.wait(name), ("ready", None), self.logs(name)[-3000:])
        self.assertIn("재적용하지 않음", self.logs(name))
        self.assertEqual(self.sql(name, "select count(*) from transactions"), "1")

        # (3) 깨진 SQL 첫 기동: Ready 전에 종료, 같은 데이터로 다시 시작해도 종료
        broken = self.volumes("broken", "BEGIN;\nCREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);\n"
                                         "SELEC 1;\nCOMMIT;\n")
        bad = self.create("broken", broken)
        for attempt in (1, 2):
            docker("start", bad)
            state, code = self.wait(bad)
            self.assertEqual(state, "exited", f"attempt {attempt}: 깨진 schema로 ready가 되면 안 된다")
            self.assertNotEqual(code, 0)
        # 같은 컨테이너·같은 HOME 볼륨이라 두 번째 시작은 기존 PGDATA로 initdb를 건너뛴다(리뷰 B1의 재시작 조건).
        self.assertIn("schema 적용 실패", self.logs(bad))

        # (4) 고친 SQL로 같은 데이터 재시도: 복구
        shutil.copy(LABDB / "fds-schema.sql", broken["start"] / "fds-schema.sql")
        docker("start", bad)
        self.assertEqual(self.wait(bad), ("ready", None), self.logs(bad)[-3000:])
        self.assertEqual(self.sql(bad, "select version_num from alembic_version"), "0003")


if __name__ == "__main__":
    unittest.main()
