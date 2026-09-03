import unittest
from fastapi.testclient import TestClient
from core.main import app
from core.services import (
    walk_json_path,
    is_partial,
    is_empty,
    discover_paths,
    ParserAnalyticsService
)

class TestParserPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_serves_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Parser Validation", response.text)

    def test_walk_json_path_nested_wildcard(self):
        data = {
            "details": {
                "locations": [
                    {"text": "Atlanta, GA"},
                    {"text": "Suwanee, GA"}
                ]
            }
        }
        extracted = walk_json_path(data, "root['details']['locations'][*]['text']")
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0][1], "Atlanta, GA")
        self.assertEqual(extracted[1][1], "Suwanee, GA")

    def test_is_partial(self):
        self.assertTrue(is_partial("lithia springs", "lithia springs, ga"))
        self.assertFalse(is_partial("Atlanta", "Atlanta"))
        self.assertFalse(is_partial("Python", "Java"))

    def test_is_empty(self):
        self.assertTrue(is_empty(""))
        self.assertTrue(is_empty([]))
        self.assertTrue(is_empty(None))
        self.assertTrue(is_empty({}))
        self.assertFalse(is_empty("value"))

    def test_discover_paths(self):
        data = {
            "details": {
                "locations": [{"text": "City"}],
                "skills": [{"name": "Python"}]
            }
        }
        paths = discover_paths(data)
        self.assertIn("root['details']['locations'][*]['text']", paths)
        self.assertIn("root['details']['skills'][*]['name']", paths)

    def test_api_connect_and_preview(self):
        # Test connect with local mongo
        conn_res = self.client.post("/api/connect", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3"
        })
        self.assertEqual(conn_res.status_code, 200)
        conn_json = conn_res.json()
        self.assertEqual(conn_json["status"], "connected")
        self.assertIn("total_documents", conn_json)

        # Test preview
        prev_res = self.client.post("/api/preview", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "sample_size": 2
        })
        self.assertEqual(prev_res.status_code, 200)
        prev_json = prev_res.json()
        self.assertGreater(len(prev_json["sample_documents"]), 0)
        self.assertGreater(len(prev_json["suggested_paths"]), 0)

    def test_api_analyze_and_export(self):
        # Test analyze pipeline on location path
        res = self.client.post("/api/analyze", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "path": "root['details']['locations'][*]['text']"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("summary", data)
        self.assertGreater(data["summary"]["total_documents"], 0)
        self.assertIn("chart_data", data)
        self.assertGreater(len(data["documents"]), 0)

        # Test CSV export
        csv_res = self.client.post("/api/export/csv", json={
            "mongo_uri": "mongodb://localhost:27017",
            "database": "maprecruit",
            "collection": "jd3",
            "path": "root['details']['locations'][*]['text']"
        })
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn("text/csv", csv_res.headers.get("content-type", ""))
        self.assertIn("document_id,v1_count,v3_count", csv_res.text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
