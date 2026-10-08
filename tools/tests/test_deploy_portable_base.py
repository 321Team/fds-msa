"""deploy/base에 환경 종속 값이 섞이지 않았는지, p1-onprem overlay가 고정 digest를 쓰는지 정적으로 확인한다."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "deploy" / "base"
P1 = ROOT / "deploy" / "overlays" / "p1-onprem"


def load_all(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def walk(obj, key=None):
    """(키, 값) 쌍을 재귀로 돌려준다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


class PortableBaseTests(unittest.TestCase):
    def setUp(self):
        kust = yaml.safe_load((BASE / "kustomization.yaml").read_text(encoding="utf-8"))
        self.docs = [d for f in kust["resources"] for d in load_all(BASE / f)]

    def test_base_has_no_environment_bound_values(self):
        text = "\n".join((BASE / f).read_text(encoding="utf-8") for f in ("transaction-api.yaml", "fds-engine.yaml",
                                                                          "networkpolicy.yaml"))
        self.assertIsNone(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text), "IP 주소는 overlay에 둔다")
        for doc in self.docs:
            self.assertNotIn("namespace", doc["metadata"], doc["metadata"]["name"])
            keys = {k for k, _ in walk(doc)}
            for banned in ("runAsUser", "runAsGroup", "fsGroup", "imagePullSecrets", "nodePort", "hostNetwork",
                           "hostPID", "hostPath"):
                self.assertNotIn(banned, keys, f"{doc['metadata']['name']}: {banned}")
            self.assertNotIn(doc["kind"], ("Route", "Ingress", "Secret", "ConfigMap", "Namespace"))
            if doc["kind"] == "Service":
                self.assertEqual(doc["spec"]["type"], "ClusterIP")

    def test_base_keeps_security_and_contract_intent(self):
        deps = {d["metadata"]["name"]: d for d in self.docs if d["kind"] == "Deployment"}
        self.assertEqual(set(deps), {"transaction-api", "fds-engine"})
        for name, dep in deps.items():
            pod = dep["spec"]["template"]["spec"]
            c = pod["containers"][0]
            self.assertEqual(c["image"], name, "이미지는 overlay images:로만 정한다")
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
            self.assertFalse(pod["automountServiceAccountToken"])
            sc = c["securityContext"]
            self.assertFalse(sc["allowPrivilegeEscalation"])
            self.assertTrue(sc["readOnlyRootFilesystem"])
            self.assertEqual(sc["capabilities"]["drop"], ["ALL"])
        api_env = deps["transaction-api"]["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual(api_env, [{"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {
            "name": "transaction-api-db-credentials", "key": "DATABASE_URL"}}}])
        self.assertNotIn("env", deps["fds-engine"]["spec"]["template"]["spec"]["containers"][0],
                         "fds-engine에는 DB 접속정보를 주지 않는다")

    def test_p1_overlay_pins_digests_and_is_marked_compare_only(self):
        text = (P1 / "kustomization.yaml").read_text(encoding="utf-8")
        kust = yaml.safe_load(text)
        self.assertEqual(kust["namespace"], "fds-app")
        for img in kust["images"]:
            self.assertRegex(img["digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertNotIn("newTag", img)
        self.assertIn("apply하지 않는다", text)


if __name__ == "__main__":
    unittest.main()
