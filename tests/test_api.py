import os
import tempfile
import unittest

from fastapi.testclient import TestClient


class ApiSmokeTest(unittest.TestCase):
    def setUp(self):
        # isolate DB per test run
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.tmpdir.name, "test.db")
        os.environ["DB_PATH"] = db_path

        # import after env set
        from app.main import create_app

        app = create_app()
        self.client = TestClient(app)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))

    def test_validate_dsl(self):
        payload = {"dsl_text": '{"description":"x","constraints":[{"name":"daily_coverage","shift":"D","min":1}]}' }
        r = self.client.post("/api/rules/validate", json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(r.json()["data"]["ok"])

    def test_master_crud_department(self):
        # create
        r = self.client.post("/api/master/departments", json={"code":"ER","name":"急診","is_active":True})
        self.assertEqual(r.status_code, 200)
        dep = r.json()["data"]
        self.assertEqual(dep["code"], "ER")

        # list
        r = self.client.get("/api/master/departments")
        self.assertEqual(r.status_code, 200)
        items = r.json()["data"]
        self.assertTrue(any(x["code"] == "ER" for x in items))

        # update
        dep_id = dep["id"]
        r = self.client.post("/api/master/departments", json={"id":dep_id,"code":"ER","name":"急診(更新)","is_active":True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["name"], "急診(更新)")

        # delete
        r = self.client.delete(f"/api/master/departments/{dep_id}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])


if __name__ == "__main__":
    unittest.main()
